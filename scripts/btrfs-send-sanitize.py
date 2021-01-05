#!/usr/bin/env python3
# SPDX-FileCopyrightText: Omar Sandoval <osandov@osandov.com>
# SPDX-License-Identifier: MIT

import argparse
import ctypes
import enum
import hashlib
import os
import struct
import sys

# Btrfs uses crc32c, not the same as the crc32 available in the Python standard
# library. Try to use the implementation in libbtrfs. If we're lucky, we might
# even be able to use the Intel crc32c instruction.
try:
    libbtrfs = ctypes.CDLL('libbtrfs.so.0')
    libbtrfs.crc32c_optimization_init.restype = None
    libbtrfs.crc32c_optimization_init.argtypes = []
    libbtrfs.crc32c_le.restype = ctypes.c_uint32
    libbtrfs.crc32c_le.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_char), ctypes.c_size_t]

    libbtrfs.crc32c_optimization_init()

    def crc32c(b):
        return libbtrfs.crc32c_le(0, b, len(b))
except Exception as e:
    print(e, file=sys.stderr)
    print(f'WARNING: failed to use libbtrfs crc32c. Using slow pure Python implementation.', file=sys.stderr)

    _crc32c_table = [0] * 256
    for i in range(256):
        fwd = i
        for j in range(8, 0, -1):
            if fwd & 1:
                fwd = (fwd >> 1) ^ 0x82f63b78
            else:
                fwd >>= 1
            _crc32c_table[i] = fwd & 0xffffffff

    def crc32c(b):
        crc = 0
        for c in b:
            crc = (crc >> 8) ^ _crc32c_table[(crc ^ c) & 0xff]
        return crc


# From fs/btrfs/send.h.

BTRFS_SEND_STREAM_MAGIC = b'btrfs-stream\0'
BTRFS_SEND_STREAM_VERSION = 1


class BtrfsSendCmd(enum.IntEnum):
    UNSPEC = 0
    SUBVOL = 1
    SNAPSHOT = 2
    MKFILE = 3
    MKDIR = 4
    MKNOD = 5
    MKFIFO = 6
    MKSOCK = 7
    SYMLINK = 8
    RENAME = 9
    LINK = 10
    UNLINK = 11
    RMDIR = 12
    SET_XATTR = 13
    REMOVE_XATTR = 14
    WRITE = 15
    CLONE = 16
    TRUNCATE = 17
    CHMOD = 18
    CHOWN = 19
    UTIMES = 20
    END = 21
    UPDATE_EXTENT = 22


class BtrfsSendAttr(enum.IntEnum):
    UNSPEC = 0
    UUID = 1
    CTRANSID = 2
    INO = 3
    SIZE = 4
    MODE = 5
    UID = 6
    GID = 7
    RDEV = 8
    CTIME = 9
    MTIME = 10
    ATIME = 11
    OTIME = 12
    XATTR_NAME = 13
    XATTR_DATA = 14
    PATH = 15
    PATH_TO = 16
    PATH_LINK = 17
    FILE_OFFSET = 18
    DATA = 19
    CLONE_UUID = 20
    CLONE_CTRANSID = 21
    CLONE_PATH = 22
    CLONE_OFFSET = 23
    CLONE_LEN = 24


def filter_header(infile, outfile):
    magic = infile.read(len(BTRFS_SEND_STREAM_MAGIC))
    if magic != BTRFS_SEND_STREAM_MAGIC:
        raise ValueError('send stream magic does not match')
    outfile.write(magic)

    version_bytes = infile.read(4)
    version, = struct.unpack('<I', version_bytes)
    if version != BTRFS_SEND_STREAM_VERSION:
        raise ValueError(f'expected version {BTRFS_SEND_STREAM_VERSION}, got {version}')
    outfile.write(version_bytes)


# Sanitize a path name by hashing it.
def filter_path(path, hasher):
    new_path = []
    for component in path.split(b'/'):
        if not component or component == b'.' or component == b'..':
            new_path.append(component)
        else:
            hasher = hasher.copy()
            hasher.update(component)
            new_path.append(hasher.hexdigest().encode('ascii'))
    return b'/'.join(new_path)


def filter_cmd(infile, outfile, hasher):
    orig_len, cmd, orig_crc = struct.unpack('<IHI', infile.read(10))
    new_data = bytearray()

    # XXX: elide xattrs completely for now, I don't want to think about
    # sanitizing them.
    if cmd in {BtrfsSendCmd.SET_XATTR, BtrfsSendCmd.REMOVE_XATTR}:
        infile.read(orig_len)
        return

    n = 0
    while n < orig_len:
        tlv_type, orig_tlv_len = struct.unpack('<HH', infile.read(4))
        orig_tlv_value = infile.read(orig_tlv_len)
        n += 4 + orig_tlv_len

        if tlv_type in {BtrfsSendAttr.PATH, BtrfsSendAttr.PATH_TO, BtrfsSendAttr.PATH_LINK, BtrfsSendAttr.CLONE_PATH}:
            new_tlv_value = filter_path(orig_tlv_value, hasher)
        elif tlv_type in {BtrfsSendAttr.DATA,
                          BtrfsSendAttr.CTIME, BtrfsSendAttr.MTIME, BtrfsSendAttr.ATIME, BtrfsSendAttr.OTIME,
                          BtrfsSendAttr.UID, BtrfsSendAttr.GID}:
            # Redact file data, utimes, uids, and gids to all zeroes.
            new_tlv_value = bytes(orig_tlv_len)
        else:
            new_tlv_value = orig_tlv_value
        new_data.extend(struct.pack('<HH', tlv_type, len(new_tlv_value)))
        new_data.extend(new_tlv_value)

    new_crc = crc32c(struct.pack('<IHI', len(new_data), cmd, 0) + new_data)
    outfile.write(struct.pack('<IHI', len(new_data), cmd, new_crc))
    outfile.write(new_data)
    return cmd == BtrfsSendCmd.END


def filter_send_stream(infile, outfile, salt):
    # We seed the hash function with a unique salt per run so that files cannot
    # be identified by hash. E.g., without this, /etc/shadow would always be
    # e80f17310109447772dca82b45ef35a5/3bf1114a986ba87ed28fc1b5884fc2f8. Since
    # file data is redacted, this isn't a big deal, but better safe than sorry.
    hasher = hashlib.md5(salt)

    filter_header(infile, outfile)
    done = False
    while not done:
        done = filter_cmd(infile, outfile, hasher)


def main():
    parser = argparse.ArgumentParser(
        description='sanitize a btrfs-send stream for public sharing')
    args = parser.parse_args()

    filter_send_stream(sys.stdin.buffer, sys.stdout.buffer, os.urandom(8))


if __name__ == '__main__':
    main()
