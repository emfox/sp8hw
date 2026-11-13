# sp8hw — Surface Pro 8 camera calibration

Turns the AIQB calibration of the Surface Pro 8 cameras into libcamera
software ISP tuning files, for the ov13858 at the back and the ov5693 in
front, behind the Intel IPU6.

The blobs themselves are not in this repository. They are Microsoft's
calibration data shipped in the Windows driver package, and they stay
there: `fetch-aiqb.sh` pulls them out and checks the SHA-256, so the
numbers below can be reproduced without redistributing them.

## Get the blobs

```sh
./fetch-aiqb.sh                        # downloads the driver package, ~1 GB
MSI=/path/to/sp8.msi ./fetch-aiqb.sh   # or use a copy you already have
```

Needs `7z` (7zip) and `msidump` (msitools). The file names inside the
cabs are hashes, so the script reads the MSI File table to map them back
and then verifies:

```
8be033ec800bd58d7f1f9b8347f56ab1b7881711f41b9775c261a258b619c2a7  OV13858_MSHW0261_TGL.aiqb: OK
772dd6c773ad44b2880d4ace75ca3446ab4b88d99f718efaf22676292f1f1309  OV5693_MSHW0220_TGL.aiqb: OK
```

The driver package is not version-pinned: Microsoft replaces it as
firmware is updated, and the checks above are what tells you whether the
copy in front of you is the one the tuning files came from.

## Build

```sh
IPU6_BINS=/path/to/ipu6-camera-bins ./build-dumps.sh
IAQ_DUMP2=./dump2 IAQ_LIBDIR=$IPU6_BINS/lib python3 build-tune.py out
```

`IPU6_BINS` is a checkout of `intel/ipu6-camera-bins`, which ships the
`ia_imaging` headers and `libia_cmc_parser`. `build-dumps.sh` compiles
`dump2.c` / `dump4.c` against it and writes `lsc-rear.txt` and
`lsc-front.txt`; `build-tune.py` then writes `out/ov13858.yaml` and
`out/ov5693.yaml`, byte for byte the files used by the libcamera patch
*ipa: softisp: Add tuning data for the ov13858 and ov5693*.

## What the scripts do

- `gen-tuning.py` — colour gains, priors and colour matrices. The values
  are copied from the blob as they are, to five decimals.
- `gen-lsc.py` — the 63x47 Q11 grids (2048 = 1.0) resampled to the 17x17
  UQ<2,6> table the ISP interpolates (64 = 1.0, one byte per cell). Grids
  that share a colour temperature are averaged.
- `build-tune.py` — both of the above, assembled into one tuning file.

`dump4.c` walks the CMC structures with the Intel parser and prints the
lens shading grids; `dump2.c` does the same for the white points and
colour matrices.

## Copyright

The `.aiqb` blobs are calibration data of Intel and Microsoft and are not
redistributed here; `fetch-aiqb.sh` only documents how to obtain them.
The scripts are CC0-1.0.
