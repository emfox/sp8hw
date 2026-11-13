"""Stage 4: assemble one tuning file per sensor.

    blob (AIQB) --dump--> text --parse--> records --render--> sections --+
                                                                        |
                                        out/<sensor>.yaml <--assemble--+

The order of the sections is libcamera's, not ours: Awb, then Lsc, then Ccm.
The assembler walks the blocks colour.py hands it and drops the shading
table in just before the matrix table, so no stage has to splice text.
"""

import argparse
import os
import sys

import aiqb
import colour
import ipu6
import lsc

HERE = os.path.dirname(os.path.abspath(__file__))

# name, blob, where the camera sits. The blob names are Microsoft's; the
# cabs inside the driver package store them under hashes, fetch-aiqb.sh
# maps them back.
SENSORS = (
    ("ov13858", "OV13858_MSHW0261_TGL.aiqb", "rear"),
    ("ov5693", "OV5693_MSHW0220_TGL.aiqb", "front"),
)

HEADER = """\
# Calibrated from the AIQB blob shipped with the Windows camera driver of
# the Surface Pro 8 {where} camera. The colour gains are the inverse of the
# white point of each light source, and the lens shading and colour matrix
# tables come from the same blob, so all three agree with each other."""

DUMP_NAMES = {"cmc": "cmc-%s.txt", "lsc": "lsc-%s.txt"}


def dump_path(directory, kind, where):
    return os.path.join(directory, DUMP_NAMES[kind] % where)


def assemble(name, where, sources, lsc_lines):
    """The whole tuning file, as a list of lines."""
    out = [colour.LICENCE]
    out += HEADER.format(where=where).splitlines()
    for key, block in colour.blocks(sources, name):
        if key == "ccm":
            # The ISP interpolates shading before it applies the matrix, so
            # the table belongs in front of it.
            out += lsc_lines
        out += block
    return out


def from_dumps(directory, where):
    """The two dump texts of a sensor, as written by an earlier run."""
    texts = {}
    for kind in DUMP_NAMES:
        path = dump_path(directory, kind, where)
        if not os.path.exists(path):
            raise aiqb.AiqbError("no dump at %s (run the dumps stage first)"
                                 % path)
        with open(path) as f:
            texts[kind] = f.read()
    return texts


def run_dumpers(toolchain, blob, where, directory):
    """Dump a blob and keep both texts, so a later run can start here."""
    os.makedirs(directory, exist_ok=True)
    texts = {}
    for kind in DUMP_NAMES:
        texts[kind] = toolchain.run(kind, blob)
        with open(dump_path(directory, kind, where), "w") as f:
            f.write(texts[kind])
    return texts


def sensor(name, blob, where, outdir, toolchain=None, dumps=None):
    """One sensor: dumps -> records -> out/<name>.yaml.

    `dumps` reads texts an earlier run left in that directory, `toolchain`
    runs the dumpers and writes them next to the blobs; exactly one of the
    two is given.
    """
    if dumps:
        texts = from_dumps(dumps, where)
    else:
        texts = run_dumpers(toolchain, os.path.join(HERE, blob), where, HERE)

    sources = aiqb.parse_cmc(texts["cmc"])
    _, _, shadings = aiqb.parse_lsc(texts["lsc"])
    anchors = lsc.anchors_from_sources(sources)
    sets = lsc.tables(shadings, anchors)

    lines = assemble(name, where, sources, lsc.block(sets))
    out = os.path.join(outdir, name + ".yaml")
    with open(out, "w") as f:
        f.write("\n".join(lines) + "\n")

    print("  %-8s %d light sources, %d shading grids -> %d sets, %d lines -> %s"
          % (name, len(sources), len(shadings), len(sets), len(lines), out))
    return out


def generate(outdir, bins=None, cc=None, dumps=None):
    """Every sensor of the table; returns the files written."""
    os.makedirs(outdir, exist_ok=True)
    toolchain = None if dumps else ipu6.Toolchain(bins, cc)
    return [sensor(name, blob, where, outdir, toolchain, dumps)
            for name, blob, where in SENSORS]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", nargs="?", default="out",
                    help="output directory (default: out)")
    ap.add_argument("--bins", help="ipu6-camera-bins checkout ($IPU6_BINS)")
    ap.add_argument("--cc", help="C compiler ($CC)")
    ap.add_argument("--dumps", metavar="DIR",
                    help="reuse the cmc-*.txt/lsc-*.txt in DIR instead of "
                         "running the dumpers")
    args = ap.parse_args(argv)

    try:
        generate(args.out, args.bins, args.cc, args.dumps)
    except (aiqb.AiqbError, ipu6.ToolchainError) as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
