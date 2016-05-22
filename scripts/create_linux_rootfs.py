#!/usr/bin/env python3

import argparse
import itertools
import os
import re
import shutil
import subprocess
import tempfile


DIRS = [
    'dev',
    'etc',
    'mnt',
    'proc',
    'root',
    'sys',
    'usr',
    'usr/bin',
    'usr/lib',
]


SYMLINKS = [
    ('bin', 'usr/bin'),
    ('etc/mtab', '../proc/self/mounts'),
    ('lib64', 'usr/lib'),
    ('lib', 'usr/lib'),
    ('sbin', 'usr/bin'),
    ('usr/lib64', 'lib'),
    ('usr/sbin', 'bin'),
]


def subprocess_wait_check(proc):
    if proc.wait() != 0:
        raise subprocess.CalledProcessError(proc.returncode, proc.args)


def make_fs_hierarchy():
    for dir in DIRS:
        os.mkdir(dir)
    for link_name, target in SYMLINKS:
        os.symlink(target, link_name)


def install_binary(name):
    binary_path = shutil.which(name)

    loader = None
    ldd = subprocess.Popen(['ldd', binary_path], stdout=subprocess.PIPE)
    dynamic = True
    for line in ldd.stdout:
        if line.strip() == b'not a dynamic executable':
            dynamic = False
        # The only absolute path printed by ldd is the loader.
        match = re.match(rb'\s*(/\S+)', line)
        if match:
            loader = match.group(1).decode('ascii')
    if dynamic:
        subprocess_wait_check(ldd)
        assert loader is not None
    else:
        ldd.wait()
        shutil.copy(binary_path, 'usr/bin')
        return

    libraries = [loader]
    ld_so = subprocess.Popen([loader, '--list', binary_path], stdout=subprocess.PIPE)
    for line in ld_so.stdout:
        match = re.match(rb'\s*\S+ => (\S+)', line)
        if match:
            libraries.append(match.group(1).decode('ascii'))
    subprocess_wait_check(ld_so)

    shutil.copy(binary_path, 'usr/bin')
    for library_path in libraries:
        shutil.copy(library_path, 'usr/lib')


def install_busybox():
    install_binary('busybox')
    # We can't use busybox --install -s because it creates absolute symlinks,
    # and we can't use busybox --install because cpio doesn't preserve
    # hardlinks.
    proc = subprocess.Popen(['usr/bin/busybox', '--list'], stdout=subprocess.PIPE)
    for line in proc.stdout:
        applet = line.strip().decode('ascii')
        try:
            os.symlink('busybox', os.path.join('usr/bin', applet))
        except FileExistsError:
            # The user may have explicitly installed a binary with the same
            # name.
            pass
    subprocess_wait_check(proc)


def install_init():
    init = """\
#!/bin/sh

mount -t proc -o nodev,noexec,nosuid proc /proc
mount -t sysfs -o nodev,noexec,nosuid sys /sys
mount -t devtmpfs -o nosuid dev /dev

exec sh
""".strip()
    with open('init', 'w') as f:
        f.write(init)
    os.chmod('init', 0o755)


def main():
    parser = argparse.ArgumentParser(
        description='create a Linux rootfs suitable for initramfs or chroot'
    )
    parser.add_argument(
        'path', metavar='PATH', help='path to create the root in')

    parser.add_argument(
        '-b', '--binary', metavar='PATH', type=str, dest='binaries',
        action='append',
        help='include the given binary and any libraries it depends on in the rootfs')

    parser.add_argument(
        '--initramfs', action='store_true',
        help='create an initramfs instead of a chroot')
    args = parser.parse_args()

    if args.initramfs:
        tempdir = tempfile.TemporaryDirectory()
        root = tempdir.name
    else:
        os.mkdir(args.path)
        root = args.path

    os.chdir(root)
    make_fs_hierarchy()
    if args.binaries:
        for binary in args.binaries:
            install_binary(binary)
    install_busybox()

    if args.initramfs:
        install_init()
        with open(args.path, 'xb') as f:
            cmd = 'find . -print0 | cpio --quiet --format=newc --create --null | gzip'
            subprocess.run(cmd, stdout=f, shell=True, check=True)
        tempdir.cleanup()


if __name__ == '__main__':
    main()
