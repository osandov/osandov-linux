#!/usr/bin/env python3

import argparse
import mmap
import os


def main():
    parser = argparse.ArgumentParser(
        description='allocate as much memory as possible')
    args = parser.parse_args()

    mms = []
    page_size = os.sysconf('SC_PAGESIZE')
    size = os.sysconf('SC_PHYS_PAGES')
    while size > 0:
        try:
            mm = mmap.mmap(-1, size * page_size)
            print('Allocated {} pages'.format(size))
            # Dirty all of the pages so that they're actually allocated.
            for i in range(size):
                mm.seek(i * page_size)
                mm.write_byte(0xff)
            # Keep a reference to the mmap object so that Python doesn't munmap
            # the memory.
            mms.append(mm)
        except OSError:
            print('Failed to allocate {} pages'.format(size))
            size //= 2
    

if __name__ == '__main__':
    main()
