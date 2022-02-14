#!/usr/bin/env python3
# SPDX-FileCopyrightText: Omar Sandoval <osandov@osandov.com>
# SPDX-License-Identifier: MIT

import argparse
import codecs
import os
import os.path
import re
import subprocess
import sys
from typing import Dict, TextIO, Tuple


_include_re = re.compile(r'include\s*"((?:[^"\\]|\\.)*)"')
_silent_re = re.compile(r"silent")
_endsilent_re = re.compile(r"endsilent")
_config_re = re.compile(r"CONFIG_([^=]+)=(.*)")
_line_re = re.compile(r'("(?:[^"\\]|\\(?:.|$))*(?:"|$)|[^"\\#]|\\(?:.|$))*')


def parse_kconfig(
    file: TextIO, augmented: bool, config: Dict[str, Tuple[str, bool]]
) -> None:
    silent = False
    for lineno, line in enumerate(file, 1):
        line = _line_re.match(line.rstrip()).group()
        if not line:
            continue

        match = _config_re.fullmatch(line)
        if match:
            config[match.group(1)] = match.group(2), silent
            continue

        if augmented:
            match = _include_re.fullmatch(line)
            if match:
                if file is sys.stdin:
                    sys.exit(
                        f"{file.name}:{lineno}: cannot include from standard input"
                    )
                include_path = os.path.join(
                    os.fsencode(os.path.dirname(file.name)),
                    codecs.escape_decode(match.group(1))[0],
                )
                with open(include_path, "r") as include_file:
                    parse_kconfig(include_file, True, config)
                continue

            match = _silent_re.fullmatch(line)
            if match:
                if silent:
                    sys.exit(f"{file.name}:{lineno}: nested silent")
                silent = True
                continue

            match = _endsilent_re.fullmatch(line)
            if match:
                if not silent:
                    sys.exit(f"{file.name}:{lineno}: unmatched endsilent")
                silent = False
                continue

        sys.exit(f"{file.name}:{lineno}: invalid syntax")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate kernel configuration from one or more kernel configuration files."
    )
    parser.add_argument(
        "configs",
        metavar="CONFIG",
        nargs="*",
        help='kernel configuration file or "-" for stdin',
    )
    args = parser.parse_args()

    config: Dict[str, Tuple[str, bool]] = {}
    for path in args.configs:
        if path == "-":
            parse_kconfig(sys.stdin, True, config)
        else:
            with open(path, "r") as f:
                parse_kconfig(f, True, config)

    with open(".config", "w") as f:
        for option, (value, silent) in config.items():
            f.write(f"CONFIG_{option}={value}\n")

    subprocess.check_call(["make", "olddefconfig"])

    generated_config: Dict[str, Tuple[str, bool]] = {}
    with open(".config", "r") as f:
        parse_kconfig(f, False, generated_config)
    status = 0
    for option, (expected_value, silent) in config.items():
        if not silent:
            actual_value = generated_config.get(option, "n")[0]
            if actual_value != expected_value:
                print(
                    f"Expected CONFIG_{option}={expected_value}, got {actual_value}",
                    file=sys.stderr,
                )
                status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
