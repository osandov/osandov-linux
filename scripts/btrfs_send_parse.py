#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
import datetime
from enum import IntEnum
import struct
import sys
from typing import Any, BinaryIO, Iterator, Sequence, Union
import uuid

BTRFS_SEND_STREAM_MAGIC = b"btrfs-stream\0"
BTRFS_SEND_STREAM_VERSION = 1


class CmdType(IntEnum):
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


class AttrType(IntEnum):
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


@dataclass
class DevT:
    major: int
    minor: int


@dataclass
class Timestamp:
    sec: int
    nsec: int


@dataclass
class Attr:
    type: Union[AttrType, int]
    value: Any


@dataclass
class Cmd:
    type: Union[CmdType, int]
    attrs: Sequence[Attr]
    crc: int


def parse_send_stream(file: BinaryIO) -> Iterator[Cmd]:
    magic = file.read(len(BTRFS_SEND_STREAM_MAGIC))
    if magic != BTRFS_SEND_STREAM_MAGIC:
        raise ValueError("send stream magic does not match")

    version_bytes = file.read(4)
    (version,) = struct.unpack("<I", version_bytes)
    if version != BTRFS_SEND_STREAM_VERSION:
        raise ValueError(f"expected version {BTRFS_SEND_STREAM_VERSION}, got {version}")

    while True:
        cmd_len, cmd, crc = struct.unpack("<IHI", file.read(10))
        try:
            cmd = CmdType(cmd)
        except ValueError:
            pass
        attrs = []
        n = 0
        while n < cmd_len:
            attr_type, attr_len = struct.unpack("<HH", file.read(4))
            try:
                attr_type = AttrType(attr_type)
            except ValueError:
                pass
            attr_value: Any = file.read(attr_len)
            n += 4 + attr_len

            if attr_type in {
                AttrType.CTRANSID,
                AttrType.INO,
                AttrType.SIZE,
                AttrType.MODE,
                AttrType.UID,
                AttrType.GID,
                AttrType.FILE_OFFSET,
                AttrType.CLONE_CTRANSID,
                AttrType.CLONE_OFFSET,
                AttrType.CLONE_LEN,
            }:
                attr_value = int.from_bytes(attr_value, "little")
            elif attr_type == AttrType.RDEV:
                dev = int.from_bytes(attr_value, "little")
                attr_value = DevT(
                    (dev & 0xFFF00) >> 8, (dev & 0xFF) | ((dev >> 12) & 0xFFF00),
                )
            elif attr_type in {
                AttrType.CTIME,
                AttrType.MTIME,
                AttrType.ATIME,
                AttrType.OTIME,
            }:
                attr_value = Timestamp(*struct.unpack("<QI", attr_value))

            attrs.append(Attr(attr_type, attr_value))
        yield Cmd(cmd, attrs, crc)
        if cmd == CmdType.END:
            break


def main() -> None:
    parser = argparse.ArgumentParser(
        description="parse and dump a Btrfs send stream in a human-readable format",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-s",
        "--string-limit",
        metavar="N",
        type=int,
        default=32,
        help="maximum string size to print",
    )
    parser.add_argument(
        "-c", "--crc", action="store_true", default=False, help="show CRCs of commands"
    )
    args = parser.parse_args()

    for cmd in parse_send_stream(sys.stdin.buffer):
        if isinstance(cmd.type, CmdType):
            print(cmd.type.name)
        else:
            print(f"Unknown command {cmd.type}")
        if args.crc:
            print(f"  crc {cmd.crc:#x}")
        for attr in cmd.attrs:
            if isinstance(attr.type, AttrType):
                print(f"  {attr.type.name}", end=" ")
            else:
                print(f"  Unknown attribute {attr.type}", end=" ")
            if isinstance(attr.value, bytes):
                if attr.type in {
                    AttrType.XATTR_NAME,
                    AttrType.PATH,
                    AttrType.PATH_TO,
                    AttrType.PATH_LINK,
                    AttrType.CLONE_PATH,
                }:
                    print(repr(attr.value)[1:])
                elif attr.type in {AttrType.UUID, AttrType.CLONE_UUID}:
                    print(uuid.UUID(bytes=attr.value))
                else:
                    print(
                        f"[{len(attr.value)} bytes]",
                        repr(attr.value[: args.string_limit])[1:],
                        end="...\n" if len(attr.value) > args.string_limit else "\n",
                    )
            elif isinstance(attr.value, DevT):
                print(f"{attr.value.major}, {attr.value.minor}")
            elif isinstance(attr.value, Timestamp):
                ts = attr.value.sec + attr.value.nsec / 1000000000
                print(datetime.datetime.fromtimestamp(ts))
            elif attr.type == AttrType.MODE:
                print(f"0{attr.value:o}")
            else:
                print(attr.value)


if __name__ == "__main__":
    main()
