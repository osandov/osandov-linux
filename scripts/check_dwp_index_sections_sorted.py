#!/usr/bin/env python3
# SPDX-FileCopyrightText: Omar Sandoval <osandov@osandov.com>
# SPDX-License-Identifier: MIT

import argparse
from array import array
import sys

from elftools.elf.elffile import ELFFile


def main() -> None:
    parser = argparse.ArgumentParser(
        description="check whether the section tables in a DWARF package file are sorted by offset"
    )
    parser.add_argument("path")
    args = parser.parse_args()

    with open(args.path, "rb") as f:
        elf = ELFFile(f)
        byteorder = "little" if elf.little_endian else "big"

        for section_name in (".debug_cu_index", ".debug_tu_index"):
            scn = elf.get_section_by_name(section_name)
            if scn is None:
                continue

            data = scn.data()
            view = memoryview(data)

            if len(data) < 16:
                sys.exit("error: header is truncated")

            if int.from_bytes(data[:4], byteorder) == 2:
                version = 2
            else:
                version = int.from_bytes(data[:2], byteorder)
                if version != 5:
                    sys.exit(f"error: unrecognized version {version}")
            section_count = int.from_bytes(data[4:8], byteorder)
            unit_count = int.from_bytes(data[8:12], byteorder)
            slot_count = int.from_bytes(data[12:16], byteorder)

            hash_table_start = 16
            hash_table_end = index_table_start = hash_table_start + slot_count * 8
            index_table_end = section_table_header_start = (
                index_table_start + slot_count * 4
            )
            section_table_header_end = section_offset_table_start = (
                section_table_header_start + section_count * 4
            )
            section_offset_table_end = section_size_table_start = (
                section_offset_table_start + unit_count * section_count * 4
            )
            section_size_table_end = (
                section_size_table_start + unit_count * section_count * 4
            )

            if len(data) < section_size_table_end:
                sys.exit("error: section is truncated")

            section_offset_table = array("I")
            section_offset_table.frombytes(
                view[section_offset_table_start:section_offset_table_end]
            )
            section_size_table = array("I")
            section_size_table.frombytes(
                view[section_size_table_start:section_size_table_end]
            )
            if byteorder != sys.byteorder:
                section_offset_table.byteswap()
                section_size_table.byteswap()

            last_offset = array("I", [0] * section_count)
            for i in range(unit_count):
                for j in range(section_count):
                    if section_size_table[i * section_count + j] == 0:
                        continue
                    offset = section_offset_table[i * section_count + j]
                    if offset < last_offset[j]:
                        sys.exit(f"{section_name} unit {i + 1} section {j} not sorted ({hex(offset)} < {hex(last_offset[j])})")
                    last_offset[j] = offset

    print("Sorted")


if __name__ == "__main__":
    main()

