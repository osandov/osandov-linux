#!/usr/bin/env python3
# SPDX-FileCopyrightText: Omar Sandoval <osandov@osandov.com>
# SPDX-License-Identifier: MIT

import argparse

_crc32c_table = [0] * 256
for i in range(256):
    fwd = i
    for j in range(8, 0, -1):
        if fwd & 1:
            fwd = (fwd >> 1) ^ 0x82F63B78
        else:
            fwd >>= 1
        _crc32c_table[i] = fwd & 0xFFFFFFFF


def main():
    parser = argparse.ArgumentParser(
        description="calculate the Btrfs CRC32C of zero byte blocks of different sizes"
    )
    args = parser.parse_args()

    crc = 0xFFFFFFFF
    i = 1
    while True:
        crc = (crc >> 8) ^ _crc32c_table[crc & 0xFF]
        if i & (i - 1) == 0:
            print(f"{i} 0x{crc ^ 0xFFFFFFFF:08x}", flush=True)
        i += 1


if __name__ == "__main__":
    main()
