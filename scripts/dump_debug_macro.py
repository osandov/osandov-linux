#!/usr/bin/env python3
# SPDX-FileCopyrightText: Omar Sandoval <osandov@osandov.com>
# SPDX-License-Identifier: MIT

import argparse
from typing import Any, Optional

from elftools.elf.elffile import ELFFile
from elftools.elf.sections import Section


class FormatError(Exception):
    pass


class Reader:
    def __init__(self, data: bytes, little_endian: bool) -> None:
        self._data = data
        self._byteorder: Any = "little" if little_endian else "big"
        self.offset = 0

    def _seek(self, offset: Optional[int]) -> None:
        if offset is not None:
            if offset > len(self._data):
                raise FormatError("out of bounds")
            self.offset = offset

    def read_uint(self, size: int, offset: Optional[int] = None) -> int:
        self._seek(offset)
        if len(self._data) - self.offset < size:
            raise FormatError("truncated")
        value = int.from_bytes(
            self._data[self.offset : self.offset + size], self._byteorder
        )
        self.offset += size
        return value

    def read_ubyte(self, offset: Optional[int] = None) -> int:
        self._seek(offset)
        if self.offset >= len(self._data):
            raise FormatError("truncated")
        value = self._data[self.offset]
        self.offset += 1
        return value

    def read_uleb128(self, offset: Optional[int] = None) -> int:
        self._seek(offset)
        value = 0
        shift = 0
        while True:
            byte = self.read_ubyte()
            value |= (byte & 0x7F) << shift
            if (byte & 0x80) == 0:
                return value
            shift += 7

    def read_string(self, offset: Optional[int] = None) -> str:
        self._seek(offset)
        end = self._data.index(b"\0", self.offset)
        s = self._data[self.offset : end]
        self.offset = end + 1
        return s.decode()

    def eof(self) -> bool:
        return self.offset >= len(self._data)


def dump_debug_macinfo(elf: ELFFile, macinfo_scn: Section) -> None:
    print(f"Section {macinfo_scn.name} @ {hex(macinfo_scn['sh_offset'])}")

    macinfo_reader = Reader(macinfo_scn.data(), elf.little_endian)

    while not macinfo_reader.eof():
        print("  Macro Unit @", hex(macinfo_reader.offset))
        while True:
            print(f"      {macinfo_reader.offset:x}: ", end="")
            opcode = macinfo_reader.read_ubyte()
            if opcode == 0:
                print()
                break
            elif opcode == 1:
                print(
                    f"define line {macinfo_reader.read_uleb128()}, {macinfo_reader.read_string()}"
                )
            elif opcode == 2:
                print(
                    f"undef line {macinfo_reader.read_uleb128()}, {macinfo_reader.read_string()}"
                )
            elif opcode == 3:
                print(
                    f"start_file line {macinfo_reader.read_uleb128()}, file {macinfo_reader.read_uleb128()}"
                )
            elif opcode == 4:
                print("end_file")
            else:
                raise FormatError(f"unknown opcode {hex(opcode)}")


