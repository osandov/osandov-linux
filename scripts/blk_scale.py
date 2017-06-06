#!/usr/bin/env python3

"""
Test block layer scalability
"""

import argparse
import datetime
import glob
import json
import multiprocessing
import os
import os.path
import re
import statistics
import subprocess
import sys


def run_fio(args, num_jobs):
    name = 'fio{}'.format(num_jobs)
    output = name + '.json'
    fio_cmd = [
        'fio',
        '--output={}'.format(output),
        '--output-format=json',
        '--name={}'.format(name),
        '--filename={}'.format(args.dev),
        '--direct=1',
        '--numjobs={}'.format(num_jobs),
        '--cpus_allowed_policy=split',
        '--runtime=10',
        '--time_based',
        '--ioengine={}'.format(args.ioengine),
        '--iodepth={}'.format(args.iodepth),
        '--rw={}'.format(args.rw),
        '--unified_rw_reporting=1',
    ]
    subprocess.check_call(fio_cmd, stdout=subprocess.DEVNULL)

    with open(output, 'r') as f:
        fio_output = json.load(f)
    return aggregate_iops(fio_output)


def aggregate_iops(fio_output):
    iops = [job['mixed']['iops'] for job in fio_output['jobs']]
    merges = sum(disk_util['read_merges'] + disk_util['write_merges'] for disk_util in fio_output['disk_util'])
    return {
            'num_jobs': len(fio_output['jobs']),
            'total_iops': sum(iops),
            'min_iops': min(iops),
            'max_iops': max(iops),
            'mean_iops': statistics.mean(iops),
            'iops_stdev': statistics.stdev(iops) if len(iops) > 1 else 0.0,
            'merges': merges,
    }


def print_header():
    print('JOBS\tTOTAL IOPS\tMIN IOPS\tMAX IOPS\tMEAN IOPS\tIOPS STDEV\tMERGES', file=sys.stderr)
    sys.stderr.flush()


def print_results(iops):
    print('{num_jobs}\t{total_iops}\t{min_iops}\t{max_iops}\t{mean_iops}\t{iops_stdev}\t{merges}'.format(**iops))
    sys.stdout.flush()


def main():
    def positive_int(value):
        n = int(value)
        if n <= 0:
            raise ValueError
        return n
    parser = argparse.ArgumentParser(
        description='test block layer scalability',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument(
        '--parse', metavar='PATH', type=str, default=argparse.SUPPRESS,
        help='parse saved result directory instead of running; all other options will be ignored')
    parser.add_argument(
        'dev', metavar='DEV', type=str, nargs='?', help='block device to run on')

    parser.add_argument(
        '-j', '--jobs', type=str, default=argparse.SUPPRESS,
        help='comma-separated list of numbers of jobs to run in parallel (default: 1,2,...,number of CPUs)')

    parser.add_argument(
        '--ioengine', type=str, default='libaio', help='I/O engine for fio')
    parser.add_argument(
        '--iodepth', type=positive_int, default=64, help='I/O depth for fio')
    parser.add_argument(
        '--rw', type=str, default='randread', help='I/O pattern for fio')

    args = parser.parse_args()

    if hasattr(args, 'jobs'):
        args.jobs = [int(x) for x in args.jobs.split(',')]
    else:
        args.jobs = list(range(1, multiprocessing.cpu_count() + 1))

    if hasattr(args, 'parse'):
        os.chdir(args.parse)
        print_header()
        paths = glob.glob('fio*.json')
        paths.sort(key=lambda path: int(re.search(r'\d+', path).group()))
        for path in paths:
            with open(path, 'r') as f:
                fio_output = json.load(f)
            iops = aggregate_iops(fio_output)
            print_results(iops)
        return

    if args.dev is None:
        parser.error('DEV is required unless --parse is given')

    now = datetime.datetime.now()
    dir = 'blk_scale_' + now.replace(microsecond=0).isoformat()
    os.mkdir(dir)
    print(os.path.abspath(dir), file=sys.stderr)
    os.chdir(dir)

    info = {
        'args': vars(args),
        'date': now.isoformat(),
        'kernel_version': os.uname().release,
    }
    with open('info.json', 'w') as f:
        json.dump(info, f, sort_keys=True, indent=4)

    print_header()
    for num_jobs in args.jobs:
        iops = run_fio(args, num_jobs)
        print_results(iops)


if __name__ == '__main__':
    main()
