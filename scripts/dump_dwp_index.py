#!/usr/bin/env python3
# SPDX-FileCopyrightText: Omar Sandoval <osandov@osandov.com>
# SPDX-License-Identifier: MIT

import argparse
from array import array
import sys

from elftools.elf.elffile import ELFFile

DW_SECT = {
    2: {
        1: "INFO",
        2: "TYPES",
        3: "ABBREV",
        4: "LINE",
        5: "LOC",
        6: "STR_OFFSETS",
        7: "MACINFO",
        8: "MACRO",
    },
    5: {
        1: "INFO",
        3: "ABBREV",
        4: "LINE",
        5: "LOCLISTS",
        6: "STR_OFFSETS",
        7: "MACRO",
        8: "RNGLISTS",
    },
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="dump DWARF package file index sections"
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

            print("Section", section_name)

            if len(data) < 16:
                sys.stdout.flush()
                print("error: header is truncated", file=sys.stderr)
                continue

            if int.from_bytes(data[:4], byteorder) == 2:
                version = 2
                print("  version =", version)
            else:
                version = int.from_bytes(data[:2], byteorder)
                print(" version =", version)
                if version != 5:
                    continue
            section_count = int.from_bytes(data[4:8], byteorder)
            unit_count = int.from_bytes(data[8:12], byteorder)
            slot_count = int.from_bytes(data[12:16], byteorder)
            print("  section_count =", section_count)
            print("  unit_count =", unit_count)
            print("  slot_count =", slot_count)

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
                sys.stdout.flush()
                print("error: section is truncated", file=sys.stderr)
                continue

            hash_table = array("Q")
            hash_table.frombytes(view[hash_table_start:hash_table_end])
            index_table = array("I")
            index_table.frombytes(view[index_table_start:index_table_end])
            section_table_header = array("I")
            section_table_header.frombytes(
                view[section_table_header_start:section_table_header_end]
            )
            section_offset_table = array("I")
            section_offset_table.frombytes(
                view[section_offset_table_start:section_offset_table_end]
            )
            section_size_table = array("I")
            section_size_table.frombytes(
                view[section_size_table_start:section_size_table_end]
            )
            if byteorder != sys.byteorder:
                hash_table.byteswap()
                index_table.byteswap()
                section_table_header.byteswap()
                section_offset_table.byteswap()
                section_size_table.byteswap()

            print("  Hash Table")
            print("        Slot Signature          Unit")
            for i in range(slot_count):
                print(f"  {i:10} ", end="")
                signature = hash_table[i]
                row = index_table[i]
                if signature == 0 and row == 0:
                    print()
                else:
                    print(f"0x{signature:016x} {row}")

            print("  Section Table")
            print("        Unit ", end="")
            for section in section_table_header:
                try:
                    name = DW_SECT[version][section]
                except KeyError:
                    name = str(section)
                print(f"{name:22}", end="")
            print()

            for i in range(unit_count):
                print(f"  {i + 1:10} ", end="")
                for j in range(section_count):
                    offset = section_offset_table[i * section_count + j]
                    size = section_size_table[i * section_count + j]
                    print(f"0x{offset:08x}+0x{size:08x} ", end="")
                print()


if __name__ == "__main__":
    main()
