#!/usr/bin/env python3

import argparse
import errno
import getpass
import os
import os.path
import pty
import re
import runpy
import selectors
import shlex
import signal
import subprocess
import sys
import termios
import tty
import urllib.request


def prompt_yes_no(prompt, default=True):
    prompt += ' [Y/n] ' if default else ' [y/N] '
    sys.stderr.write(prompt)
    sys.stderr.flush()
    answer = input().strip().lower()
    if answer.startswith('y'):
        return True
    elif answer.startswith('n'):
        return False
    else:
        return default


def cmd_create(args):
    vm_dir = os.path.expanduser('~/linux/vm')
    os.makedirs(vm_dir, exist_ok=True)
    os.chdir(vm_dir)

    os.mkdir(args.name)
    print(f'Creating {args.name!r}, cpu={args.cpu} memory={args.memory}')
    subprocess.run(['qemu-img', 'create', '-f', 'qcow2', '-o', 'nocow=on',
                    f'{args.name}/{args.name}.qcow2', args.size], check=True)
    with open(f'{args.name}/config.py', 'w') as f:
        f.write(f"""\
qemu_options = [
    '-nodefaults',
    '-nographic',
    '-serial', 'mon:stdio',

    '-cpu', 'kvm64',
    '-enable-kvm',
    '-smp', {args.cpu!r},
    '-m', {args.memory!r},
    '-watchdog', 'i6300esb',

    # Host forwarding can be enabled by adding to the -netdev option:
    # hostfwd=[tcp|udp]:[hostaddr]:hostport-[guestaddr]:guestport
    # e.g., hostfwd=tcp:127.0.0.1:2222-:22
    '-netdev', 'user,id=vlan0',
    '-device', 'virtio-net,netdev=vlan0',

    '-drive', 'file={args.name}/{args.name}.qcow2,index=0,media=disk,if=virtio,cache=none',
]

kernel_cmdline = [
    'root=/dev/vda1',
    'console=ttyS0,115200',
]
""")


def get_qemu_args(args):
    config = runpy.run_path(os.path.join(args.name, 'config.py'))

    qemu_options = ['qemu-system-x86_64']
    qemu_options.extend(config.get('qemu_options', []))

    # Command-line arguments.
    if hasattr(args, 'kernel'):
        build_path = os.path.join(os.path.expanduser('~/linux/builds/'), args.kernel)
        image_name = subprocess.check_output(
            ['make', '-s', 'image_name'], cwd=build_path,
            universal_newlines=True).strip()
        kernel_image_path = os.path.join(build_path, image_name)
        qemu_options.extend(('-kernel', kernel_image_path))
        virtfs_opts = [
            'local', f'path={build_path}', 'security_model=none', 'readonly',
            'mount_tag=modules',
        ]
        qemu_options.extend(('-virtfs', ','.join(virtfs_opts)))

    if hasattr(args, 'initrd'):
        qemu_options.extend(('-initrd', args.initrd))
    if hasattr(args, 'qemu_options'):
        qemu_options.extend(args.qemu_options)

    kernel_cmdline = config.get('kernel_cmdline', [])
    if hasattr(args, 'append'):
        kernel_cmdline.extend(args.append)

    # Don't use the VM script's default append line if a kernel image was not
    # passed. If it was passed explicitly, let QEMU error out on the user.
    if (('-kernel' in qemu_options or hasattr(args, 'append')) and
        '-append' not in qemu_options):
        qemu_options.extend(('-append', ' '.join(kernel_cmdline)))

    return qemu_options


def cmd_run(args):
    os.chdir(os.path.expanduser('~/linux/vm'))
    args = get_qemu_args(args)
    os.execvp(args[0], args)


