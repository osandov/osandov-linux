#!/usr/bin/env python3

import argparse
import os.path
import re
import shlex
import subprocess


PACKAGES=[
	# Base system
	'base',
	'base-devel',
	'grub',

	# Development
	'git',
	'python',
	'python2',
	'strace',
	'vim',

	# xfstests
	'attr',
	'bc',
	'fio',
	'libaio',
	'psmisc',
        'xfsprogs',
]


def comment(args, comment=''):
    if args.dry_run:
        print(comment)


def call(args, exec_args):
    if args.dry_run:
        print(' '.join(shlex.quote(arg) for arg in exec_args))
    else:
        subprocess.check_call(exec_args)


def chroot_call(args, exec_args):
    call(args, ['arch-chroot', '/mnt'] + exec_args)


def call_shell(args, cmd):
    if args.dry_run:
        print(cmd)
    else:
        subprocess.check_call(cmd, shell=True)


def call_with_input(args, exec_args, input):
    if args.dry_run:
        print('{} << "EOF"\n{}EOF'.format(' '.join(shlex.quote(arg) for arg in exec_args), input))
    else:
        subprocess.run(exec_args, input=input, check=True, universal_newlines=True)


def write_file(args, path, contents):
    if args.dry_run:
        print('cat << "EOF" > {}\n{}EOF'.format(shlex.quote(path), contents))
    else:
        with open(path, 'w') as f:
            f.write(contents)


def prepare_storage(args):
    if args.dry_run:
        comment(args, '# Prepare storage devices')
    call(args, ['wipefs', '-a', args.root_dev])
    call_with_input(args, ['sfdisk', args.root_dev], input="""\
label: dos
,
""")
    args.root_part = args.root_dev + '1'
    call_shell(args, '{} {}'.format(args.mkfs_cmd, args.root_part))
    call(args, ['mount', args.root_part, '/mnt'])


def install_packages(args):
    comment(args, '# Install packages')
    comment(args, '# This will be copied to the VM by pacstrap')
    mirrorlist = '\n'.join('Server = {}'.format(mirror) for mirror in args.pacman_mirrors) + '\n'
    write_file(args, '/etc/pacman.d/mirrorlist', mirrorlist)
    call(args, ['pacstrap', '/mnt'] + PACKAGES)
    call_shell(args, 'genfstab -U /mnt >> /mnt/etc/fstab')


def configure_locale(args):
    comment(args, '# Configure locale')
    locales = '|'.join([re.escape(locale) for locale in args.locales])
    chroot_call(args, ['sed', '-r', '-i', r's/^#({}) /\1 /'.format(locales), '/etc/locale.gen'])
    write_file(args, '/mnt/etc/locale.conf', 'LANG={}\n'.format(args.locales[0]))
    chroot_call(args, ['locale-gen'])


def configure_time(args):
    comment(args, '# Configure time')
    chroot_call(args, ['ln', '-s', os.path.join('/usr/share/zoneinfo', args.timezone), '/etc/localtime'])
    chroot_call(args, ['hwclock', '--systohc', '--utc'])


def install_bootloader(args):
    comment(args, '# Install bootloader')
    chroot_call(args, ['grub-install', '--target=i386-pc', args.root_dev])
    write_file(args, '/mnt/etc/default/grub', """\
GRUB_DEFAULT=0
GRUB_TIMEOUT=5
GRUB_DISTRIBUTOR="Arch"

GRUB_TERMINAL="console serial"
GRUB_SERIAL_COMMAND="serial --speed=115200"

GRUB_GFXMODE=auto
GRUB_GFXPAYLOAD_LINUX=keep

GRUB_CMDLINE_LINUX_DEFAULT=""
GRUB_CMDLINE_LINUX="console=ttyS0,115200"
GRUB_DISABLE_RECOVERY=true
""")
    chroot_call(args, ['grub-mkconfig', '-o', '/boot/grub/grub.cfg'])


def configure_networking(args):
    comment(args, '# Configure networking')
    write_file(args, '/mnt/etc/hostname', args.hostname + '\n')
    chroot_call(args, ['systemctl', 'enable', 'dhcpcd.service'])


def configure_users(args):
    comment(args, '# Configure users')
    comment(args, '# For xfstests')
    chroot_call(args, ['useradd', 'fsgqa'])
    comment(args, '# Finally, set the root password')
    chroot_call(args, ['passwd'])


def main():
    parser = argparse.ArgumentParser(
        description='set up an Arch Linux virtual machine from the installation disk',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='print the command lines that would be run instead of running them')

    parser.add_argument(
        '--root-dev', metavar='DEV', default='/dev/vda',
        help='device to partition for root file system and bootloader')

    parser.add_argument(
        '--mkfs-cmd', metavar='CMD', default='mkfs.ext4',
        help='command to run on the root device')

    parser.add_argument(
        '--pacman-mirrors', metavar='URL', nargs='+',
        default=['https://mirrors.kernel.org/archlinux/$repo/os/$arch'],
        help='mirror list to use for pacman')

    parser.add_argument(
        '--locales', metavar='LOCALE', nargs='+', default=['en_US.UTF-8'],
        help='locales to generate; the first one is used as the default')

    parser.add_argument(
        '--timezone', metavar='TZ', default='America/Los_Angeles',
        help='time zone to use; see tzselect(8)')

    parser.add_argument(
        '--hostname', metavar='NAME', required=True, default=argparse.SUPPRESS,
        help='hostname to use for the virtual machine (required)')

    args = parser.parse_args()

    comment(args, '#!/bin/sh')
    comment(args)
    comment(args, 'set -e')
    comment(args)

    prepare_storage(args)
    comment(args)

    install_packages(args)
    comment(args)

    configure_locale(args)
    comment(args)

    configure_time(args)
    comment(args)

    install_bootloader(args)
    comment(args)

    configure_networking(args)
    comment(args)

    configure_users(args)


if __name__ == '__main__':
    main()
