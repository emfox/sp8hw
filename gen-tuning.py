#!/usr/bin/env python3
"""Generate a libcamera soft ISP tuning file from an Intel aiqb.

The aiqb is a CPFF container. ia_cmc_parser_init_v1() has to be handed the
inner AIQB chunk, not the whole file, otherwise it walks off the end of the
buffer while looking for its block chain.
"""

import argparse
import os
import shutil
import struct
import subprocess
import sys

# dump2 is the small dumper that walks the CMC structures with the Intel
# parser; point IAQ_DUMP2 at it, or put it in PATH.
DUMP2 = os.environ.get("IAQ_DUMP2") or shutil.which("dump2") or "dump2"
LIBDIR = os.environ.get("IAQ_LIBDIR", "")


def find_aiqb(data):
    off = data.find(b"AIQB")
    while off != -1:
        size = struct.unpack_from("<I", data, off + 4)[0]
        if 0 < size <= len(data) - off:
            return off
        off = data.find(b"AIQB", off + 1)
    raise SystemExit("no AIQB chunk found")


def mccamy(x, y):
    """Correlated colour temperature from CIE xy (McCamy 1992)."""
    n = (x - 0.3320) / (0.1858 - y)
    return 449.0 * n ** 3 + 3525.0 * n ** 2 + 6823.1 * n + 5520.33


def lightsources(aiqb):
    off = find_aiqb(open(aiqb, "rb").read())
    env = dict(os.environ)
    if LIBDIR:
        env["LD_LIBRARY_PATH"] = LIBDIR
    out = subprocess.run([DUMP2, aiqb, hex(off)], env=env, check=True,
                         capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        if not line.startswith("YAML "):
            continue
        f = line.split()
        cct, x, y = int(f[1]), float(f[2]), float(f[3])
        # Older aiqb files carry no CCT field, fall back to the CIE xy of the
        # light source, which agrees with the stored CCT within ~1%.
        if not 1500 <= cct <= 20000:
            cct = round(mccamy(x, y))
        rows.append((cct, float(f[4]), float(f[5]),
                     [float(v) for v in f[6:15]]))

    if not rows:
        raise SystemExit("no light sources dumped")

    rows.sort(key=lambda r: r[0])
    unique = []
    for r in rows:
        if unique and r[0] - unique[-1][0] < 20:
            continue
        unique.append(r)
    return unique


def priors(rows):
    """Flat prior: no assumption about which illuminant is likely.

    A peaked prior pulls the estimator towards whatever temperature it is
    centred on: a 4000 K hump dragged a 5700 K LED down to 3790 K and left
    a white sheet 6% blue. With no illuminant statistics for this module,
    every calibrated source is equally likely.
    """
    return [1.0 / len(rows)] * len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("aiqb")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--sensor", help="sensor name for the comment")
    ap.add_argument("--no-ccm", action="store_true",
                    help="omit the CCM section. The gains and the matrices are "
                         "one calibration, so both are emitted by default")
    ap.add_argument("--black-level", type=int, default=None,
                    help="black level in the tuning file's 16 bit convention; "
                         "left out by default, the sensor helper knows it")
    args = ap.parse_args()

    rows = lightsources(args.aiqb)
    prob = priors(rows)
    cts = [r[0] for r in rows]
    name = args.sensor or os.path.basename(args.out).rsplit(".", 1)[0]

    L = []
    L.append("# SPDX-License-Identifier: CC0-1.0")
    L.append("%YAML 1.1")
    L.append("---")
    L.append("version: 1")
    L.append("algorithms:")
    L.append("  - BlackLevel:")
    if args.black_level is not None:
        L.append(f"      blackLevel: {args.black_level}")
    L.append("  - Awb:")
    L.append("      algorithm: bayes")
    L.append("      # Colour gains and matrices are the calibrated values of the")
    L.append(f"      # vendor aiqb of the {name}; each gain is the inverse of the")
    L.append("      # white point of its light source, so both agree.")
    L.append("      colourGains:")
    for ct, gr, gb, _ in rows:
        L.append(f"        - ct: {ct}")
        L.append(f"          gains: [ {gr:.5f}, {gb:.5f} ]")
    L.append("      # Flat priors: there are no illuminant statistics for these")
    L.append("      # modules, so every calibrated source is equally likely.")
    L.append("      priors:")
    for lux in (0, 100):
        L.append(f"        - lux: {lux}")
        L.append("          ct: [ " + ", ".join(str(c) for c in cts) + " ]")
        L.append("          probability: [ "
                 + ", ".join(f"{p:.6f}" for p in prob) + " ]")
    L.append("      AwbMode:")
    L.append("        Auto:")
    L.append(f"          lo: {min(cts) - 200}")
    L.append(f"          hi: {max(cts) + 900}")
    if args.no_ccm:
        L.append("  - Adjust:")
        L.append("  - Agc:")
        L.append("...")
        with open(args.out, "w") as f:
            f.write("\n".join(L) + "\n")
        print(f"wrote {args.out}: {len(rows)} light sources "
              f"({cts[0]}..{cts[-1]}K), no CCM")
        return

    L.append("  - Ccm:")
    L.append("      ccms:")
    for ct, _, _, m in rows:
        L.append(f"        - ct: {ct}")
        L.append("          ccm: [ " + ", ".join(f"{v:.5f}" for v in m[:3])
                 + ",")
        L.append("                 " + ", ".join(f"{v:.5f}" for v in m[3:6])
                 + ",")
        L.append("                 " + ", ".join(f"{v:.5f}" for v in m[6:9])
                 + " ]")
        L.append("          offsets: [ 0, 0, 0 ]")
    L.append("  - Adjust:")
    L.append("  - Agc:")
    L.append("...")

    with open(args.out, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"wrote {args.out}: {len(rows)} light sources "
          f"({cts[0]}..{cts[-1]}K)")


if __name__ == "__main__":
    main()
