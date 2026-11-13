"""The colour half of a tuning file: the Awb and Ccm sections.

Everything here comes straight out of the blob. The gains are the inverse
of the white point of each light source, the matrices are the vendor's own
per-source matrices, and nothing is fitted or hand-tuned, so the two
sections always describe the same measurement.

The file is emitted as ordered blocks rather than as one string: the LSC
table belongs between Awb and Ccm, and the assembler in tuning.py has to be
able to put it there without searching for a line to splice at.
"""

LICENCE = "# SPDX-License-Identifier: CC0-1.0"

# libcamera keys the AWB entry points on the CCT the estimator reports, so
# the window has to cover every calibrated source with a little room for
# interpolation at either end.
AWB_LO_MARGIN = 200
AWB_HI_MARGIN = 900


def priors(rows):
    """Flat prior: no assumption about which illuminant is likely.

    A peaked prior pulls the estimator towards whatever temperature it is
    centred on: a 4000 K hump dragged a 5700 K LED down to 3790 K and left
    a white sheet 6% blue. With no illuminant statistics for this module,
    every calibrated source is equally likely.
    """
    return [1.0 / len(rows)] * len(rows)


def _prologue():
    # No blackLevel: the sensor helper knows the black level of the module,
    # and a value here would only have to agree with it.
    return ["%YAML 1.1", "---", "version: 1", "algorithms:",
            "  - BlackLevel:"]


def _awb(rows, name):
    cts = [r.ct for r in rows]
    out = [
        "  - Awb:",
        "      algorithm: bayes",
        "      # Colour gains and matrices are the calibrated values of the",
        "      # vendor aiqb of the %s; each gain is the inverse of the" % name,
        "      # white point of its light source, so both agree.",
        "      colourGains:",
    ]
    for r in rows:
        out.append("        - ct: %d" % r.ct)
        out.append("          gains: [ %.5f, %.5f ]" % (r.r_gain, r.b_gain))

    out += [
        "      # Flat priors: there are no illuminant statistics for these",
        "      # modules, so every calibrated source is equally likely.",
        "      priors:",
    ]
    probability = ", ".join("%.6f" % p for p in priors(rows))
    ct_list = ", ".join(str(ct) for ct in cts)
    for lux in (0, 100):
        out.append("        - lux: %d" % lux)
        out.append("          ct: [ %s ]" % ct_list)
        out.append("          probability: [ %s ]" % probability)

    out += [
        "      AwbMode:",
        "        Auto:",
        "          lo: %d" % (min(cts) - AWB_LO_MARGIN),
        "          hi: %d" % (max(cts) + AWB_HI_MARGIN),
    ]
    return out


def _ccm(rows):
    out = ["  - Ccm:", "      ccms:"]
    for r in rows:
        out.append("        - ct: %d" % r.ct)
        out.append("          ccm: [ " + ", ".join("%.5f" % v for v in r.ccm[:3])
                   + ",")
        out.append("                 " + ", ".join("%.5f" % v for v in r.ccm[3:6])
                   + ",")
        out.append("                 " + ", ".join("%.5f" % v for v in r.ccm[6:9])
                   + " ]")
        out.append("          offsets: [ 0, 0, 0 ]")
    return out


def blocks(rows, name):
    """The sections in file order, as (key, lines) pairs.

    The keys are what the assembler joins on: the LSC table goes between
    'awb' and 'ccm', because the ISP interpolates shading before it applies
    the matrix.
    """
    return [("prologue", _prologue()),
            ("awb", _awb(rows, name)),
            ("ccm", _ccm(rows)),
            ("epilogue", ["  - Adjust:", "  - Agc:", "..."])]
