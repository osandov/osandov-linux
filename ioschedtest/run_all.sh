#!/bin/bash

set -e

dir="$(dirname "${BASH_SOURCE[0]}")"

_run_aggregate () {
	local iosched="${1}"
	sync

	for subtest in 10r-seq 10w-seq 5r5w-seq 5r5w-rand; do
		printf "\\t\\t${subtest}\\n"
		mkdir -p "results/aggregate/${subtest}"
		sync
		fio --output-format=json --output="results/aggregate/${subtest}/${iosched}.json" \
			--runtime=30s --time_based "${dir}/${subtest}.fio"
		echo
	done
	(cd results/aggregate && "${dir}/aggregate_throughput.py" > throughput.dat)
}

_run_writeburst () {
	local iosched="${1}"
	mkdir -p results/writeburst
	sync

	fio --output-format=json --output="results/writeburst/${iosched}.json" "${dir}/writeburst.fio"
	echo
	mv writeburst_reader_bw.log "results/writeburst/${iosched}_bw.log"
	mv writeburst_reader_lat.log "results/writeburst/${iosched}_lat.log"
	mv writeburst_reader_clat.log "results/writeburst/${iosched}_clat.log"
	mv writeburst_reader_slat.log "results/writeburst/${iosched}_slat.log"
}

_run_interactive () {
	local iosched="${1}"
	mkdir -p results/interactive
	sync

	fio --output-format=json --output="results/interactive/${iosched}.json" "${dir}/interactive.fio"
	echo
	mv interactive_reader_lat.log "results/interactive/${iosched}_lat.log"
	mv interactive_reader_clat.log "results/interactive/${iosched}_clat.log"
	mv interactive_reader_slat.log "results/interactive/${iosched}_slat.log"
}

# _run_startup () {
	# local iosched="${1}"
	# mkdir -p results/startup

	# fio --output=/dev/null --create_only=1 "${dir}/10w-seq.fio"

	# rm -f "results/startup/${iosched}.dat"
	# ( while true; do
		# sleep 1
		# echo 3 > /proc/sys/vm/drop_caches
		# TIMEFORMAT='%R'; { time zsh -c exit >/dev/null 2>&1 ; } 2>> "results/startup/${iosched}.dat"
	# done ) &

	# fio --output=/dev/null --runtime=120s --time_based "${dir}/10w-seq.fio"
	# echo
	# kill $!
	# wait
# }

_run_startup () {
	local iosched="${1}"
	mkdir -p results/startup

	fio --output-format=json --output="results/startup/${iosched}.json" "${dir}/startup.fio"
	echo
}

run_tests () {
	local iosched="${1}"
	printf "${iosched}\\n"
	for test in "${tests[@]}"; do
		printf "\\t${test}\\n"
		"_run_${test}" "${iosched}"
	done
}

all_tests=($(compgen -A function | sed -n 's/^_run_//p' | sort))

usage () {
	USAGE_STRING="usage: $0 [-t TEST1,TEST2]

Available tests: ${all_tests[@]}"

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

tests=("${all_tests[@]}")
while getopts "t:h" OPT; do
	case "$OPT" in
		t)
			IFS=',' read -ra tests <<< "$OPTARG"
			for test in "${tests[@]}"; do
				if ! declare -f "_run_${test}" >/dev/null; then
					usage "err"
				fi
			done
			;;
		h)
			usage "out"
			;;
		*)
			usage "err"
			;;
	esac
done

dev="sda"

if [[ -d "/sys/block/${dev}/mq" ]]; then
	run_tests "blk-mq"
else
	for iosched in noop deadline cfq; do
		echo "${iosched}" > "/sys/block/${dev}/queue/scheduler"
		run_tests "${iosched}"
	done
fi
