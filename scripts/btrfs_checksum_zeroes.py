#!/usr/bin/env python3

import argparse
import ctypes
import math


libbtrfs = ctypes.CDLL('libbtrfs.so.0')
libbtrfs.crc32c_optimization_init.restype = None
libbtrfs.crc32c_optimization_init.argtypes = []
libbtrfs.crc32c_le.restype = ctypes.c_uint32
libbtrfs.crc32c_le.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_char), ctypes.c_size_t]

libbtrfs.crc32c_optimization_init()


def main():
    parser = argparse.ArgumentParser(
        description='calculate the CRC32C of zero byte blocks of different sizes')
    args = parser.parse_args()

    b = bytes(2**26)
    for i in range(9, int(math.log2(len(b)))):
        crc = libbtrfs.crc32c_le(0xffffffff, b, 2**i) ^ 0xffffffff
        print(f'{2**i} 0x{crc:08x}')


if __name__ == '__main__':
    main()
