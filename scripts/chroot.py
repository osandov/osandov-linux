#!/usr/bin/env python3

import argparse
import ctypes
import os
import os.path


libc = ctypes.CDLL('libc.so.6', use_errno=True)
libc.unshare.restype = ctypes.c_int
libc.unshare.argtypes = [ctypes.c_int]
libc.mount.restype = ctypes.c_int
libc.mount.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_ulong, ctypes.c_void_p]
libc.umount2.restype = ctypes.c_int
libc.umount2.argtypes = [ctypes.c_char_p, ctypes.c_int]
libc.syscall.restype = ctypes.c_int


# From /usr/include/linux/sched.h
CLONE_FS = 0x00000200
CLONE_FILES = 0x00000400
CLONE_NEWNS = 0x00020000
CLONE_SYSVSEM = 0x00040000
CLONE_NEWUTS = 0x04000000
CLONE_NEWIPC = 0x08000000
CLONE_NEWUSER = 0x10000000
CLONE_NEWPID = 0x20000000
CLONE_NEWNET = 0x40000000

# From /usr/include/sys/mount.h
MS_RDONLY = 1
MS_NOSUID = 2
MS_NODEV = 4
MS_NOEXEC = 8
MS_SYNCHRONOUS = 16
MS_REMOUNT = 32
MS_MANDLOCK = 64
MS_DIRSYNC = 128
MS_NOATIME = 1024
MS_NODIRATIME = 2048
MS_BIND = 4096
MS_MOVE = 8192
MS_REC = 16384
MS_VERBOSE = 32768
MS_SILENT = 32768
MS_POSIXACL = (1<<16)
MS_UNBINDABLE = (1<<17)
MS_PRIVATE = (1<<18)
MS_SLAVE = (1<<19)
MS_SHARED = (1<<20)
MS_RELATIME = (1<<21)
MS_KERNMOUNT = (1<<22)
MS_I_VERSION = (1<<23)
MS_STRICTATIME = (1<<24)
MS_LAZYTIME = (1<<25)
# These sb flags are internal to the kernel
# MS_NOSEC = (1<<28)
# MS_BORN = (1<<29)
# MS_ACTIVE = (1<<30)
# MS_NOUSER = (1<<31)

# From /usr/include/sys/mount.h
MNT_FORCE = 1
MNT_DETACH = 2
MNT_EXPIRE = 4
UMOUNT_NOFOLLOW = 8


def unshare(flags):
    ret = libc.unshare(flags)
    if ret == -1:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno))


def mount(source, target, filesystemtype, flags, data):
    source = source.encode('utf-8')
    target = target.encode('utf-8')
    if filesystemtype is not None:
        filesystemtype = filesystemtype.encode('utf-8')
    ret = libc.mount(source, target, filesystemtype, flags, data)
    if ret == -1:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno))


def umount(target, flags=0):
    target = target.encode('utf-8')
    ret = libc.umount2(target, flags)
    if ret == -1:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno))


def pivot_root(new_root, put_old):
    SYS_pivot_root = 155  # XXX: arch-dependent
    ret = libc.syscall(ctypes.c_int(SYS_pivot_root),
                       ctypes.c_char_p(new_root.encode('utf-8')),
                       ctypes.c_char_p(put_old.encode('utf-8')))
    if ret == -1:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno))


def main():
    parser = argparse.ArgumentParser(
        description='run in a chroot'
    )
    parser.add_argument(
        'root', metavar='ROOT', help='chroot directory')
    parser.add_argument(
        '--no-pivot', dest='pivot', action='store_false',
        help="don't pivot_root before chroot")
    args = parser.parse_args()

    unshare(CLONE_NEWNS)
    mount('none', '/', None, MS_REC | MS_PRIVATE, None)
    if args.pivot:
        mount(args.root, args.root, None, MS_BIND, None)
    os.chdir(args.root)
    if args.pivot:
        pivot_root('.', 'mnt')
        umount('mnt', MNT_DETACH)
    os.chroot('.')
    mount('proc', '/proc', 'proc', MS_NODEV | MS_NOEXEC | MS_NOSUID, None)
    mount('sys', '/sys', 'sysfs', MS_NODEV | MS_NOEXEC | MS_NOSUID, None)
    mount('dev', '/dev', 'devtmpfs', MS_NOSUID, None)
    os.execve('/bin/sh', ['/bin/sh', '-i'], {
        'HOME': '/root',
        'PATH': '/usr/bin',
        'SHELL': '/bin/sh',
        'USER': 'root',
    })


if __name__ == '__main__':
    main()
