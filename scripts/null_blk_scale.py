#!/usr/bin/env python3

"""
Test blk-mq scalability with the null-blk kernel module.
"""

import argparse
import datetime
import json
import multiprocessing
import os
import os.path
import statistics
import subprocess
import sys


def run_fio(args, num_jobs):
    subprocess.check_call(['modprobe', '-r', 'null_blk'])
    subprocess.check_call(['modprobe', 'null_blk', 'submit_queues={}'.format(args.hw_queues)])
    name = '{}{}'.format(args.ioengine, num_jobs)
    output = name + '.json'
    fio_cmd = [
        'fio',
        '--output={}'.format(output),
        '--output-format=json',
        '--name={}'.format(name),
        '--filename=/dev/nullb0',
        '--direct=1',
        '--numjobs={}'.format(num_jobs),
        '--cpus_allowed_policy=split',
        '--runtime=10',
        '--time_based',
        '--ioengine={}'.format(args.ioengine),
        '--iodepth={}'.format(args.iodepth),
        '--rw={}'.format(args.rw),
    ]
    subprocess.check_call(fio_cmd, stdout=subprocess.DEVNULL)

    with open(output, 'r') as f:
        fio_output = json.load(f)
    return aggregate_iops(fio_output)


def aggregate_iops(fio_output):
    read_iops = [job['read']['iops'] for job in fio_output['jobs']]
    read_merges = sum(disk_util['read_merges'] for disk_util in fio_output['disk_util'])
    return {
            'total_iops': sum(read_iops),
            'min_iops': min(read_iops),
            'max_iops': max(read_iops),
            'mean_iops': statistics.mean(read_iops),
            'iops_stdev': statistics.stdev(read_iops) if len(read_iops) > 1 else 0.0,
            'merges': read_merges,
    }


def main():
    def positive_int(value):
        n = int(value)
        if n <= 0:
            raise ValueError
        return n
    parser = argparse.ArgumentParser(
        description='test blk-mq scalability with null-blk',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument(
        '-m', '--min-jobs', type=int, default=1,
        help='minimum number of jobs to run in parallel')
    parser.add_argument(
        '-M', '--max-jobs', type=int, default=multiprocessing.cpu_count(),
        help='maximum number of jobs to run in parallel')
    parser.add_argument(
        '-q', '--hw-queues', type=positive_int, default=multiprocessing.cpu_count(),
        help='number of null-blk hardware queues to use')
    parser.add_argument(
        '-d', '--queue-depth', type=positive_int, default=64,
        help='depth of null-blk hardware queues')
    parser.add_argument(
        '--ioengine', type=str, default='libaio', help='fio I/O engine')
    parser.add_argument(
        '--iodepth', type=positive_int, default=64, help='fio I/O depth')
    parser.add_argument(
        '--rw', type=str, default='randread', help='fio I/O pattern')
    args = parser.parse_args()

    now = datetime.datetime.now()
    dir = 'null_blk_scale_' + now.replace(microsecond=0).isoformat()
    os.mkdir(dir)
    print(os.path.abspath(dir), file=sys.stderr)
    os.chdir(dir)

    info = {
        'argv': sys.argv,
        'date': now.isoformat(),
        'kernel_version': os.uname().release,
    }
    with open('info.json', 'w') as f:
        json.dump(info, f, sort_keys=True, indent=4)

    print('JOBS\tTOTAL IOPS\tMIN IOPS\tMAX IOPS\tMEAN IOPS\tIOPS\tSTDEV\tMERGES', file=sys.stderr)
    sys.stdout.flush()
    for num_jobs in range(args.min_jobs, args.max_jobs + 1):
        iops = run_fio(args, num_jobs)
        print('{0}\t{total_iops}\t{min_iops}\t{max_iops}\t{mean_iops}\t{iops_stdev}\t{merges}'.format(num_jobs, **iops))
        sys.stdout.flush()


if __name__ == '__main__':
    main()
