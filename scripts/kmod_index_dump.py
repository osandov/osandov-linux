#!/usr/bin/env python3

import argparse
import struct
import sys


def dump_node(f, offset, depth, prefix):
    if offset & 0x0fffffff == 0:
        return
    f.seek(offset & 0x0fffffff)

    if offset & 0x80000000:
        while True:
            c = f.read(1)[0]
            if not c:
                break
            prefix += chr(c)

    if offset & 0x20000000:
        first = f.read(1)[0]
        last = f.read(1)[0]
        for i in range(last - first + 1):
            buf = f.read(4)
            pos = f.tell()
            dump_node(f, struct.unpack('>I', buf)[0], depth + 1,
                      prefix + chr(first + i))
            f.seek(pos)

    print('  ' * depth + prefix, end='')
    if offset & 0x40000000:
        print(' ->')
        value_count = struct.unpack('>I', f.read(4))[0]
        for i in range(value_count):
            priority = struct.unpack('>I', f.read(4))[0]
            value = ''
            while True:
                c = f.read(1)[0]
                if not c:
                    break
                value += chr(c)
            print('  ' * (depth + 1), priority, value)
    else:
        print()


def dump_index(f):
    magic = struct.unpack('>I', f.read(4))[0]
    assert magic == 0xb007f457

    version = struct.unpack('>I', f.read(4))[0]
    assert version == (2 << 16) | 1

    dump_node(f, struct.unpack('>I', f.read(4))[0], 0, '')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='dump the contents of a kmod index file (e.g., /lib/modules/$(uname -r)/modules.dep.bin)')
    parser.add_argument('path', type=str, help='file path')
    args = parser.parse_args()

    with open(args.path, 'rb') as f:
        dump_index(f)
