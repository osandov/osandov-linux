#!/bin/sh
# SPDX-FileCopyrightText: Omar Sandoval <osandov@osandov.com>
# SPDX-License-Identifier: MIT

set -e

usage () {
	USAGE_STRING="usage: $0 [-h]

Print the debug info files for the running kernel

options:
  -h    show this help message and exit"

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
			usage out
			;;
		*)
			usage err
			;;
	esac
done
if [ $# -ne 0 ]; then
	usage err
fi

status=0

release="$(uname -r)"

found_vmlinux=
for path in "/usr/lib/debug/boot/vmlinux-$release" \
	    "/usr/lib/debug/lib/modules/$release/vmlinux" \
	    "/boot/vmlinux-$release" \
	    "/lib/modules/$release/build/vmlinux" \
	    "/lib/modules/$release/vmlinux"; do
	if [ -e "$path" ]; then
		echo "$path"
		found_vmlinux=1
		break
	fi
done
if [ -z "$found_vmlinux" ]; then
	echo "vmlinux not found" >&2
	status=1
fi

while read -r module _; do
	if ! module_path="$(modinfo -F filename "$module")"; then
		status=1
		continue
	fi

	case "$module_path" in
		*.ko.gz)
			module_path_no_ext="${module_path%%.gz}"
			;;
		*.ko.xz)
			module_path_no_ext="${module_path%%.xz}"
			;;
		*)
			module_path_no_ext="$module_path"
			;;
	esac
	found_module=
	for path in "/usr/lib/debug$module_path_no_ext" \
		    "/usr/lib/debug$module_path_no_ext.debug"; do
		if [ -e "$path" ]; then
			echo "$path"
			found_module=1
			break
		fi
	done
	if [ -z "$found_module" ]; then
		if eu-readelf -S "$module_path" | grep -q '\.z\?debug_info'; then
			echo "$module_path"
		else
			echo "debug info for $module not found" >&2
			status=1
		fi
	fi
done < /proc/modules

exit $status
