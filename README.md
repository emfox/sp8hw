# sp8hw — Surface Pro 8 camera calibration

Turns the AIQB calibration of the Surface Pro 8 cameras into libcamera
software ISP tuning files, for the ov13858 at the back and the ov5693 in
front, behind the Intel IPU6.

The blobs themselves are not in this repository. They are Microsoft's
calibration data shipped in the Windows driver package, and they stay
there: `fetch-aiqb.sh` pulls them out and checks the SHA-256, so the
numbers below can be reproduced without redistributing them.

## The pipeline

Four stages, each one only reading what the stage before it left behind:

```
  Windows driver package (sp8.msi)
        │
        │  1  fetch-aiqb.sh             download, 7z + msidump, SHA-256
        ▼
  OV13858_MSHW0261_TGL.aiqb             OV5693_MSHW0220_TGL.aiqb
        │                                       │
        │  2  ipu6.py                   cc against ipu6-camera-bins
        ▼                                       ▼
  build/cmc   build/lsc                 the two C dumpers, native/*.c
        │
        │  3  sp8hw.py dumps            one run per blob and dumper
        ▼
  cmc-rear.txt  lsc-rear.txt    cmc-front.txt  lsc-front.txt
        │
        │  4  colour.py + lsc.py, assembled by tuning.py
        ▼
  out/ov13858.yaml                      out/ov5693.yaml
```

| stage | command | reads | writes |
| --- | --- | --- | --- |
| fetch | `./sp8hw.py fetch` | `sp8.msi` | the two `.aiqb` |
| tools | `./sp8hw.py tools` | `native/*.c`, ipu6-camera-bins | `build/cmc`, `build/lsc` |
| dumps | `./sp8hw.py dumps` | the blobs | `cmc-*.txt`, `lsc-*.txt` |
| generate | `./sp8hw.py generate` | the dumps | `out/*.yaml` |

With no stage, all four run in that order, and fetch is skipped when the
blobs are already there:

```sh
git clone https://github.com/intel/ipu6-camera-bins ../ipu6-camera-bins
./sp8hw.py
```

`IPU6_BINS` points the tools stage at a checkout kept elsewhere, and
`--msi /path/to/sp8.msi` reuses a driver package already downloaded. Any
stage can be rerun on its own; `generate` re-dumps unless `--dumps DIR`
points it at dumps from an earlier run.

```
  extracted OV13858_MSHW0261_TGL.aiqb
  8be033ec…  OV13858_MSHW0261_TGL.aiqb: OK
  …
  ov13858  6 light sources, 10 shading grids -> 5 sets, 369 lines -> out/ov13858.yaml
  ov5693   7 light sources, 5 shading grids -> 5 sets, 376 lines -> out/ov5693.yaml
```

## What each file is

| file | role |
| --- | --- |
| `sp8hw.py` | the four stages, in order, with what each one reads and writes |
| `fetch-aiqb.sh` | vendor package in, two verified blobs out |
| `aiqb.py` | where the parser's AIQB chunk starts, and what the dumpers print |
| `ipu6.py` | find ipu6-camera-bins, build the dumpers, run them on a blob |
| `colour.py` | the Awb and Ccm sections: gains, priors, matrices |
| `lsc.py` | the Lsc section: shading grids resampled and averaged |
| `tuning.py` | the sensor table, and the order the sections go in |
| `native/dump-cmc.c` | CMC dumper: white points, gains, matrices |
| `native/dump-lsc.c` | LSC dumper: the 63x47 shading grids |

The two C files are thin adapters over `libia_cmc_parser`, the vendor's own
parser. The offset of the AIQB chunk inside the container is found once, in
`aiqb.py`, and passed in, so nothing hardcodes 0x38.

## The numbers

- **Colour gains, priors, matrices** (`colour.py`) are copied from the blob
  as they are, to five decimals. Each gain is the inverse of the white point
  of its light source and the matrix is the vendor's matrix for the same
  source, so the two sections cannot disagree.
- **Priors are flat.** A peaked prior pulls the estimator towards whatever
  temperature it is centred on: a 4000 K hump dragged a 5700 K LED down to
  3790 K and left a white sheet 6% blue. There are no illuminant statistics
  for these modules, so every calibrated source is equally likely.
- **CCT** is the stored one; older blobs carry none, and the CIE xy of the
  source is used instead, which agrees within ~1% (McCamy 1992).
- **Lens shading** (`lsc.py`): the 63x47 Q11 grids (2048 = 1.0) are
  resampled to the 17x17 UQ<2,6> table the ISP interpolates (64 = 1.0, one
  byte per cell), normalised on their own centre and clamped at 3.98x. The
  blob has more light sources than the AWB table has entry points, so grids
  sharing a colour temperature are averaged instead of all but one dropped.
- **Order of sections** is libcamera's: Awb, Lsc, Ccm. The ISP interpolates
  shading before it applies the matrix, so the table comes first.

The result is byte for byte the files used by the libcamera patch
*ipa: softisp: Add tuning data for the ov13858 and ov5693*; nothing is
edited by hand afterwards.

## Verifying a blob

The driver package is not version-pinned: Microsoft replaces it as firmware
is updated, and the checks below are what tells you whether the copy in
front of you is the one the tuning files came from.

```
8be033ec800bd58d7f1f9b8347f56ab1b7881711f41b9775c261a258b619c2a7  OV13858_MSHW0261_TGL.aiqb: OK
772dd6c773ad44b2880d4ace75ca3446ab4b88d99f718efaf22676292f1f1309  OV5693_MSHW0220_TGL.aiqb: OK
```

## Copyright

The `.aiqb` blobs are calibration data of Intel and Microsoft and are not
redistributed here; `fetch-aiqb.sh` only documents how to obtain them.
The scripts are CC0-1.0.