def dump_debug_macro(elf: ELFFile, macro_scn: Section) -> None:
    print(f"Section {macro_scn.name} @ {hex(macro_scn['sh_offset'])}")

    if macro_scn.name.endswith(".dwo"):
        str_scn = elf.get_section_by_name(".debug_str.dwo")
        str_offsets_scn = elf.get_section_by_name(".debug_str_offsets.dwo")
        if elf.get_section_by_name(".debug_cu_index") or elf.get_section_by_name(
            ".debug_tu_index"
        ):
            dwarf_type = "dwp"
        else:
            dwarf_type = "dwo"
    else:
        str_scn = elf.get_section_by_name(".debug_str")
        str_offsets_scn = elf.get_section_by_name(".debug_str_offsets")
        dwarf_type = "plain"
    macro_reader = Reader(macro_scn.data(), elf.little_endian)
    str_reader = Reader(str_scn.data(), elf.little_endian) if str_scn else None
    str_offsets_reader = (
        Reader(str_offsets_scn.data(), elf.little_endian) if str_offsets_scn else None
    )

    while not macro_reader.eof():
        print("  Macro Unit @", hex(macro_reader.offset))

        version = macro_reader.read_uint(2)
        print("    version =", version)
        if version != 4 and version != 5:
            raise FormatError(f"unknown version {version}")

        flags = macro_reader.read_ubyte()
        offset_size_flag = (flags & 0x1) != 0
        debug_line_offset_flag = (flags & 0x2) != 0
        opcode_operands_table_flag = (flags & 0x4) != 0
        flags_str = []
        if offset_size_flag:
            flags_str.append("offset_size_flag")
        if debug_line_offset_flag:
            flags_str.append("debug_line_offset_flag")
        if opcode_operands_table_flag:
            flags_str.append("opcode_operands_table_flag")
        if flags & ~0x7:
            flags_str.append(hex(flags & ~0x7))
        if not flags_str:
            flags_str.append("0")
        print("    flags =", "|".join(flags_str))

        offset_size = 8 if offset_size_flag else 4

        if debug_line_offset_flag:
            debug_line_offset = macro_reader.read_uint(offset_size)
            print("    debug_line_offset =", hex(debug_line_offset))

        if opcode_operands_table_flag:
            raise NotImplementedError("opcode_operands_table_flag")

        while True:
            print(f"    {macro_reader.offset:x}: ", end="")
            opcode = macro_reader.read_ubyte()
            if opcode == 0:
                print()
                break
            elif opcode == 1:
                print(
                    f"define line {macro_reader.read_uleb128()}, {macro_reader.read_string()}"
                )
            elif opcode == 2:
                print(
                    f"undef line {macro_reader.read_uleb128()}, {macro_reader.read_string()}"
                )
            elif opcode == 3:
                print(
                    f"start_file line {macro_reader.read_uleb128()}, file {macro_reader.read_uleb128()}"
                )
            elif opcode == 4:
                print("end_file")
            elif opcode == 5 or opcode == 6:
                lineno = macro_reader.read_uleb128()
                strp = macro_reader.read_uint(offset_size)
                print(
                    "define_strp" if opcode == 5 else "undef_strp",
                    f"line {lineno}, strp {strp} ",
                    end="",
                )
                try:
                    if str_reader:
                        string = str_reader.read_string(strp)
                    else:
                        raise FormatError("no .debug_str")
                    print("->", string)
                except FormatError as e:
                    print(f"<{e}>")
            elif opcode == 7:
                print("import", hex(macro_reader.read_uint(offset_size)))
            elif opcode == 8 or opcode == 9:
                lineno = macro_reader.read_uleb128()
                sup = macro_reader.read_uint(offset_size)
                print(
                    "define_sup" if opcode == 8 else "undef_sup",
                    f"line {lineno}, sup {sup}",
                )
            elif opcode == 10:
                print("import_sup", hex(macro_reader.read_uint(offset_size)))
            elif opcode == 11 or opcode == 12:
                lineno = macro_reader.read_uleb128()
                strx = macro_reader.read_uleb128()
                print(
                    "define_strx" if opcode == 11 else "undef_strx",
                    f"line {lineno}, strx {strx} ",
                    end="",
                )
                if dwarf_type == "dwo":
                    # It's harder to get the str_offsets_base for normal and
                    # dwp files.
                    str_offsets_base = (2 * offset_size) if version >= 5 else 0
                    try:
                        if str_offsets_reader:
                            strp = str_offsets_reader.read_uint(
                                offset_size, str_offsets_base + strx * offset_size
                            )
                        else:
                            raise FormatError("no .debug_str_offsets")
                        print("-> strp", hex(strp), end=" ")
                        if str_reader:
                            string = str_reader.read_string(strp)
                        else:
                            raise FormatError("no .debug_str")
                        print("->", string)
                    except FormatError as e:
                        print(f"<{e}>")
                else:
                    print()
            else:
                raise FormatError(f"unknown opcode {hex(opcode)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="dump macro debugging information for a file"
    )
    parser.add_argument("path")
    args = parser.parse_args()

    with open(args.path, "rb") as f:
        elf = ELFFile(f)

        for section in elf.iter_sections():
            try:
                if (
                    section.name == ".debug_macinfo"
                    or section.name == ".debug_macinfo.dwo"
                ):
                    dump_debug_macinfo(elf, section)
                elif (
                    section.name == ".debug_macro" or section.name == ".debug_macro.dwo"
                ):
                    dump_debug_macro(elf, section)
            except FormatError as e:
                print(f"<{e}>")


if __name__ == "__main__":
    main()
