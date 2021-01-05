#!/bin/sh
# SPDX-FileCopyrightText: Omar Sandoval <osandov@osandov.com>
# SPDX-License-Identifier: MIT

set -e

usage () {
	USAGE_STRING="Usage: $0 PATH
$0 -h

Age a Btrfs filesystem

Miscellaneous:
  -h    display this help message and exit"

	case "$1" in
		out)
			echo "$USAGE_STRING"
			exit 0
			;;
		err)
			echo "$USAGE_STRING" >&2
			exit 1
			;;
	esac
}

while getopts "h" OPT; do
	case "$OPT" in
		h)
			usage "out"
			;;
		*)
			usage "err"
			;;
	esac
done

if [ $# -ne 1 ]; then
	usage "err"
fi

cd "$1"

if [ ! -d linux.git ]; then
	btrfs subvol create linux.git
	(git clone git://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git linux.git)
	btrfs filesystem sync "$1"
fi
prev=linux.git
for version in $(cd linux.git; git tag --sort -refname); do
	if [ ! -d "linux-$version" ]; then
		btrfs subvolume snapshot "$prev" "linux-$version"
		(cd "linux-$version"; git reset --hard "$version")
		btrfs filesystem sync "$1"
	fi
	prev="linux-$version"
done
