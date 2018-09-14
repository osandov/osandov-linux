#!/bin/bash

: TIMEOUT="${TIMEOUT:=60}"

if [[ $# -eq 0 ]]; then
	echo "usage: $0 DEV [DEV ...]" >&2
	exit 1
fi

targets=()
for dev in "$@"; do
	echo "$dev"
	major=$((0x$(stat -c %t "$dev")))
	minor=$((0x$(stat -c %T "$dev")))
	target=$(ls "/sys/dev/block/${major}:${minor}/device/scsi_device")
	if [[ -z $target ]]; then
		echo "could not find SCSI target for $dev" >&2
		exit 1
	fi
	echo "$dev is $target"
	targets+=("$target")
done

tmpdir="$(mktemp -d)" || exit $?
for target in "${targets[@]}"; do
	(
	host="${target%%:*}"
	scan="${target#*:}"
	scan="${scan//:/ }"
	while [[ ! -e "$tmpdir/stop" ]]; do
		echo 1 > "/sys/class/scsi_device/${target}/device/delete"
		echo "${scan}" > "/sys/class/scsi_host/host${host}/scan"
	done
	) &
done
sleep "$TIMEOUT"
touch "$tmpdir/stop"
wait
rm -r "$tmpdir"