def download_latest_archiso(mirror):
    with urllib.request.urlopen(mirror) as url:
        latest = re.search(r'archlinux-\d{4}\.\d{2}\.\d{2}-x86_64\.iso',
                           url.read().decode()).group()

    iso_dir = os.path.expanduser('~/linux/vm/iso')
    iso_path = os.path.join(iso_dir, latest)

    if not os.path.exists(iso_path):
        if not prompt_yes_no(f'Download latest Arch Linux ISO ({latest}) to ~/linux/vm/iso?'):
            sys.exit('Use --iso if you have a previously downloaded ISO you want to use')
        os.makedirs(iso_dir, exist_ok=True)
        subprocess.run(['curl', '-C', '-', '-f', '-o', iso_path + '.part', mirror + '/' + latest],
                       check=True)
        # TODO: check checksum
        os.rename(iso_path + '.part', iso_path)
    return iso_path


def install_script(args, proxy_vars):
    script = []
    script.append(f"""\
#!/bin/bash

set -ex

root_dev={shlex.quote(args.root_dev)}
root_part="${{root_dev}}1"
mkfs_cmd={shlex.quote(args.mkfs_cmd)}
mirrors=({' '.join(shlex.quote(mirror) for mirror in args.pacman_mirrors)})
packages=({' '.join(shlex.quote(package) for package in args.packages)})
locale={shlex.quote(args.locales[0])}
locales={shlex.quote('|'.join([re.escape(locale) for locale in args.locales]))}
timezone={shlex.quote(args.timezone)}
hostname={shlex.quote(args.hostname)}
user={shlex.quote(args.user)}
""")

    script.append(r"""
gateway="$(ip route show default | gawk 'match($0, /^\s*default.*via\s+([0-9.]+)/, a) { print a[1]; exit }')"
[[ -z $gateway ]] && { echo "Could not find gateway" >&2; exit 1; }

nic="$(ip route show default | gawk 'match($0, /^\s*default.*dev\s+(\S+)/, a) { print a[1]; exit }')"
[[ -z $nic ]] && { echo "Could not find network interface" >&2; exit 1; }

ip_address="$(ip addr show dev "$nic" | gawk 'match($0, /^\s*inet\s+([0-9.]+\/[0-9]+)/, a) { print a[1]; exit }')"
[[ -z $ip_address ]] && { echo "Could not find IP address" >&2; exit 1; }

mac_address="$(ip addr show dev "$nic" | gawk 'match($0, /^\s*link\/ether\s+([0-9A-Fa-f:]+)/, a) { print a[1]; exit }')"
[[ -z $mac_address ]] && { echo "Could not find MAC address" >&2; exit 1; }

dns_server="$(gawk 'match($0, /^\s*nameserver\s+([0-9.]+)/, a) {print a[1]; exit}' /etc/resolv.conf)"
[[ -z $dns_server ]] && { echo "Could not find DNS server" >&2; exit 1; }
""")

    script.append(r"""
# Prepare storage devices
wipefs -a "${root_dev}"
parted "${root_dev}" --align optimal --script mklabel msdos mkpart primary 0% 100%
${mkfs_cmd} "${root_part}"
mount "${root_part}" /mnt

# Install packages
# dirmngr doesn't use http_proxy by default. Additionally, its built-in DNS
# resolver doesn't seem to play nicely with QEMU.
cat << "EOF" > /etc/pacman.d/gnupg/dirmngr.conf
honor-http-proxy
standard-resolver
EOF
# This will be copied to the installed system by pacstrap
: > /etc/pacman.d/mirrorlist
for mirror in "${mirrors[@]}"; do
	echo "Server = ${mirror}" >> /etc/pacman.d/mirrorlist
done
pacstrap /mnt "${packages[@]}"
genfstab -U /mnt >> /mnt/etc/fstab
cp /etc/pacman.d/gnupg/dirmngr.conf /mnt/etc/pacman.d/gnupg/dirmngr.conf
""")
    if proxy_vars:
        script.append(f"""
# Configure proxy
cat << "EOF" > /mnt/etc/profile.d/proxy.sh
{proxy_vars}EOF
""")
    script.append(r"""
# Configure locale
sed -r -i "s/^#(${locales}) /\\1 /" /mnt/etc/locale.gen
echo "LANG=${locale}" > /mnt/etc/locale.conf
arch-chroot /mnt locale-gen

# Configure time
ln -sf /usr/share/zoneinfo/"${timezone}" /mnt/etc/localtime
arch-chroot /mnt hwclock --systohc --utc

# Install bootloader
arch-chroot /mnt grub-install --target=i386-pc "${root_dev}"
cat << "EOF" > /mnt/etc/default/grub
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
EOF
arch-chroot /mnt grub-mkconfig -o /boot/grub/grub.cfg

# Configure networking
echo "${hostname}" > /mnt/etc/hostname

cat << EOF > /mnt/etc/systemd/network/virtio-net.network
[Match]
MACAddress=${mac_address}

[Network]
Address=${ip_address}
Gateway=${gateway}
DNS=${dns_server}
EOF
ln -sf /run/systemd/resolve/resolv.conf /mnt/etc/resolv.conf
arch-chroot /mnt systemctl enable systemd-networkd.service systemd-resolved.service sshd.service

# Configure miscellaneous settings
echo "kernel.sysrq = 1" > /mnt/etc/sysctl.d/50-sysrq.conf
useradd -R /mnt -m fsgqa

# Set up the new user account and disable root login.
useradd -R /mnt -m "${user}" -g users
echo "${user}:${hostname}" | chpasswd -R /mnt
echo "${user} ALL=(ALL) NOPASSWD: ALL" > "/mnt/etc/sudoers.d/10-${user}"
passwd -R /mnt -l root
""")
    # TODO: also install vm-modules-mounter
    return ''.join(script)


