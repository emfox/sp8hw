"""The AIQB blob itself: where the parser's chunk starts, and what the
dumpers print for it.

An .aiqb file is a CPFF container, not the chunk the Intel parser wants:
ia_cmc_parser_init_v1() has to be handed the inner AIQB chunk, otherwise it
walks off the end of the buffer while looking for its block chain. Every
stage that touches a blob therefore starts from `chunk_offset()` here,
instead of each one guessing an offset of its own.

The rest of the module reads the two line-oriented dumps the C helpers in
native/ print, and turns them into plain records (`LightSource`, `Shading`)
that the tuning writers can use without knowing about ia_cmc types.
"""

import struct

MAGIC = b"AIQB"


class AiqbError(Exception):
    """A blob or a dump does not look the way the pipeline expects."""


# -- the container -----------------------------------------------------

def chunk_offset(path):
    """Offset of the AIQB chunk inside the CPFF container.

    The chunk is not always at 0x38, so let the file say where it is: take
    the first 'AIQB' whose length field stays inside the file.
    """
    with open(path, "rb") as f:
        data = f.read()

    off = data.find(MAGIC)
    while off != -1:
        if off + 8 <= len(data):
            size = struct.unpack_from("<I", data, off + 4)[0]
            if 0 < size <= len(data) - off:
                return off
        off = data.find(MAGIC, off + 1)

    raise AiqbError("%s: no AIQB chunk in this container" % path)


# -- colour temperature -------------------------------------------------

def mccamy(x, y):
    """Correlated colour temperature from CIE xy (McCamy 1992)."""
    n = (x - 0.3320) / (0.1858 - y)
    return 449.0 * n ** 3 + 3525.0 * n ** 2 + 6823.1 * n + 5520.33


# -- records ------------------------------------------------------------

class LightSource:
    """One calibrated illuminant: where it sits, and what it implies.

    `r_gain` and `b_gain` are the white point of the source inverted, which
    is what the AWB algorithm wants; `ccm` is the 3x3 colour matrix that
    belongs to the same measurement.
    """

    __slots__ = ("ct", "cie_x", "cie_y", "r_gain", "b_gain", "ccm")

    def __init__(self, ct, cie_x, cie_y, r_gain, b_gain, ccm):
        self.ct = ct
        self.cie_x = cie_x
        self.cie_y = cie_y
        self.r_gain = r_gain
        self.b_gain = b_gain
        self.ccm = tuple(ccm)

    def __repr__(self):
        return "LightSource(%dK, gains %.5f/%.5f)" % (self.ct, self.r_gain,
                                                      self.b_gain)


class Shading:
    """One lens-shading measurement from the blob.

    `cells` holds the Bayer cells the blob carries, keyed by (row, col) in
    the 2x2 pattern; each value is a `height` x `width` grid of fixed point
    gains with `fraction_bits` fraction bits.
    """

    __slots__ = ("index", "source_type", "r_per_g", "b_per_g", "cie_x",
                 "cie_y", "fraction_bits", "cells")

    def __init__(self, index, source_type, r_per_g, b_per_g, cie_x, cie_y,
                 fraction_bits):
        self.index = index
        self.source_type = source_type
        self.r_per_g = r_per_g
        self.b_per_g = b_per_g
        self.cie_x = cie_x
        self.cie_y = cie_y
        self.fraction_bits = fraction_bits
        self.cells = {}

    def __repr__(self):
        return "Shading(ls %d, %.3f/%.3f)" % (self.index, self.r_per_g,
                                              self.b_per_g)


# -- parsing the dumps --------------------------------------------------

def parse_cmc(text):
    """Light sources from a `dump-cmc` run, sorted by colour temperature.

    Each 'YAML' line carries cct, the CIE xy of the source, the two gains
    and the nine matrix coefficients.
    """
    rows = []
    for line in text.splitlines():
        if not line.startswith("YAML "):
            continue
        f = line.split()
        if len(f) < 15:
            raise AiqbError("short CMC line: %r" % line)

        ct, x, y = int(f[1]), float(f[2]), float(f[3])
        # Older blobs carry no CCT field, fall back to the CIE xy of the
        # light source, which agrees with a stored CCT within ~1%.
        if not 1500 <= ct <= 20000:
            ct = int(round(mccamy(x, y)))

        rows.append(LightSource(ct, x, y, float(f[4]), float(f[5]),
                                [float(v) for v in f[6:15]]))

    if not rows:
        raise AiqbError("no light sources in the CMC dump")

    rows.sort(key=lambda r: r.ct)

    # The blob sometimes measures the same illuminant twice; two entry
    # points 20 K apart would only cost the estimator resolution.
    unique = []
    for r in rows:
        if unique and r.ct - unique[-1].ct < 20:
            continue
        unique.append(r)
    return unique


def parse_lsc(text):
    """Lens-shading grids from a `dump-lsc` run.

    Returns (width, height, [Shading]). The grid size is taken from the
    '# grid' header when the dumper prints one, so a blob with an unusual
    geometry still reads.
    """
    width = height = None
    grids = []
    cur = None
    cell = None

    for line in text.splitlines():
        if line.startswith("# grid "):
            f = line.split()
            width, height = int(f[2]), int(f[3])
        elif line.startswith("LS "):
            f = line.split()
            cur = Shading(index=int(f[1]), source_type=int(f[3]),
                          r_per_g=float(f[5]), b_per_g=float(f[7]),
                          cie_x=float(f[9]), cie_y=float(f[10]),
                          fraction_bits=int(f[12]))
            grids.append(cur)
            cell = None
        elif line.startswith("CH "):
            if cur is None:
                raise AiqbError("channel before any light source: %r" % line)
            r, c = line.split()[1:3]
            cell = (int(r), int(c))
            cur.cells[cell] = []
        elif line[:1].isdigit() and cell is not None:
            cur.cells[cell].append([int(v) for v in line.split()])

    if not grids:
        raise AiqbError("no light sources in the LSC dump")

    if width is None:
        first = next(iter(grids[0].cells.values()))
        height, width = len(first), len(first[0])

    for g in grids:
        if not g.cells:
            raise AiqbError("light source %d has no grid" % g.index)
        for c, rows in g.cells.items():
            if len(rows) != height or any(len(r) != width for r in rows):
                raise AiqbError("light source %d cell %s is not %dx%d"
                                % (g.index, c, width, height))

    return width, height, grids
