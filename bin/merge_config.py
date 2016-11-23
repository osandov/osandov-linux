#!/usr/bin/env python3

import argparse
from collections import OrderedDict
import shutil
import subprocess
import re
import sys


comment_re = re.compile(r'#.*$')
config_re = re.compile(r'^CONFIG_([^=]+)=(.*)$')


def parse_config(config, f):
    for i, line in enumerate(f, 1):
        line = comment_re.sub('', line).strip()
        if not line:
            continue
        match = config_re.fullmatch(line)
        if match:
            config[match.group(1)] = match.group(2)
        else:
            print("{}:{}:invalid Kconfig {!r}".format(f.name, i, line),
                  file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description='Merge multiple Kconfig fragments into a single Kconfig')
    parser.add_argument('--defconfig', metavar='KCONFIG', default=None,
        help='default Kconfig to use as the base for merging; if unspecified, `make defconfig` will be used instead')
    parser.add_argument(
        'fragments', metavar='FRAGMENT', nargs='+',
        help='Kconfig fragment file; later fragment files can override options in ealier ones')
    args = parser.parse_args()

    if args.defconfig is None:
        subprocess.check_call(['make', 'defconfig'])
    else:
        shutil.copyfile(args.defconfig, '.config')

    config = OrderedDict()
    with open('.config', 'r') as f:
        parse_config(config, f)

    fragments = OrderedDict()
    for fragment in args.fragments:
        with open(fragment, 'r') as f:
            parse_config(fragments, f)

    config.update(fragments)
    with open('.config', 'w') as f:
        for option, value in config.items():
            f.write('CONFIG_{}={}\n'.format(option, value))

    subprocess.check_call(['make', 'olddefconfig'])

    config = {}
    with open('.config', 'r') as f:
        parse_config(config, f)

    status = 0
    for option, expected_value in fragments.items():
        actual_value = config.get(option, 'n')
        if actual_value != expected_value:
            print('Expected CONFIG_{}={}, got {}'.format(option, expected_value, actual_value),
                  file=sys.stderr)
            status = 1
    return status


if __name__ == '__main__':
    exit(main())
