#!/usr/bin/env python3

import argparse
import resource
import os
import sys
import time


def main():
    parser = argparse.ArgumentParser(
        description='time how long it takes to dump core')
    parser.add_argument(
        'gb', metavar='GB', type=int,
        help='how many gigabytes of memory to use')
    parser.add_argument(
        '--pipe', action='store_true',
        help='do the coredump through a pipe helper')
    args = parser.parse_args()

    print('Allocating {} GB'.format(args.gb))
    mem = bytearray(2**30 * args.gb)
    with open('/proc/self/stat', 'r') as f:
        rss = int(f.readline().split()[23])
        print('RSS: {:.2f} GB'.format(rss * os.sysconf('SC_PAGESIZE') / 2**30))

    if args.pipe:
        with open('/root/coredump_helper.sh', 'w') as f:
            f.write('#!/bin/sh\n')
            f.write('\n')
            f.write('cat >$1')
        os.chmod('/root/coredump_helper.sh', 0o755)

    with open('/proc/sys/kernel/core_pattern', 'r') as f:
        old_core_pattern = f.read()

    try:
        with open('/proc/sys/kernel/core_pattern', 'w') as f:
            if args.pipe:
                f.write('|/root/coredump_helper.sh /root/core.%e.%p\n')
            else:
                f.write('/root/core.%e.%p\n')

        limit = (resource.RLIM_INFINITY, resource.RLIM_INFINITY)
        resource.setrlimit(resource.RLIMIT_CORE, limit)
        pid = os.fork()
        if pid == 0:
            os.abort()
        else:
            print('Forked child {}'.format(pid))
            start = time.perf_counter()
            os.waitpid(pid, 0)
            end = time.perf_counter()
            print('Elapsed: {:.2f}s'.format(end - start))
    finally:
        with open('/proc/sys/kernel/core_pattern', 'w') as f:
            f.write(old_core_pattern)


if __name__ == '__main__':
    main()
