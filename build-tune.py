#!/usr/bin/env python3
"""Build a softisp tuning file for the Surface Pro 8 cameras from the aiqb.

One command produces the whole file: the colour gains and matrices come from
gen-tuning.py, the lens shading tables from gen-lsc.py, both fed by the same
blob. Nothing is edited by hand afterwards, so the result is reproducible:

    python3 build-tune.py <outdir>
"""
import importlib.util
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

SENSORS = (
    # name, aiqb, lsc dump, where the camera sits
    ("ov13858", "OV13858_MSHW0261_TGL.aiqb", "lsc-rear.txt", "rear"),
    ("ov5693", "OV5693_MSHW0220_TGL.aiqb", "lsc-front.txt", "front"),
)

HEADER = """\
# Calibrated from the AIQB blob shipped with the Windows camera driver of
# the Surface Pro 8 {where} camera. The colour gains are the inverse of the
# white point of each light source, and the lens shading and colour matrix
# tables come from the same blob, so all three agree with each other."""


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build(name, aiqb, dump, where, outdir):
    gt = load("gt-" + name, os.path.join(HERE, "gen-tuning.py"))
    rows = gt.lightsources(os.path.join(HERE, aiqb))

    base = os.path.join(outdir, name + ".base")
    subprocess.run([PY, os.path.join(HERE, "gen-tuning.py"), os.path.join(HERE, aiqb),
                    "-o", base, "--sensor", name], check=True)

    # The LSC sets are keyed on the colour temperature AWB reports, so the
    # anchors are exactly the AWB entry points of this sensor.
    anchors = ",".join("%d:%f:%f" % (ct, gr, gb) for ct, gr, gb, _ in rows)
    lsc = os.path.join(outdir, name + ".lsc")
    subprocess.run([PY, os.path.join(HERE, "gen-lsc.py"), os.path.join(HERE, dump),
                    lsc, anchors], check=True)

    lines = open(base).read().splitlines()
    assert lines[0].startswith("# SPDX"), lines[0]
    out = [lines[0], HEADER.format(where=where)]
    lsc_lines = open(lsc).read().splitlines()
    for line in lines[1:]:
        if line.startswith("  - Ccm:"):
            out.extend(lsc_lines)
        out.append(line)

    path = os.path.join(outdir, name + ".yaml")
    text = "\n".join(out) + "\n"
    with open(path, "w") as f:
        f.write(text)
    print("%s: %d 光源, %d 行 -> %s" % (name, len(rows), len(text.splitlines()), path))
    return path


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(outdir, exist_ok=True)
    for name, aiqb, dump, where in SENSORS:
        build(name, aiqb, dump, where, outdir)


if __name__ == "__main__":
    main()
