#!/usr/bin/env python3

import argparse
import os
import os.path
import shutil
import subprocess
import sys


CHUNK_SIZE = 1024 * 1024 * 1024  # 1 GB


def cycle_mount_btrfsck(dev, mnt):
    subprocess.check_call(['umount', '--', mnt])
    subprocess.check_call(['btrfs', 'check', '--', dev])
    subprocess.check_call(['mount', '--', dev, mnt])


def create_files(test_dir, sectorsize, numfiles):
    os.chdir(test_dir)
    for i in range(numfiles):
        if i % 2048 == 0:
            print('Created {}/{} files...'.format(i, numfiles), end='\r')
        fd = os.open(str(i), os.O_WRONLY | os.O_CREAT)
        try:
            os.posix_fallocate(fd, 0, sectorsize)
        finally:
            os.close(fd)
    print('Created {0}/{0} files...'.format(numfiles))
    os.chdir('/')


def unlink_every_other_file(test_dir, numfiles):
    os.chdir(test_dir)
    for i in range(0, numfiles, 2):
        if i % 4096 == 0:
            print('Unlinked {}/{} files...'.format(i // 2, numfiles // 2), end='\r')
        os.unlink(str(i))
    print('Unlinked {0}/{0} files...'.format(numfiles // 2))
    os.chdir('/')


def benchmark(args):
    numfiles = CHUNK_SIZE // args.sectorsize

    print('Creating filesystem...')
    try:
        os.mkdir(args.mnt)
    except FileExistsError:
        pass
    subprocess.check_call(['mkfs.btrfs', '-f', '-d', 'single', '-m', 'single',
                           '-s', str(args.sectorsize), '--', args.dev])
    subprocess.check_call(['mount', '-o', 'space_cache=v2', '--', args.dev, args.mnt])
    try:
        # Get rid of the 8 MB data block group that mkfs.btrfs makes, we want a
        # full-sized 1 GB block group.
        subprocess.check_call(['btrfs', 'balance', 'start', '-d', args.mnt])
        if args.check:
            cycle_mount_btrfsck(args.dev, args.mnt)

        test_dir = os.path.join(args.mnt, 'dir')
        os.mkdir(test_dir)

        # Create a bunch of sectorsize files.
        create_files(test_dir, args.sectorsize, numfiles)
        if args.check:
            cycle_mount_btrfsck(args.dev, args.mnt)

        # This will more or less free every other sector in the data block
        # group, which is the worst case for extents. At some point, we'll
        # convert over to bitmaps.
        unlink_every_other_file(test_dir, numfiles)
        if args.check:
            cycle_mount_btrfsck(args.dev, args.mnt)

        # Now unlink everything else, which will cause us to convert back to
        # extents.
        print('Removing everything else...')
        shutil.rmtree(test_dir)
    finally:
        subprocess.call(['umount', '--', args.mnt])
    if args.check:
        subprocess.check_call(['btrfs', 'check', '--', args.dev])


def main():
    parser = argparse.ArgumentParser(
        description='fragment the Btrfs free space tree for testing',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument(
        'dev', metavar='DEV', type=str, default=argparse.SUPPRESS,
        help='device to test on (WARNING: will be reformatted)')
    parser.add_argument(
        '-s', '--sectorsize', type=int, default=os.sysconf('SC_PAGESIZE'),
        help='sectorsize to pass to mkfs.btrfs')
    parser.add_argument(
        '-m', '--mnt', type=str, default='/tmp/fragment_free_space_tree',
        help='test file system mountpoint path')
    parser.add_argument(
        '-c', '--check', action='store_true',
        help='check the filesystem with `btrfs check` between steps')
    parser.add_argument(
        '-r', '--record', choices=['ftrace', 'perf'],
        help='record the benchmark')
    # Internal flag for when we're being re-executed by trace-cmd or perf.
    parser.add_argument(
        '--recording', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.recording or args.record is None:
        benchmark(args)
    else:
        if args.record == 'ftrace':
            wrapper = [
                'trace-cmd', 'record', '-o', '/tmp/trace.dat', '-p', 'function_graph',
                '-g', 'add_to_free_space_tree', '-l', 'add_to_free_space_tree',
                '-g', 'remove_from_free_space_tree', '-l', 'remove_from_free_space_tree',
                '-g', 'convert_free_space_to_bitmaps', '-l', 'convert_free_space_to_bitmaps',
                '-g', 'convert_free_space_to_extents', '-l', 'convert_free_space_to_extents',
            ]
        elif args.record == 'perf':
            wrapper = ['perf', 'record', '-o', '/tmp/perf.data', '-g', '-a']
        wrapper.append('--')
        wrapper.extend(sys.argv)
        wrapper.append('--recording')
        subprocess.check_call(wrapper)


if __name__ == '__main__':
    main()
