#!/usr/bin/env python3

import argparse
from collections import namedtuple
import ctypes
import os
import re
import sys


libc = ctypes.CDLL('libc.so.6', use_errno=True)
libc.setns.restype = ctypes.c_int
libc.setns.argtypes = [ctypes.c_int, ctypes.c_int]
libc.umount2.restype = ctypes.c_int
libc.umount2.argtypes = [ctypes.c_char_p, ctypes.c_int]


def setns(fd, nstype=0):
    ret = libc.setns(fd, nstype)
    if ret == -1:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno))


def umount(target, flags=0):
    ret = libc.umount2(target, flags)
    if ret == -1:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno))


MOUNTINFO_RE = re.compile(
    rb'(?P<mount_id>\d+) (?P<parent_id>\d+) (?P<major>\d+):(?P<minor>\d+) '
    rb'(?P<root>[^ ]+) (?P<mount_point>[^ ]+) (?P<mount_options>[^ ]+) '
    rb'(?P<optional>.*) - (?P<fs_type>[^ ]+) (?P<source>[^ ]+) '
    rb'(?P<super_options>[^ ]+)\n')


Mount = namedtuple('Mount', [
    'mount_id',
    'parent_id',
    'major',
    'minor',
    'root',
    'mount_point',
    'mount_options',
    'optional',
    'fs_type',
    'source',
    'super_options',
])


def mounts(pid='self'):
    with open(f'/proc/{pid}/mountinfo', 'rb') as f:
        for line in f:
            match = MOUNTINFO_RE.fullmatch(line)
            assert match
            optional = []
            for field in match['optional'].split():
                if b':' in field:
                    tag, value = field.split(b':', 1)
                    optional.append((tag.decode('unicode-escape'), value.decode('unicode-escape')))
                else:
                    optional.append((field.decode('unicode-escape'), None))
            yield Mount(
                mount_id=int(match['mount_id']),
                parent_id=int(match['parent_id']),
                major=int(match['major']),
                minor=int(match['minor']),
                root=match['root'].decode('unicode-escape'),
                mount_point=match['mount_point'].decode('unicode-escape'),
                mount_options=match['mount_options'].decode('unicode-escape'),
                optional=optional,
                fs_type=match['fs_type'].decode('unicode-escape'),
                source=match['source'].decode('unicode-escape'),
                super_options=match['super_options'].decode('unicode-escape'),
            )


def main():
    parser = argparse.ArgumentParser(
        description='unmount a filesystem in all mount namespaces')
    parser.add_argument(
        'source', metavar='SOURCE', help='source (e.g., block device) to unmount')
    args = parser.parse_args()

    success = True

    namespaces = set()
    for dir in os.scandir('/proc'):
        if not dir.name.isdigit():
            continue

        mnt_ns = -1
        pid_ns = -1
        try:
            mnt_ns = os.open(os.path.join(dir.path, 'ns', 'mnt'), os.O_RDONLY)
            mnt_ns_ino = os.fstat(mnt_ns).st_ino
            if mnt_ns_ino in namespaces:
                continue

            pid_ns = os.open(os.path.join(dir.path, 'ns', 'pid'), os.O_RDONLY)
            root = os.readlink(os.path.join(dir.path, 'root'))

            # Add this after we've gotten everything we need from /proc. If it
            # failed before this, it might be because the process we were
            # looking at disappeared, so we should still try again if we find
            # another process in that mount namespace.
            namespaces.add(mnt_ns_ino)

            # setns() with a PID namespace changes the namespace that child
            # processes will be created in.
            setns(pid_ns)

            pid = os.fork()
            if pid:
                wstatus = os.waitpid(pid, 0)[1]
                if not os.WIFEXITED(wstatus) or os.WEXITSTATUS(wstatus) != 0:
                    success = False
            else:
                try:
                    setns(mnt_ns)
                    os.chroot(root)
                    os.chdir('/')
                    for mount in mounts():
                        if mount.source == args.source:
                            umount(mount.mount_point.encode())
                except Exception as e:
                    print(e, file=sys.stderr)
                    os._exit(1)
                else:
                    os._exit(0)
        except OSError as e:
            print(e, file=sys.stderr)
        finally:
            if mnt_ns != -1:
                os.close(mnt_ns)
            if pid_ns != -1:
                os.close(pid_ns)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
