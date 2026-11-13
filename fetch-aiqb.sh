#!/bin/sh
# Stages 1 and 2: the vendor driver package -> the two AIQB blobs.
#
# The blobs are Microsoft's calibration data and are not redistributed with
# this repository, so they are taken out of the Windows driver package:
# download the .msi, pull the cabs out of it, map the hashed member names back
# to real ones through the MSI File table, and check the SHA-256 of the result.
#
#   ./fetch-aiqb.sh                      # download the current package (~1 GB)
#   MSI=/path/to/sp8.msi ./fetch-aiqb.sh # or use a copy you already have
#
# Needs 7z (7zip) and msidump (msitools).
set -eu

EXPECT_13858=8be033ec800bd58d7f1f9b8347f56ab1b7881711f41b9775c261a258b619c2a7
EXPECT_5693=772dd6c773ad44b2880d4ace75ca3446ab4b88d99f718efaf22676292f1f1309

MSI=${MSI:-sp8.msi}
INDEX=https://www.microsoft.com/en-us/download/details.aspx?id=103503

# Scratch, all of it removed again on the way out: x/ holds the cabs, msi/
# the tables msidump writes, stage/ a member between extraction and rename.
# out/ is not touched, it is where the tuning files go.
trap 'rm -rf x msi stage' EXIT

say() { printf '  %s\n' "$*"; }
die() { printf '%s\n' "$*" >&2; exit 1; }

need() {
	command -v "$1" >/dev/null || die "needs $1 ($2)"
}

# -- 1. the package ----------------------------------------------------

download() {
	say "looking up the current driver package"
	url=$(curl -sL "$INDEX" |
	      grep -oE 'https://download\.microsoft\.com[^"]*\.msi' |
	      sort -u | tail -n 1) || true
	[ -n "$url" ] || die "no .msi link on the index page; pass MSI=<file>"
	say "downloading $url"
	curl -L --fail --progress-bar -o "$MSI" "$url"
}

unpack() {
	mkdir -p x msi stage
	7z x -y "$MSI" "*.cab" -ox >/dev/null
	msidump -t -d msi "$MSI" >/dev/null
}

# -- 2. the blobs ------------------------------------------------------

# Member names inside the cabs are hashes; the real ones are in the third
# column of the MSI File table, after the pipe.
hash_of() {
	awk -F'\t' -v n="$1" \
	    'NF > 2 && $3 ~ ("\\|" n "$") { print $1; exit }' msi/File.idt
}

extract() {
	real=$1
	hash=$(hash_of "$real")
	[ -n "$hash" ] || die "not in the package: $real"

	for cab in x/*.cab; do
		7z x -y "$cab" "$hash" -ostage >/dev/null 2>&1 || true
		[ -f "stage/$hash" ] && break
	done
	[ -f "stage/$hash" ] || die "not in any cab: $real"

	mv "stage/$hash" "$real"
	say "extracted $real"
}

# The driver package is not version-pinned: Microsoft replaces it as firmware
# is updated, and this is what tells you whether the copy in front of you is
# the one the tuning files came from.
verify() {
	printf '%s  %s\n' "$2" "$1" | sha256sum -c -
}

# -- run ---------------------------------------------------------------

need 7z "package 7zip or p7zip-full"
need msidump "package msitools"

if [ ! -f "$MSI" ]; then
	download
else
	say "using $MSI"
fi

unpack
extract OV13858_MSHW0261_TGL.aiqb
extract OV5693_MSHW0220_TGL.aiqb
verify OV13858_MSHW0261_TGL.aiqb "$EXPECT_13858"
verify OV5693_MSHW0220_TGL.aiqb "$EXPECT_5693"
