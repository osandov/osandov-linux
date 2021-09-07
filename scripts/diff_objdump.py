#!/usr/bin/env python3
# SPDX-FileCopyrightText: Omar Sandoval <osandov@osandov.com>
# SPDX-License-Identifier: MIT

import argparse
import difflib
import re
import subprocess
import sys

symbol_re = re.compile(r"^<([^>]+)>:")


def read_to_next_symbol(f):
    lines = []
    while True:
        line = f.readline()
        if not line:
            return lines, None
        match = symbol_re.match(line)
        if match:
            return lines, match.group(1)
        else:
            lines.append(line)


def main():
    parser = argparse.ArgumentParser(
        description="Compare the disassembly of two object files"
    )
    parser.add_argument(
        "--diff", action="store_true", help="include unified diff of changed symbols"
    )
    parser.add_argument("file1")
    parser.add_argument("file2")
    args = parser.parse_args()

    printed_changed_symbol = False

    def print_symbol_diff(symbol, lines1, lines2):
        nonlocal printed_changed_symbol
        if lines1 != lines2:
            if printed_changed_symbol:
                if args.diff:
                    print()
            else:
                print("Changed symbols:")
                printed_changed_symbol = True
            print(symbol)
            if args.diff:
                sys.stdout.writelines(
                    difflib.unified_diff(lines1, lines2, args.file1, args.file2)
                )

    objdump_command = [
        "objdump",
        "--disassemble",
        "--no-addresses",
        "--no-show-raw-insn",
    ]

    with subprocess.Popen(
        objdump_command + [args.file1], stdout=subprocess.PIPE, text=True
    ) as proc1, subprocess.Popen(
        objdump_command + [args.file2], stdout=subprocess.PIPE, text=True
    ) as proc2:
        symbol_list1 = []
        symbol_list2 = []
        unmatched1 = {}
        unmatched2 = {}
        symbol1 = read_to_next_symbol(proc1.stdout)[1]
        symbol2 = read_to_next_symbol(proc2.stdout)[1]
        while symbol1 is not None or symbol2 is not None:
            if symbol1 is not None:
                symbol_list1.append(symbol1 + "\n")
                lines1, next_symbol1 = read_to_next_symbol(proc1.stdout)
            if symbol2 is not None:
                symbol_list2.append(symbol2 + "\n")
                lines2, next_symbol2 = read_to_next_symbol(proc2.stdout)

            if symbol1 == symbol2:
                print_symbol_diff(symbol1, lines1, lines2)
            else:
                if symbol1 in unmatched2:
                    print_symbol_diff(symbol1, lines1, unmatched2.pop(symbol1))
                elif symbol1 is not None:
                    unmatched1[symbol1] = lines1
                if symbol2 in unmatched1:
                    print_symbol_diff(symbol2, unmatched1.pop(symbol2), lines2)
                elif symbol2 is not None:
                    unmatched1[symbol2] = lines2

            symbol1 = next_symbol1
            symbol2 = next_symbol2
        if proc1.wait() != 0:
            raise subprocess.CalledProcessError(proc1.returncode, proc1.args)
        if proc2.wait() != 0:
            raise subprocess.CalledProcessError(proc2.returncode, proc2.args)

    if symbol_list1 != symbol_list2:
        if printed_changed_symbol:
            print()
        print("Changed symbol list:")
        sys.stdout.writelines(
            difflib.unified_diff(symbol_list1, symbol_list2, args.file1, args.file2)
        )


if __name__ == "__main__":
    main()
