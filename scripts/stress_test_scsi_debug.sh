#!/bin/bash

set -eu

usage () {
	USAGE_STRING="Usage: $0 [-H HOSTS] [-t TARGETS]
$0 -h

Options:
  -H    number of SCSI hosts (default: 1)
  -t    number of SCSI targets per host (default: 1)

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

num_hosts=1
num_targets=1

while getopts "hH:t:" OPT; do
	case "$OPT" in
		H)
			num_hosts="$OPTARG"
			;;
		t)
			num_targets="$OPTARG"
			;;
		h)
			usage "out"
			;;
		*)
			usage "err"
			;;
	esac
done

modprobe -r scsi_debug
modprobe scsi_debug add_host="${num_hosts}" num_tgts="${num_targets}"

hosts=()
for scsi_host in /sys/class/scsi_host/*; do
	if grep '^scsi_debug' "${scsi_host}/proc_name" >/dev/null 2>&1; then
		host="$(basename "${scsi_host}")"
		hosts+=("${host#host}")
	fi
done

targets=()
for host in "${hosts[@]}"; do
	for scsi_disk in "/sys/class/scsi_disk/${host}:"*; do
		targets+=("$(basename "${scsi_disk}")")
	done
done

echo "Hosts: ${hosts[@]}"
echo "Targets: ${targets[@]}"

processes=()
for target in "${targets[@]}"; do
	(
	host="${target%%:*}"
	scan="${target#*:}"
	scan="${scan//:/ }"
	while true; do
		echo 1 > "/sys/class/scsi_disk/${target}/device/delete"
		echo "${scan}" > "/sys/class/scsi_host/host${host}/scan"
	done
	) &
	processes+=($!)
done
wait
