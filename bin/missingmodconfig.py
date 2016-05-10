#!/usr/bin/env python3

import argparse
import os
import os.path
import re
import subprocess
import sys


def read_config():
    with open('.config', 'r') as f:
        return f.read()


def parse_config(contents):
    config_re = re.compile(r'CONFIG_([0-9A-Z_a-z]+)=(m|y)')
    config = {}
    for line in contents.splitlines():
        match = config_re.fullmatch(line)
        if match:
            config[match.group(1)] = match.group(2)
    return config


def read_lsmod(path):
    if path is not None:
        with open(path, 'r') as f:
            return f.read()
    else:
        return subprocess.check_output(['lsmod']).decode('utf-8')


def parse_lsmod(contents):
    modules = set()
    for i, line in enumerate(contents.splitlines()):
        # Skip the first line
        if i > 0:
            modules.add(line.split()[0].replace('-', '_'))
    return modules


def find_module_options(modules):
    def find_makefiles():
        for dirpath, dirnames, filenames in os.walk('.'):
            for filename in filenames:
                if filename == 'Makefile' or filename == 'Kbuild':
                    yield os.path.join(dirpath, filename)

    goal_re = re.compile(r'^obj-\$\(CONFIG_([0-9A-Z_a-z]+)\)\s*(?::=|\+=|=)\s*([^#\n]*)$',
                         re.MULTILINE)
    objs_re = re.compile(r'(\S+)\.o')

    options = {module: set() for module in modules}
    for path in find_makefiles():
        with open(path, 'r') as f:
            contents = f.read().replace('\\\n', '')
        for match in goal_re.finditer(contents):
            option, objs = match.group(1), match.group(2)
            for match in objs_re.finditer(objs):
                module = match.group(1).replace('-', '_')
                if module in modules:
                    options[module].add(option)
    return options


def main():
    parser = argparse.ArgumentParser(
        description='list config options needed for loaded modules')
    parser.add_argument(
        '--lsmod', metavar='FILE', type=str,
        help='read lsmod output from FILE instead of running lsmod')
    args = parser.parse_args()

    config = parse_config(read_config())
    modules = parse_lsmod(read_lsmod(args.lsmod))
    module_options = find_module_options(modules)

    for module, options in sorted(module_options.items()):
        if len(options) == 0:
            print('warning: no config options found for {}'.format(module), file=sys.stderr)
        for option in options:
            if option in config:
                break
        else:
            print('{} needs one of {}'.format(module, ', '.join(options)))


if __name__ == '__main__':
    main()