def interact(master, expect=None):
    sel = selectors.DefaultSelector()
    sel.register(master, selectors.EVENT_READ)
    sel.register(sys.stdin, selectors.EVENT_READ)

    if expect is not None:
        buf = bytearray()

    while True:
        events = sel.select()
        for key, mask in events:
            if key.fileobj == master:
                try:
                    b = master.read(1)
                except OSError as e:
                    if e.errno == errno.EIO:
                        if expect is not None:
                            raise EOFError
                        else:
                            return
                    raise e
                sys.stdout.buffer.write(b)
                sys.stdout.buffer.flush()
                if expect is not None:
                    buf.extend(b)
                    if buf.endswith(expect):
                        return
            else:  # key.fileobj == sys.stdin
                b = os.read(sys.stdin.fileno(), 1)
                master.write(b)


def cmd_archinstall(args):
    args.packages = [
        # Base system
        'base',
        'base-devel',
        'grub',
        'openssh',
        'rsync',
        'sudo',

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

    if not hasattr(args, 'hostname'):
        args.hostname = re.sub(r'[^-a-z0-9]+', '-', args.name.lower()).strip('-')

    if not hasattr(args, 'iso'):
        mirror = args.pacman_mirrors[0].replace('$repo/os/$arch', 'iso/latest')
        args.iso = download_latest_archiso(mirror)

    if not hasattr(args, 'user'):
        args.user = getpass.getuser()
        if args.user == 'root':
            args.user = 'vm'

    proxy_vars = ''.join([
        f'export {name}={os.environ[name]}\n'
        for name in ['http_proxy', 'https_proxy', 'ftp_proxy']
        if name in os.environ])

    os.chdir(os.path.expanduser('~/linux/vm'))
    qemu_args = get_qemu_args(args) + ['-boot', 'd', '-no-reboot', '-cdrom', args.iso]

    pid, fd = pty.fork()
    if pid == 0:
        os.execvp(qemu_args[0], qemu_args)
    old = termios.tcgetattr(sys.stdin.fileno())
    try:
        tty.setraw(sys.stdin.fileno())
        tty.setraw(fd)
        with os.fdopen(fd, 'r+b', buffering=0) as master:
            try:
                interact(master, b'Boot Arch Linux')
                master.write(b'\t console=ttyS0,115200\r')
                interact(master, b'login: ')
                master.write(b'root\r')
                interact(master, b'# ')
                master.write(b'OLD_PS2="$PS2"; PS2=\r')  # Disable the heredoc> prompt.
                master.write(proxy_vars.encode())
                master.write(b'cat > install.sh << "SCRIPTEOF"\r')
                master.write(install_script(args, proxy_vars).encode())
                master.write(b'SCRIPTEOF\r')
                master.write(b'PS2="$OLDPS2"\r')
                master.write(b'chmod +x ./install.sh\r')
                if not args.edit:
                    master.write(b'./install.sh && poweroff\r')
                interact(master)
            except EOFError:
                pass
            except Exception as e:
                os.kill(pid, signal.SIGKILL)
                raise e
    finally:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSAFLUSH, old)
    os.waitpid(pid, 0)


