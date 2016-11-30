#!/usr/bin/env python3

import argparse
import json
import os
import os.path


def main():
    parser = argparse.ArgumentParser(
        description='Create a Kconfig from a metaconfig file')
    parser.add_argument(
        'metaconfig', metavar='METACONFIG', help='metaconfig file')
    args = parser.parse_args()

    with open(args.metaconfig, 'r') as f:
        metaconfig = json.load(f)

    cmd = ['merge_config.py']
    try:
        defconfig = os.path.join(os.path.dirname(args.metaconfig), metaconfig['defconfig'])
        cmd.append('--defconfig')
        cmd.append(defconfig)
    except KeyError:
        pass

    cmd.append('--')
    for fragment in metaconfig.get('fragments', []):
        cmd.append(os.path.join(os.path.dirname(args.metaconfig), fragment))
    os.execvp(cmd[0], cmd)


if __name__ == '__main__':
    main()
