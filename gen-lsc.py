#!/usr/bin/env python3
"""Turn the aiqb lens-shading grids into a libcamera softisp Lsc tuning section.

The aiqb keeps 63x47 gain grids per light source and per Bayer channel, in
fixed point with `fraction_bits` fraction bits. libcamera wants 17x17 float
tables (keyed r/g/b) where 64.0 means gain 1.0 (UQ<2,6> byte in the LUT).
"""
import sys, re

GRID = 17


def parse(path):
    """-> [ {'rg':, 'bg':, 'ch': {(r,c): [[...]]}} ]"""
    out = []
    cur = None
    chan = None
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("LS "):
                m = re.match(r"LS (\d+) type (\d+) rg ([\d.]+) bg ([\d.]+)", line)
                cur = {"ls": int(m.group(1)), "type": int(m.group(2)),
                       "rg": float(m.group(3)), "bg": float(m.group(4)), "ch": {}}
                out.append(cur)
                chan = None
            elif line.startswith("CH "):
                r, c = line.split()[1:3]
                chan = (int(r), int(c))
                cur["ch"][chan] = []
            elif line and line[0].isdigit() and chan:
                cur["ch"][chan].append([int(v) for v in line.split()])
    return out


def bilinear(grid, w, h, nx, ny):
    """Resample w x h grid to nx x ny (grid[y][x])."""
    out = []
    for j in range(ny):
        fy = j * (h - 1) / (ny - 1)
        y0 = int(fy)
        y1 = min(y0 + 1, h - 1)
        ty = fy - y0
        row = []
        for i in range(nx):
            fx = i * (w - 1) / (nx - 1)
            x0 = int(fx)
            x1 = min(x0 + 1, w - 1)
            tx = fx - x0
            v = (grid[y0][x0] * (1 - tx) * (1 - ty) + grid[y0][x1] * tx * (1 - ty) +
                 grid[y1][x0] * (1 - tx) * ty + grid[y1][x1] * tx * ty)
            row.append(v)
        out.append(row)
    return out


def normalise(grid, w, h):
    """Scale so that the value at the optical centre becomes 64.0 (= gain 1.0).

    Anything above 255 is clamped: that is the top of UQ<2,6>, 3.98x.  The
    centre keeps its gain, the corners lose whatever does not fit.
    """
    ref = grid[h // 2][w // 2]
    return [[min(v / ref * 64.0, 255.0) for v in row] for row in grid]


def flatten(grid):
    """The tuning file carries the values in the register format, i.e. whole
    numbers from 0 to 255, so round here rather than leaving the truncation to
    the cast into the uint8_t lookup table."""
    return [int(round(v)) for row in grid for v in row]


def emit(sets, path):
    with open(path, "w") as f:
        f.write("  - Lsc:\n      type: table\n      sets:\n")
        for ct, comp in sets:
            f.write("        - ct: %d\n" % ct)
            for k in ("r", "g", "b"):
                vals = flatten(comp[k])
                assert len(vals) == GRID * GRID, (ct, k, len(vals))
                f.write("          %s: [\n" % k)
                for i in range(0, len(vals), GRID):
                    f.write("            " + ", ".join("%d" % v for v in vals[i:i + GRID]) + ",\n")
                f.write("          ]\n")


CT_ANCHORS = [(2514, 0.982, 2.138), (2848, 1.141, 2.093), (2870, 1.121, 1.991),
              (3786, 1.439, 1.698), (5438, 1.713, 1.405), (6366, 1.952, 1.300)]
# r_per_g, b_per_g implied by the AWB gain table; used to label a light source.
ANCH = [(ct, 1.0 / rg, 1.0 / bg) for ct, rg, bg in CT_ANCHORS]


def nearest_ct(rg, bg):
    return min(ANCH, key=lambda a: (a[1] - rg) ** 2 + (a[2] - bg) ** 2)


def main():
    global ANCH
    src, out = sys.argv[1], sys.argv[2]
    if len(sys.argv) > 3:
        spec = []
        for item in sys.argv[3].split(","):
            ct, rg, bg = item.split(":")
            spec.append((int(ct), float(rg), float(bg)))
        ANCH = [(ct, 1.0 / rg, 1.0 / bg) for ct, rg, bg in spec]
    groups = parse(src)
    w = len(groups[0]["ch"][(0, 0)][0])
    h = len(groups[0]["ch"][(0, 0)])

    # The blob has more light sources than the AWB table has entry points, so
    # several grids share a colour temperature. Resample and normalise each of
    # them on its own, then average the ones that land on the same ct; keeping
    # only the first of them would throw away half the calibration.
    buckets = {}
    for g in groups:
        ct, _, _ = nearest_ct(g["rg"], g["bg"])
        buckets.setdefault(ct, []).append(g)

    sets = []
    for ct in sorted(buckets):
        comp = {}
        for key, cells in (("r", [(0, 0)]), ("b", [(1, 1)]),
                           ("g", [(0, 1), (1, 0)])):
            acc = [[0.0] * GRID for _ in range(GRID)]
            weight = len(cells) * len(buckets[ct])
            for g in buckets[ct]:
                for cell in cells:
                    small = normalise(bilinear(g["ch"][cell], w, h, GRID, GRID), GRID, GRID)
                    for y in range(GRID):
                        for x in range(GRID):
                            acc[y][x] += small[y][x] / weight
            comp[key] = acc
        sets.append((ct, comp))

    emit(sets, out)
    print("light sources: %d, sets: %d (%s)" %
          (len(groups), len(sets), ", ".join(str(s[0]) for s in sets)))


main()