def main():
    parser = argparse.ArgumentParser(
        description='Manage QEMU virtual machines')

    subparsers = parser.add_subparsers(
        title='command', description='command to run', dest='command')
    subparsers.required = True

    parser_create = subparsers.add_parser(
        'create', help='create a new virtual machine',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser_create.add_argument(
        'name', metavar='NAME', help='name of the VM to create')
    parser_create.add_argument(
        '-c', '--cpu', type=str, default='2',
        help='number of CPUs to give the guest (QEMU -smp option)')
    parser_create.add_argument(
        '-m', '--memory', type=str, default='2G',
        help='amount of RAM to give the guest (QEMU -m option)')
    parser_create.add_argument(
        '-s', '--size', type=str, default='16G',
        help="size of the guest's root disk (can use k, M, G, and T suffixes)")
    parser_create.set_defaults(func=cmd_create)

    parser_run = subparsers.add_parser(
        'run', help='run a virtual machine',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser_run.add_argument(
        'name', metavar='NAME', help='name of the VM to run')
    parser_run.add_argument(
        '-k', '--kernel', default=argparse.SUPPRESS,
        help='kernel in ~/linux/builds to run')
    parser_run.add_argument(
        '-i', '--initrd', metavar='FILE', default=argparse.SUPPRESS,
        help='file to use as initial ramdisk (only when passing -k)')
    parser_run.add_argument(
        '-a', '--append', action='append', default=argparse.SUPPRESS,
        help='append a kernel command line argument (only when passing -k)')
    parser_run.add_argument(
        'qemu_options', metavar='QEMU_OPTION', nargs='*',
        help='extra options to pass directly to QEMU')
    parser_run.set_defaults(func=cmd_run)

    parser_archinstall = subparsers.add_parser(
        'archinstall', help='install Arch Linux on a virtual machine',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser_archinstall.add_argument(
        'name', metavar='NAME', help='name of the VM to install')
    parser_archinstall.add_argument(
        '--edit', action='store_true',
        help="don't run the installation script automatically; "
             "use this if you'd like to edit the script before running it")
    parser_archinstall.add_argument(
        '--root-dev', metavar='DEV', default='/dev/vda',
        help='device to partition for root file system and bootloader')
    parser_archinstall.add_argument(
        '--mkfs-cmd', metavar='CMD', default='mkfs.ext4',
        help='command to run on the root device')
    parser_archinstall.add_argument(
        '--pacman-mirrors', metavar='URL', nargs='+',
        default=['https://mirrors.kernel.org/archlinux/$repo/os/$arch'],
        help='mirror list to use for pacman')
    parser_archinstall.add_argument(
        '--locales', metavar='LOCALE', nargs='+', default=['en_US.UTF-8'],
        help='locales to generate; the first one is used as the default')
    parser_archinstall.add_argument(
        '--timezone', metavar='TZ', default='America/Los_Angeles',
        help='time zone to use; see tzselect(8)')
    parser_archinstall.add_argument(
        '--hostname', metavar='NAME', default=argparse.SUPPRESS,
        help='hostname to use for the virtual machine (default: sanitized VM name)')
    parser_archinstall.add_argument(
        '--user', default=argparse.SUPPRESS,
        help='name of user to set up in the VM (default: name of the current user, or "vm" if running as root)')
    parser_archinstall.add_argument(
        '--iso', metavar='ISO', default=argparse.SUPPRESS,
        help='Arch Linux ISO to use (default: download the latest ISO)')
    parser_archinstall.set_defaults(func=cmd_archinstall)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
