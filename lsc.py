"""The lens-shading half of a tuning file: the Lsc section.

The blob keeps a 63x47 gain grid per light source and Bayer channel, in
fixed point. libcamera wants 17x17 byte tables keyed r/g/b, where 64.0 means
gain 1.0 (UQ<2,6>). So each grid is resampled, normalised to its own centre,
and finally the grids that land on the same colour temperature are averaged:
the blob has more light sources than the AWB table has entry points, and
keeping only the first of each would throw away half the calibration.
"""

import aiqb

GRID = 17
CENTRE = 64.0
MAX = 255.0

# Bayer cells of the 2x2 pattern the grid covers. The blob also prints its
# own grid indices, but they are the same layout for both modules here.
CELLS = (("r", [(0, 0)]), ("b", [(1, 1)]), ("g", [(0, 1), (1, 0)]))

# AWB gains of the entry points these modules are calibrated at, used only
# when nothing better is passed in. tuning.py always hands over the gains of
# the blob it is converting, which is where the truth is.
DEFAULT_GAINS = ((2514, 0.982, 2.138), (2848, 1.141, 2.093),
                 (2870, 1.121, 1.991), (3786, 1.439, 1.698),
                 (5438, 1.713, 1.405), (6366, 1.952, 1.300))


def anchors_from_gains(gains):
    """(ct, r/g, b/g) per light source, in chromaticity rather than gain.

    The blob labels a grid by its chromaticity while the AWB table is
    written in gains, so invert once here and compare like with like.
    """
    return [(ct, 1.0 / r, 1.0 / b) for ct, r, b in gains]


def anchors_from_sources(sources):
    return anchors_from_gains([(s.ct, s.r_gain, s.b_gain) for s in sources])


def nearest(anchors, r_per_g, b_per_g):
    return min(anchors, key=lambda a: (a[1] - r_per_g) ** 2 + (a[2] - b_per_g) ** 2)


def resample(grid, nx, ny):
    """Bilinear resample of a height x width grid to ny x nx."""
    h, w = len(grid), len(grid[0])
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


def normalise(grid):
    """Scale so the optical centre becomes 1.0, and clamp to what fits.

    Anything above 255 is dropped: that is the top of UQ<2,6>, 3.98x. The
    centre keeps its gain, the corners lose whatever does not fit.
    """
    ref = grid[len(grid) // 2][len(grid[0]) // 2]
    return [[min(v / ref * CENTRE, MAX) for v in row] for row in grid]


def _average(grids, cells):
    """Mean of the given Bayer cells over the given grids, 17x17."""
    acc = [[0.0] * GRID for _ in range(GRID)]
    weight = len(cells) * len(grids)
    for g in grids:
        for cell in cells:
            small = normalise(resample(g.cells[cell], GRID, GRID))
            for y in range(GRID):
                for x in range(GRID):
                    acc[y][x] += small[y][x] / weight
    return acc


def tables(shadings, anchors):
    """[(ct, {'r': grid, 'g': grid, 'b': grid})], one entry per anchor."""
    buckets = {}
    for s in shadings:
        ct, _, _ = nearest(anchors, s.r_per_g, s.b_per_g)
        buckets.setdefault(ct, []).append(s)

    out = []
    for ct in sorted(buckets):
        comp = {key: _average(buckets[ct], cells) for key, cells in CELLS}
        out.append((ct, comp))
    return out


def block(sets):
    """The Lsc section as YAML lines."""
    out = ["  - Lsc:", "      type: table", "      sets:"]
    for ct, comp in sets:
        out.append("        - ct: %d" % ct)
        for key in ("r", "g", "b"):
            vals = [int(round(v)) for row in comp[key] for v in row]
            assert len(vals) == GRID * GRID, (ct, key, len(vals))
            out.append("          %s: [" % key)
            for i in range(0, len(vals), GRID):
                out.append("            " +
                           ", ".join("%d" % v for v in vals[i:i + GRID]) + ",")
            out.append("          ]")
    return out


def build(shadings, anchors=None):
    """The Lsc section for one blob's shading grids."""
    if anchors is None:
        anchors = anchors_from_gains(DEFAULT_GAINS)
    return block(tables(shadings, anchors))


def main(argv):
    """lsc.py <dump> <out> [ct:gain_r:gain_b,...]"""
    if len(argv) < 3:
        raise SystemExit("usage: %s <lsc dump> <out> [anchors]" % argv[0])
    src, dst = argv[1], argv[2]

    anchors = None
    if len(argv) > 3:
        gains = []
        for item in argv[3].split(","):
            ct, r, b = item.split(":")
            gains.append((int(ct), float(r), float(b)))
        anchors = anchors_from_gains(gains)

    width, height, shadings = aiqb.parse_lsc(open(src).read())
    lines = build(shadings, anchors)
    with open(dst, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("grid %dx%d, light sources: %d, sets: %d"
          % (width, height, len(shadings),
             sum(1 for line in lines if line.startswith("        - ct: "))))


if __name__ == "__main__":
    import sys
    main(sys.argv)
