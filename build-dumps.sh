#!/bin/sh
# Build the two dumpers against the Intel IPU6 binaries and regenerate the
# lens shading dumps that build-tune.py reads.
#
# IPU6_BINS must point at a checkout of intel/ipu6-camera-bins, which ships
# the ia_imaging headers and libia_cmc_parser. Neither the firmware nor the
# library is modified.
set -eu

BINS=${IPU6_BINS:-../ipu6-camera-bins}
INC=$BINS/include/ipu6/ia_imaging
LIB=$BINS/lib
CC=${CC:-cc}

[ -f "$LIB/libia_cmc_parser-ipu6.so.0" ] ||
	{ echo "no libia_cmc_parser under $LIB" >&2; exit 1; }

$CC -O2 -Wall -o dump2 dump2.c -I"$INC" \
	"$LIB/libia_cmc_parser-ipu6.so.0" "$LIB/libia_log-ipu6.so.0"
$CC -O2 -Wall -o dump4 dump4.c -I"$INC" \
	"$LIB/libia_cmc_parser-ipu6.so.0" "$LIB/libia_log-ipu6.so.0"

# The AIQB chunk does not always sit at the same offset, so let the file say
# where it is rather than hardcoding 0x38.
offset() {
	python3 -c 'import sys
d = open(sys.argv[1], "rb").read()
i = d.find(b"AIQB")
print(hex(i) if i >= 0 else "0x38")' "$1"
}

dump_lsc() {
	LD_LIBRARY_PATH=$LIB ./dump4 "$1" "$(offset "$1")" > "$2"
	echo "$2: $(head -n 1 "$2")"
}

dump_lsc OV13858_MSHW0261_TGL.aiqb lsc-rear.txt
dump_lsc OV5693_MSHW0220_TGL.aiqb lsc-front.txt
