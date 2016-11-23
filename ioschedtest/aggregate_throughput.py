#!/usr/bin/env python2

from __future__ import print_function
import os.path
import json


SUBTESTS = [
    '10r-seq',
    '10w-seq',
    '5r5w-seq',
    '5r5w-rand',
]


IOSCHEDS = [
    ('Noop', 'noop'),
    ('Deadline', 'deadline'),
    ('CFQ', 'cfq'),
    ('blk-mq', 'blk-mq'),
    ('BFQ', 'bfq'),
]


def main():
    print('\t'.join(['"I/O Scheduler"'] + [x[0] for x in IOSCHEDS]))

    for subtest in SUBTESTS:
        print(subtest, end='')
        for iosched_name, key in IOSCHEDS:
            try:
                with open(os.path.join(subtest, key + '.json'), 'r') as f:
                    output = json.load(f)
                print('\t%f' % (sum(job['mixed']['bw'] for job in output['jobs']) / 1000.0), end='')
            except IOError:
                print('\t-', end='')
        print()


if __name__ == '__main__':
    main()
