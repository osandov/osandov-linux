#!/usr/bin/env python3
# SPDX-FileCopyrightText: Omar Sandoval <osandov@osandov.com>
# SPDX-License-Identifier: MIT

import argparse
import math
import re
import struct
import subprocess
import sys
import time
from types import SimpleNamespace


def humanize(number, unit="", precision=1):
    n = float(number)
    for prefix in ("", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"):
        if abs(n) < 1024:
            break
        n /= 1024
    else:
        prefix = "Yi"
    if n.is_integer():
        precision = 0
    return f"{n:.{precision}f}{prefix}{unit}"


def get_seq(dev, ino):
    output = subprocess.check_output(
        ["xfs_db", "-r", dev, "-c", f"inode {ino}", "-c", "p core.atime"],
        universal_newlines=True,
    )
    match = re.search(f"^core.atime.sec = (.*)$", output, flags=re.M)
    return int(time.mktime(time.strptime(match.group(1))))


def read_rt_inode(dev, ino, blocks):
    cmd = ["xfs_db", "-r", dev, "-c", f"inode {ino}"]
    for block in range(blocks):
        cmd.append("-c")
        cmd.append(f"dblock {block}")
        cmd.append("-c")
        cmd.append("p")
    data = bytearray()
    for line in subprocess.check_output(cmd, universal_newlines=True).splitlines():
        match = re.match("[0-9a-fA-F]+: ((?: [0-9a-fA-F]{2})+)", line)
        hexdump = match.group(1).replace(" ", "")
        data.extend(bytes.fromhex(hexdump))
    return data


def print_overview(sb, seq):
    rextsize_bytes = sb.blocksize * sb.rextsize

    if seq == 0:
        numerator = 0
        denominator = 1
    else:
        log2 = seq.bit_length() - 1
        resid = seq - (1 << log2)
        numerator = (resid << 1) + 1
        denominator = 1 << (log2 + 1)
    next_new = (sb.rextents * numerator // denominator) % sb.rextents

    print(
        f"""\
Filesystem block size is {humanize(sb.blocksize, "B")} ({sb.blocksize} bytes)
Realtime extent size is {humanize(rextsize_bytes, "B")} ({rextsize_bytes} bytes)
Realtime device size is {humanize(sb.rextents * rextsize_bytes, "B")}
Filesystem has {sb.rbmblocks} realtime bitmap blocks
Each realtime bitmap block accounts for {humanize(sb.blocksize * 8 * rextsize_bytes, "B")}
Filesystem realtime summary has {sb.rsumlevels} levels
Next location to allocate for a new file is extent {next_new}
                                            byte {humanize(next_new * rextsize_bytes, "B")}
                                            block {next_new // (sb.blocksize * 8)}
                                            fraction {numerator} / {denominator}
                                            percentage {numerator / denominator:.2%}
                                            sequence number {seq}
""",
        end="",
    )


def print_rsum(sb, rsum):
    print(
        "Realtime summary (rows are free extent sizes, columns are bitmap block numbers):"
    )

    def size(i):
        return humanize((sb.blocksize * sb.rextsize) << i, "B")

    size_max_len = max(len(size(i)) for i in range(len(rsum)))
    columns_max = [max(level[bbno] for level in rsum) for bbno in range(len(rsum[0]))]
    columns_max_len = [
        max(len(str(bbno)), len(str(n))) for bbno, n in enumerate(columns_max)
    ]

    print(" " * size_max_len, end="")
    for bbno, column_max in enumerate(columns_max):
        if column_max:
            print(f"{bbno:>{columns_max_len[bbno] + 1}}", end="")
    print()

    for i, level in enumerate(rsum):
        print(f"{size(i):<{size_max_len}}", end="")
        for bbno, n in enumerate(level):
            if columns_max[bbno]:
                column_max_len = columns_max_len[bbno]
                if n:
                    print(f"{n:>{column_max_len + 1}}", end="")
                else:
                    print(" " * (column_max_len + 1), end="")
        print()


def create_rsum(sb, rbm):
    rsum = [[0] * sb.rbmblocks for _ in range(sb.rsumlevels)]
    prev = False
    for i, word in enumerate(rbm):
        for j in range(32):
            cur = bool(word & (1 << j))
            if cur != prev:
                pos = 32 * i + j
                if cur:
                    start = pos
                else:
                    end = pos
                    rsum[(end - start).bit_length() - 1][
                        start // 8 // sb.blocksize
                    ] += 1
            prev = cur
    if prev:
        end = 32 * len(rbm)
        rsum[(end - start).bit_length() - 1][start // 8 // sb.blocksize] += 1
    return rsum


def main():
    parser = argparse.ArgumentParser(description="debug XFS realtime metadata")
    parser.add_argument(
        "dev", help="device containing the filesystem (not the realtime device)"
    )
    parser.add_argument(
        "--dump-summary", action="store_true", help="dump the realtime summary"
    )
    parser.add_argument(
        "--verify-summary",
        action="store_true",
        help="verify the realtime summary against the realtime bitmap",
    )
    args = parser.parse_args()

    sb_output = subprocess.check_output(
        ["xfs_db", "-r", args.dev, "-c", "sb", "-c", "p"], universal_newlines=True
    )
    fields = [
        "blocksize",  # Filesystem block size in bytes.
        "rextents",  # Number of realtime extents
        "rbmino",  # Realtime bitmap inode number.
        "rsumino",  # Realtime summary inode.
        "rextsize",  # Realtime extent size in blocks.
        "rbmblocks",  # Size of the realtime bitmap in blocks.
        "rextslog",  # log2(rextents)
    ]
    regex = r"^(" + "|".join(fields) + r") = (.*)$"
    sb = SimpleNamespace()
    for match in re.finditer(regex, sb_output, re.MULTILINE):
        setattr(sb, match.group(1), int(match.group(2)))
    assert set(fields).issubset(set(dir(sb)))
    # Number of levels in the realtime summary.
    sb.rsumlevels = sb.rextslog + 1
    # Size of the realtime summary in bytes.
    sb.rsumsize = 4 * sb.rsumlevels * sb.rbmblocks

    seq = get_seq(args.dev, sb.rbmino)

    """
    The storage unit for an XFS filesystem is called a block. A block is
    `blocksize` bytes.

    The unit of allocation for the XFS realtime device is a realtime extent. A
    realtime extent is `rextsize` blocks, which is `rextsize * blocksize`
    bytes.

    XFS stores two data structures to track realtime device allocation:

    1. The realtime bitmap. This is a bitmap tracking what is allocated or free
       on the realtime device; each bit represents one realtime extent. A block
       of the bitmap therefore tracks the space for
       `blocksize * 8 * blocksize * rextsize` bytes. E.g., assuming a 4 KiB
       block size and 64 KiB realtime extent size, a block of the bitmap tracks
       the space for a `4 Ki * 8 * 64 Ki = 2 Gi` portion of the realtime
       device.
    2. The realtime summary. This is effectively a two-dimensional array
       `u32 rsum[rsumlevels][rbmblocks]`. `rsum[log][bbno]` is the number of free
       extents of size `2^log` realtime extents that start in block `bbno` of
       the realtime bitmap. E.g., again assuming a 4 KiB block size and a 64
       KiB realtime extent size, `rsum[4][5]` is the number of free
       `2^4 * 64 Ki = 1 Mi` extents that start in the range of logical block
       addresses between 10 Gi and 12 Gi.

    Additionally, the realtime bitmap inode uses its atime field to store a
    sequence number that determines where on disk to allocate space for new
    files. The sequence number translates to a fraction in the sequence 0, 1/2,
    1/4, 3/4, 1/8, ..., 7/8, 1/16, ... This is multiplied by the number of
    extents on the realtime device to give the target extent. The first
    allocation for a new file will be as close to that extent as possible.
    """

    rsumdata = read_rt_inode(
        args.dev, sb.rsumino, math.ceil(sb.rsumsize / sb.blocksize)
    )
    del rsumdata[sb.rsumsize :]
    rsum = list(
        list(level) for level in struct.iter_unpack(f"{sb.rbmblocks}i", rsumdata)
    )

    print_overview(sb, seq)

    if args.dump_summary:
        print()
        print_rsum(sb, rsum)

    if args.verify_summary:
        rbmdata = read_rt_inode(args.dev, sb.rbmino, sb.rbmblocks)
        rbm = list(struct.unpack(f"{sb.rbmblocks * sb.blocksize // 4}I", rbmdata))
        expected_rsum = create_rsum(sb, rbm)
        if expected_rsum != rsum:
            sys.exit("realtime summary does not match realtime bitmap")


if __name__ == "__main__":
    main()
