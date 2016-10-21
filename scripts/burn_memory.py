#!/usr/bin/env python3

import argparse
import mmap
import os

if not hasattr(mmap, 'MAP_POPULATE'):
    mmap.MAP_POPULATE = 0x8000


def main():
    parser = argparse.ArgumentParser(
        description='allocate as much memory as possible')
    args = parser.parse_args()

    mms = []
    page_size = os.sysconf('SC_PAGESIZE')
    size = os.sysconf('SC_PHYS_PAGES')
    while size > 0:
        try:
            mm = mmap.mmap(-1, size * page_size,
                           prot=mmap.PROT_READ | mmap.PROT_WRITE,
                           flags=mmap.MAP_ANONYMOUS | mmap.MAP_PRIVATE | mmap.MAP_POPULATE)
            print('Allocated {} pages'.format(size))
            # Keep a reference to the mmap object so that Python doesn't munmap
            # the memory.
            mms.append(mm)
        except OSError:
            print('Failed to allocate {} pages'.format(size))
            size //= 2


if __name__ == '__main__':
    main()
