#!/usr/bin/env python3

import argparse
import os.path
import re

import shlib


class ArchChrootShlib(shlib.Shlib):
    def chroot_call(self, cmd, *args, **kwds):
        self.call(['arch-chroot', '/mnt'] + cmd, *args, **kwds)


PACKAGES = [
    # Base system
    'base',
    'base-devel',
    'grub',
    'rsync',
    'openssh',

    # Development
    'asciidoc',
    'cscope',
    'gdb',
    'git',
    'ltrace',
    'perf',
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


def prepare_storage(sh, args):
    sh.comment('# Prepare storage devices')
    sh.call(['wipefs', '-a', args.root_dev])
    sh.call(['sfdisk', args.root_dev], input="""\
label: dos
,
""")
    args.root_part = args.root_dev + '1'
    sh.call('{} {}'.format(args.mkfs_cmd, args.root_part), shell=True)
    sh.call(['mount', args.root_part, '/mnt'])


def install_packages(sh, args):
    sh.comment('# Install packages')
    sh.comment('# This will be copied to the VM by pacstrap')
    mirrorlist = '\n'.join('Server = {}'.format(mirror) for mirror in args.pacman_mirrors) + '\n'
    sh.write_file('/etc/pacman.d/mirrorlist', mirrorlist)
    sh.call(['pacstrap', '/mnt'] + PACKAGES)
    sh.call('genfstab -U /mnt >> /mnt/etc/fstab', shell=True)


def configure_locale(sh, args):
    sh.comment('# Configure locale')
    locales = '|'.join([re.escape(locale) for locale in args.locales])
    sh.chroot_call(['sed', '-r', '-i', r's/^#({}) /\1 /'.format(locales), '/etc/locale.gen'])
    sh.write_file('/mnt/etc/locale.conf', 'LANG={}\n'.format(args.locales[0]))
    sh.chroot_call(['locale-gen'])


def configure_time(sh, args):
    sh.comment('# Configure time')
    sh.chroot_call(['ln', '-sf', os.path.join('/usr/share/zoneinfo', args.timezone), '/etc/localtime'])
    sh.chroot_call(['hwclock', '--systohc', '--utc'])


def install_bootloader(sh, args):
    sh.comment('# Install bootloader')
    sh.chroot_call(['grub-install', '--target=i386-pc', args.root_dev])
    sh.write_file('/mnt/etc/default/grub', """\
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
    sh.chroot_call(['grub-mkconfig', '-o', '/boot/grub/grub.cfg'])


def configure_networking(sh, args):
    sh.comment('# Configure networking')
    sh.write_file('/mnt/etc/hostname', args.hostname + '\n')
    sh.write_file('/mnt/etc/systemd/network/virtio-net.network', """\
[Match]
MACAddress=52:54:00:12:34:56

[Network]
Address=10.0.2.15/24
Gateway=10.0.2.2
DNS=10.0.2.3
""")
    sh.chroot_call(['systemctl', 'enable', 'systemd-networkd.service'])
    sh.chroot_call(['systemctl', 'enable', 'sshd.service'])


def configure_misc(sh, args):
    sh.comment('# Configure miscellaneous settings')
    sh.write_file('/mnt/etc/sysctl.d/50-sysrq.conf', """\
kernel.sysrq = 1
""")


def configure_users(sh, args):
    sh.comment('# Configure users')
    sh.comment('# For xfstests')
    sh.chroot_call(['useradd', '-m', 'fsgqa'])
    sh.comment('# Finally, set the root password')
    sh.chroot_call(['passwd'])


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

    sh = ArchChrootShlib(dry_run=args.dry_run)
    sh.blank()

    prepare_storage(sh, args)
    sh.blank()

    install_packages(sh, args)
    sh.blank()

    configure_locale(sh, args)
    sh.blank()

    configure_time(sh, args)
    sh.blank()

    install_bootloader(sh, args)
    sh.blank()

    configure_networking(sh, args)
    sh.blank()

    configure_misc(sh, args)
    sh.blank()

    configure_users(sh, args)


if __name__ == '__main__':
    main()
