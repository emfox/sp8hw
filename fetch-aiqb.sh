#!/bin/sh
# Pull the two AIQB blobs of the Surface Pro 8 out of the Windows driver
# package and check that they are the ones the tuning files were built from.
#
# The blobs are Microsoft's calibration data and are not redistributed with
# this repository; this script takes them from the vendor package instead.
# Pass MSI=<file> to use a package you already have.
set -eu

EXPECT_13858=8be033ec800bd58d7f1f9b8347f56ab1b7881711f41b9775c261a258b619c2a7
EXPECT_5693=772dd6c773ad44b2880d4ace75ca3446ab4b88d99f718efaf22676292f1f1309

MSI=${MSI:-sp8.msi}
INDEX=https://www.microsoft.com/en-us/download/details.aspx?id=103503

command -v 7z >/dev/null ||
	{ echo "needs 7z (package 7zip or p7zip-full)" >&2; exit 1; }
command -v msidump >/dev/null ||
	{ echo "needs msidump (package msitools)" >&2; exit 1; }

if [ ! -f "$MSI" ]; then
	echo "looking up the current driver package"
	url=$(curl -sL "$INDEX" |
	      grep -oE 'https://download\.microsoft\.com[^"]*\.msi' |
	      sort -u | tail -n 1)
	[ -n "$url" ] || { echo "no .msi link on the index page" >&2; exit 1; }
	echo "downloading $url"
	curl -L --fail --progress-bar -o "$MSI" "$url"
fi

mkdir -p x msi out
7z x -y "$MSI" "*.cab" -ox >/dev/null
msidump -t -d msi "$MSI" >/dev/null

# The file names inside the cabs are hashes; the real ones are in the MSI
# File table, third column, after the pipe.
extract() {
	real=$1
	hash=$(awk -F'\t' -v n="$real" \
	       'NF > 2 && $3 ~ ("\\|" n "$") { print $1; exit }' msi/File.idt)
	[ -n "$hash" ] || { echo "not in the package: $real" >&2; exit 1; }
	for cab in x/*.cab; do
		7z x -y "$cab" "$hash" -oout >/dev/null 2>&1 || true
		[ -f "out/$hash" ] && break
	done
	[ -f "out/$hash" ] || { echo "not in any cab: $real" >&2; exit 1; }
	mv "out/$hash" "$real"
	echo "extracted $real"
}

extract OV13858_MSHW0261_TGL.aiqb
extract OV5693_MSHW0220_TGL.aiqb

echo "$EXPECT_13858  OV13858_MSHW0261_TGL.aiqb" | sha256sum -c -
echo "$EXPECT_5693  OV5693_MSHW0220_TGL.aiqb" | sha256sum -c -
