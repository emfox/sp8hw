#!/usr/bin/env python3
"""The whole pipeline, in order.

    fetch     Microsoft driver package -> the two verified AIQB blobs
    tools     the C dumpers, built against intel/ipu6-camera-bins
    dumps     those dumpers run over the blobs -> cmc-*.txt, lsc-*.txt
    generate  those dumps -> out/<sensor>.yaml

With no stage given, all four run. Each stage only needs the output of the
one before it, so any of them can be rerun on its own:

    ./sp8hw.py                       # everything
    ./sp8hw.py generate --out /tmp   # rebuild the yaml from the dumps
    ./sp8hw.py dumps                 # re-dump, leave the yaml alone

The blobs are fetched only when they are missing; pass --msi to reuse a
driver package you already have (or set MSI in the environment).
"""

import argparse
import os
import subprocess
import sys

import aiqb
import ipu6
import tuning

HERE = os.path.dirname(os.path.abspath(__file__))

STAGES = ("fetch", "tools", "dumps", "generate")


def _step(index, total, stage, what):
    print("\n[%d/%d] %s: %s" % (index, total, stage, what))


def _blobs():
    return [os.path.join(HERE, blob) for _, blob, _ in tuning.SENSORS]


def fetch(msi=None, force=False):
    """Stage 1: download the driver package, extract and verify the blobs.

    Skipped when the blobs are already there, unless the stage was asked for
    by name: `sp8hw.py fetch` always goes back to the package.
    """
    if not force and msi is None and all(os.path.exists(p) for p in _blobs()):
        print("  blobs already here: " +
              ", ".join(os.path.basename(p) for p in _blobs()))
        return

    env = dict(os.environ)
    if msi:
        env["MSI"] = os.path.abspath(msi)
    # fetch-aiqb.sh writes the blobs next to itself and explains its own
    # failures (missing 7z, no .msi on the index page), so pass those on.
    proc = subprocess.run([os.path.join(HERE, "fetch-aiqb.sh")], cwd=HERE,
                          env=env)
    if proc.returncode:
        sys.exit(proc.returncode)


def tools(bins=None, cc=None):
    """Stage 2: build both dumpers against ipu6-camera-bins."""
    toolchain = ipu6.Toolchain(bins, cc)
    print("  ipu6-camera-bins: %s" % (toolchain.bins or "(prebuilt dumpers)"))
    for kind in ipu6.SOURCES:
        print("  %s: %s" % (kind, os.path.relpath(toolchain.binary(kind), HERE)))
    return toolchain


def dumps(toolchain, directory=None):
    """Stage 3: run the dumpers and keep their output."""
    directory = directory or HERE
    for _, blob, where in tuning.SENSORS:
        texts = tuning.run_dumpers(toolchain, os.path.join(HERE, blob), where,
                                  directory)
        names = {kind: os.path.basename(tuning.dump_path(directory, kind, where))
                 for kind in texts}
        print("  %-5s %s (%d lines), %s (%d lines)"
              % (where, names["cmc"], texts["cmc"].count("\n"),
                 names["lsc"], texts["lsc"].count("\n")))


def generate(outdir, bins=None, cc=None, dumps_dir=None):
    """Stage 4: assemble the tuning files."""
    tuning.generate(outdir, bins, cc, dumps=dumps_dir)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Surface Pro 8 camera calibration -> libcamera tuning files",
        epilog="stages run in order: " + " -> ".join(STAGES) +
               "; with no stage, all of them run.")
    ap.add_argument("stage", nargs="*", default=[], metavar="stage",
                    help="fetch, tools, dumps, generate, or all (default: all)")
    ap.add_argument("--out", default="out", help="tuning files (default: out)")
    ap.add_argument("--bins", help="ipu6-camera-bins checkout ($IPU6_BINS)")
    ap.add_argument("--cc", help="C compiler ($CC)")
    ap.add_argument("--msi", help="driver package already downloaded")
    ap.add_argument("--dumps", metavar="DIR",
                    help="where the dumps live (default: next to the blobs)")
    args = ap.parse_args(argv)

    unknown = [s for s in args.stage if s not in STAGES + ("all",)]
    if unknown:
        ap.error("unknown stage %r" % unknown[0])

    wanted = []
    for name in args.stage or ["all"]:
        wanted += list(STAGES) if name == "all" else [name]
    explicit = set(args.stage) - {"all"}

    toolchain = None
    try:
        for index, stage in enumerate(wanted, 1):
            if stage == "fetch":
                _step(index, len(wanted), stage, "driver package -> AIQB blobs")
                fetch(args.msi, force="fetch" in explicit)
            elif stage == "tools":
                _step(index, len(wanted), stage, "AIQB dumpers -> build/")
                toolchain = tools(args.bins, args.cc)
            elif stage == "dumps":
                _step(index, len(wanted), stage, "blobs -> cmc-*.txt, lsc-*.txt")
                dumps(toolchain or tools(args.bins, args.cc), args.dumps)
            elif stage == "generate":
                _step(index, len(wanted), stage, "dumps -> %s/*.yaml" % args.out)
                generate(args.out, args.bins, args.cc,
                         args.dumps or (HERE if "dumps" in wanted else None))
    except (aiqb.AiqbError, ipu6.ToolchainError) as e:
        sys.exit(str(e))
    except subprocess.CalledProcessError as e:
        sys.exit("%s failed" % e.cmd[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
