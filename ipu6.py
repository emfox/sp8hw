"""The Intel side of the pipeline: find ipu6-camera-bins, build the two
dumpers against it, and run them on a blob.

The dumpers are thin C adapters over the vendor parser (native/), so the
only things that can go wrong here are the three paths involved: the header
directory, the shared libraries, and the binary itself. Keeping them in one
place means the rest of the pipeline never has to know about IPU6_BINS,
LD_LIBRARY_PATH or include paths.
"""

import os
import subprocess
import sys

import aiqb

HERE = os.path.dirname(os.path.abspath(__file__))
NATIVE = os.path.join(HERE, "native")
BUILD = os.path.join(HERE, "build")

# what the pipeline needs from ipu6-camera-bins
PARSER = "libia_cmc_parser-ipu6.so.0"
LOG = "libia_log-ipu6.so.0"

SOURCES = {"cmc": "dump-cmc.c", "lsc": "dump-lsc.c"}


class ToolchainError(Exception):
    """ipu6-camera-bins is missing or does not have what we link against."""


def find_bins(explicit=None):
    """A checkout of intel/ipu6-camera-bins.

    In order: what the caller asked for, $IPU6_BINS, a sibling checkout
    next to this repository, then the usual place under $HOME.
    """
    candidates = [explicit,
                  os.environ.get("IPU6_BINS"),
                  os.path.join(HERE, "..", "ipu6-camera-bins"),
                  os.path.expanduser("~/src/ipu6-camera-bins")]

    for path in candidates:
        if path and os.path.isfile(os.path.join(path, "lib", PARSER)):
            return os.path.abspath(path)

    raise ToolchainError(
        "no ipu6-camera-bins checkout with lib/%s; clone\n"
        "    https://github.com/intel/ipu6-camera-bins\n"
        "and point IPU6_BINS at it" % PARSER)


class Toolchain:
    """Build and run the dumpers of one ipu6-camera-bins checkout."""

    def __init__(self, bins=None, cc=None):
        self.bins = None
        try:
            self.bins = find_bins(bins)
        except ToolchainError:
            # Prebuilt dumpers do not need the checkout, only the libraries
            # they were linked against, and those are found by the loader.
            if not all(os.environ.get("SP8HW_DUMP_" + k.upper())
                       for k in SOURCES):
                raise
        self.include = os.path.join(self.bins or "", "include", "ipu6",
                                    "ia_imaging")
        self.lib = os.path.join(self.bins, "lib") if self.bins else ""
        self.cc = cc or os.environ.get("CC") or "cc"

    def binary(self, kind):
        """Path of a built dumper, compiling it first if it is stale.

        $SP8HW_DUMP_CMC / $SP8HW_DUMP_LSC replace the compiled binary, for
        running a dumper built elsewhere.
        """
        override = os.environ.get("SP8HW_DUMP_" + kind.upper())
        if override:
            return override

        src = os.path.join(NATIVE, SOURCES[kind])
        out = os.path.join(BUILD, kind)
        if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(src):
            return out

        os.makedirs(BUILD, exist_ok=True)
        cmd = [self.cc, "-O2", "-Wall", "-o", out, src, "-I" + self.include,
               os.path.join(self.lib, PARSER), os.path.join(self.lib, LOG)]
        print("  cc -o %s %s" % (os.path.relpath(out, HERE),
                                 os.path.relpath(src, HERE)))
        subprocess.run(cmd, check=True)
        return out

    def run(self, kind, blob):
        """Dump one blob; returns the dumper's stdout."""
        binary = self.binary(kind)
        env = dict(os.environ)
        if self.lib:
            env["LD_LIBRARY_PATH"] = self.lib
        proc = subprocess.run([binary, blob, hex(aiqb.chunk_offset(blob))],
                              env=env, capture_output=True, text=True)
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr)
            raise ToolchainError("%s failed on %s" % (binary, blob))
        return proc.stdout
