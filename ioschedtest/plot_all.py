#!/usr/bin/env python3

from collections import OrderedDict
import json
import os.path
import subprocess
import tempfile

BENCHMARKS = [
    '10r-seq',
    '10w-seq',
    '5r5w-seq',
    '5r5w-rand',
]

IOSCHEDS = [
    ('Noop', 'noop'),
    ('Deadline', 'deadline'),
    ('CFQ', 'cfq'),
]

def plot_aggregate_throughput(benchmarks):
    with tempfile.NamedTemporaryFile('w') as f, \
         subprocess.Popen(['gnuplot'], stdin=subprocess.PIPE, universal_newlines=True) as proc:
        print('"I/O Scheduler"', *[x[0] for x in IOSCHEDS], sep='\t', file=f)
        for name in BENCHMARKS:
            print(name, *benchmarks[name]['throughput'], sep='\t', file=f)
        f.flush()

        print('set title "I/O Scheduler Aggregate Throughput"', file=proc.stdin)
        print('set auto x', file=proc.stdin)
        print('set ylabel "Aggregate Throughput (MB/s)"', file=proc.stdin)
        print('set yrange [0:]', file=proc.stdin)
        print('set style data histogram', file=proc.stdin)
        print('set style histogram cluster gap 1', file=proc.stdin)
        print('set style fill solid border -1', file=proc.stdin)
        print('set boxwidth 0.9', file=proc.stdin)

        print(f.name)
        print('plot', end='', file=proc.stdin)
        for i in range(2, len(IOSCHEDS) + 2):
            if i == 2:
                print(' "{}"'.format(f.name), end='', file=proc.stdin)
            else:
                print(', ""', end='', file=proc.stdin)
            print(' using {}:xtic(1) title col'.format(i), end='', file=proc.stdin)
        print(file=proc.stdin)
        print('pause mouse close', file=proc.stdin)
        proc.stdin.close()


def plot_aggregate_latency(benchmarks):
    with tempfile.NamedTemporaryFile('w') as f, \
         subprocess.Popen(['gnuplot'], stdin=subprocess.PIPE, universal_newlines=True) as proc:
        print('"I/O Scheduler"', *[x[0] for x in IOSCHEDS], sep='\t', file=f)
        for name in BENCHMARKS:
            print(name, *benchmarks[name]['avgclat'], sep='\t', file=f)
        f.flush()

        print('set title "I/O Scheduler Average Completion Latencies"', file=proc.stdin)
        print('set auto x', file=proc.stdin)
        print('set ylabel "Average Completion Latency (μs)"', file=proc.stdin)
        print('set yrange [0:]', file=proc.stdin)
        print('set style data histogram', file=proc.stdin)
        print('set style histogram cluster gap 1', file=proc.stdin)
        print('set style fill solid border -1', file=proc.stdin)
        print('set boxwidth 0.9', file=proc.stdin)

        print(f.name)
        print('plot', end='', file=proc.stdin)
        for i in range(2, len(IOSCHEDS) + 2):
            if i == 2:
                print(' "{}"'.format(f.name), end='', file=proc.stdin)
            else:
                print(', ""', end='', file=proc.stdin)
            print(' u {}:xtic(1) ti col'.format(i), end='', file=proc.stdin)
        print(file=proc.stdin)
        print('pause mouse close', file=proc.stdin)
        proc.stdin.close()


def main():
    benchmarks = {}
    for benchmark_name in BENCHMARKS:
        if not os.path.isdir(benchmark_name):
            continue
        benchmark = {'throughput': [], 'avgclat': []}
        for iosched_name, key in IOSCHEDS:
            throughput = []
            with open(os.path.join(benchmark_name, key + '.json'), 'r') as f:
                output = json.load(f, object_pairs_hook=OrderedDict)
            benchmark['throughput'].append(output['jobs'][0]['mixed']['bw'] / 1000)
            benchmark['avgclat'].append(output['jobs'][0]['mixed']['lat']['mean'])
        benchmarks[benchmark_name] = benchmark

    plot_aggregate_throughput(benchmarks)
    plot_aggregate_latency(benchmarks)


if __name__ == '__main__':
    main()
