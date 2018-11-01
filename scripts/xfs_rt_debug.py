#!/usr/bin/env python3

import argparse
import math
import re
import subprocess
import struct
from types import SimpleNamespace


def humanize(n, precision=1):
    n = float(n)
    for unit in ['', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi', 'Ei', 'Zi']:
        if abs(n) < 1024:
            break
        n /= 1024
    else:
        unit = 'Y'
    if n.is_integer():
        precision = 0
    return "%.*f%sB" % (precision, n, unit)


def read_rt_inode(dev, ino, blocks):
    cmd = ['xfs_db', '-r', dev, '-c', f'inode {ino}']
    for block in range(blocks):
        cmd.append('-c')
        cmd.append(f'dblock {block}')
        cmd.append('-c')
        cmd.append('p')
    data = bytearray()
    for line in subprocess.check_output(cmd, universal_newlines=True).splitlines():
        match = re.match('[0-9a-fA-F]+: ((?: [0-9a-fA-F]{2})+)', line)
        hexdump = match.group(1).replace(' ', '')
        data.extend(bytes.fromhex(hexdump))
    return data


def print_rsum(sb, rsum):
    for i, level in enumerate(rsum):
        print(humanize((sb.blocksize * sb.rextsize) << i), end='\t')
        for n in level:
            if n:
                print(f'{n:4}', end=' ')
            else:
                print('    ', end=' ')
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
                    rsum[(end - start).bit_length() - 1][start // 8 // sb.blocksize] += 1
            prev = cur
    if prev:
        end = 32 * len(rbm)
        rsum[(end - start).bit_length() - 1][start // 8 // sb.blocksize] += 1
    return rsum


def main():
    parser = argparse.ArgumentParser(description='debug XFS realtime metadata')
    parser.add_argument(
        'dev',
        help='device containing the filesystem (not the realtime device)')
    parser.add_argument(
        '--dump-summary', action='store_true',
        help='dump the realtime summary')
    parser.add_argument(
        '--verify-summary', action='store_true',
        help='verify the realtime summary against the realtime bitmap')
    parser.add_argument(
        '--summary-minmax', action='store_true',
        help='print the minimum and maximum size for each bitmap block')
    args = parser.parse_args()

    if not args.dump_summary and not args.verify_summary:
        parser.error('at least one of --dump-summary or --verify-summary is required')

    cmd = ['xfs_db', '-r', args.dev, '-c', 'sb', '-c', 'p']
    sb_output = subprocess.check_output(cmd, universal_newlines=True)
    fields = ['blocksize', 'rbmblocks', 'rbmino', 'rextents', 'rextsize',
              'rextslog', 'rsumino']
    regex = r'^(' + '|'.join(fields) + r') = (.*)$'
    sb = SimpleNamespace()
    for match in re.finditer(regex, sb_output, re.MULTILINE):
        setattr(sb, match.group(1), int(match.group(2)))
    assert set(fields).issubset(set(dir(sb)))
    sb.rsumlevels = sb.rextslog + 1
    sb.rsumsize = 4 * sb.rsumlevels * sb.rbmblocks

    rsumdata = read_rt_inode(args.dev, sb.rsumino,
                             math.ceil(sb.rsumsize / sb.blocksize))
    del rsumdata[sb.rsumsize:]
    rsum = list(list(level) for level in struct.iter_unpack(f'{sb.rbmblocks}i', rsumdata))

    if args.dump_summary:
        print_rsum(sb, rsum)

    if args.verify_summary:
        rbmdata = read_rt_inode(args.dev, sb.rbmino, sb.rbmblocks)
        rbm = list(struct.unpack(f'{sb.rbmblocks * sb.blocksize // 4}I', rbmdata))
        expected_rsum = create_rsum(sb, rbm)
        assert expected_rsum == rsum



if __name__ == '__main__':
    main()
