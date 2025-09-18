#!/usr/bin/env python3
# SPDX-FileCopyrightText: Omar Sandoval <osandov@osandov.com>
# SPDX-License-Identifier: MIT

import argparse
import configparser
import errno
import fcntl
import os
from pathlib import Path
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
from typing import Any, Dict, List, Optional, Sequence
import urllib.request


def prompt_yes_no(prompt: str, default: bool = True) -> bool:
    prompt += " [Y/n] " if default else " [y/N] "
    sys.stderr.write(prompt)
    sys.stderr.flush()
    answer = input().strip().lower()
    if answer.startswith("y"):
        return True
    elif answer.startswith("n"):
        return False
    else:
        return default


class ScriptConfig:
    def __init__(
        self, *, vms_dir: Path, isos_dir: Path, builds_dir: Optional[Path] = None
    ) -> None:
        self.vms_dir = vms_dir
        self.isos_dir = isos_dir
        self.builds_dir = builds_dir


def get_script_config() -> ScriptConfig:
    config = configparser.ConfigParser()
    config["Paths"] = {"VMs": "~/vms"}
    xdg_config_home = os.getenv("XDG_CONFIG_HOME")
    if xdg_config_home is None:
        config_home = Path("~/.config").expanduser()
    else:
        config_home = Path(xdg_config_home)
    config.read([config_home / "vmpy.conf"])
    paths = {}
    for key, value in config["Paths"].items():
        path = Path(value).expanduser()
        if not path.is_absolute():
            sys.exit(f"{key} must be absolute path")
        paths[key] = path
    return ScriptConfig(
        vms_dir=paths["vms"],
        isos_dir=paths.get("isos", paths["vms"] / "iso"),
        builds_dir=paths.get("builds"),
    )


class VMConfig:
    def __init__(
        self,
        *,
        qemu_arch: str,
        qemu_options: Sequence[str],
        kernel_cmdline: Sequence[str],
    ) -> None:
        self.qemu_arch = qemu_arch
        self.qemu_options = qemu_options
        self.kernel_cmdline = kernel_cmdline

    def qemu_args(
        self,
        *,
        build_path: Optional[Path] = None,
        initrd: Optional[str] = None,
        kernel_cmdline_append: Sequence[str] = (),
        extra_args: Sequence[str] = (),
    ) -> List[str]:
        args = ["qemu-system-" + self.qemu_arch]
        args.extend(self.qemu_options)

        # Command-line arguments.
        if build_path is not None:
            image_name = subprocess.check_output(
                ["make", "-s", "image_name"], cwd=build_path, universal_newlines=True
            ).strip()
            args.extend(("-kernel", str(build_path / image_name)))
            virtfs_opts = [
                "local",
                f"path={build_path}",
                "security_model=none",
                "readonly=on",
                "mount_tag=modules",
            ]
            args.extend(("-virtfs", ",".join(virtfs_opts)))

        if initrd is not None:
            args.extend(("-initrd", initrd))

        args.extend(extra_args)

        # Don't use the VM script's default append line if a kernel image was
        # not passed. If it was passed explicitly, let QEMU error out on the
        # user.
        if ("-kernel" in args or kernel_cmdline_append) and "-append" not in args:
            kernel_cmdline = list(self.kernel_cmdline)
            kernel_cmdline.extend(kernel_cmdline_append)
            args.extend(("-append", " ".join(kernel_cmdline)))

        return args


def parse_vm_config(vm_dir: Path) -> VMConfig:
    config = runpy.run_path(str(vm_dir / "config.py"))
    return VMConfig(
        qemu_arch=config.get("qemu_arch", "x86_64"),
        qemu_options=config.get("qemu_options", []),
        kernel_cmdline=config.get("kernel_cmdline", []),
    )


def cmd_create(args: argparse.Namespace, script_config: ScriptConfig) -> None:
    vm_dir = script_config.vms_dir / args.name
    vm_dir.mkdir(parents=True, exist_ok=True)

    print(f"Creating {args.name!r}, cpu={args.cpu} memory={args.memory}")
    subprocess.run(
        [
            "qemu-img",
            "create",
            "-f",
            "qcow2",
            "-o",
            "nocow=on",
            vm_dir / f"{args.name}.qcow2",
            args.size,
        ],
        check=True,
    )
    with open(vm_dir / "config.py", "w") as f:
        f.write(
            f"""\
qemu_options = [
    '-nodefaults',
    '-display', 'none',
    '-serial', 'mon:stdio',

    '-cpu', 'host',
    '-enable-kvm',
    '-smp', {args.cpu!r},
    '-m', {args.memory!r},
    '-device', 'i6300esb',
    '-device', 'virtio-rng-pci',
    '-device', 'vmcoreinfo',

    # Host forwarding can be enabled by adding to the -netdev option:
    # hostfwd=[tcp|udp]:[hostaddr]:hostport-[guestaddr]:guestport
    # e.g., hostfwd=tcp:127.0.0.1:2222-:22
    '-netdev', 'user,id=vlan0',
    '-device', 'virtio-net,netdev=vlan0',

    '-drive', 'file={args.name}/{args.name}.qcow2,media=disk,cache=none,if=none,id=vda',
    '-device', 'virtio-blk-pci,drive=vda,bootindex=1',
]

kernel_cmdline = [
    'root=/dev/vda1',
    'console=ttyS0,115200',
]
"""
        )


def get_build_path(
    args: argparse.Namespace, script_config: ScriptConfig
) -> Optional[Path]:
    kernel: Optional[str] = getattr(args, "kernel", None)
    if kernel is None:
        return None

    kernel = os.path.expanduser(kernel)
    if not kernel.startswith("/") and not kernel.startswith("."):
        if script_config.builds_dir is not None:
            build_path = script_config.builds_dir / kernel
            if build_path.exists():
                return build_path
    return Path(kernel).resolve()


def cmd_run(args: argparse.Namespace, script_config: ScriptConfig) -> None:
    build_path = get_build_path(args, script_config)
    qemu_args = parse_vm_config(script_config.vms_dir / args.name).qemu_args(
        build_path=build_path,
        initrd=getattr(args, "initrd", None),
        kernel_cmdline_append=getattr(args, "append", ()),
        extra_args=args.qemu_options,
    )
    if args.dry_run:
        print(" ".join(shlex.quote(arg) for arg in qemu_args))
    else:
        os.chdir(script_config.vms_dir)
        os.execvp(qemu_args[0], qemu_args)


def download_latest_archiso(mirror: str, isos_dir: Path) -> Path:
    with urllib.request.urlopen(mirror) as url:
        match = re.search(
            r"archlinux-\d{4}\.\d{2}\.\d{2}-x86_64\.iso", url.read().decode()
        )
        if not match:
            sys.exit(f"Installer ISO not found on {mirror}")
        latest: str = match.group()

    iso_path = isos_dir / latest
    if not iso_path.exists():
        iso_url = mirror + "/" + latest
        if not prompt_yes_no(f"Download {iso_url} to {isos_dir}?"):
            sys.exit(
                "Use --iso if you have a previously downloaded ISO you want to use"
            )
        isos_dir.mkdir(parents=True, exist_ok=True)
        iso_part = isos_dir / (latest + ".part")
        subprocess.run(
            ["curl", "-L", "-C", "-", "-f", "-o", iso_part, iso_url],
            check=True,
        )
        # TODO: check checksum
        iso_part.rename(iso_path)
    return iso_path


def install_script(args: argparse.Namespace, proxy_vars: str) -> str:
    script = [
        r"""#!/bin/bash

set -eux
"""
    ]
    script.append(
        f"""
export root_dev={shlex.quote(args.root_dev)}
export root_part="${{root_dev}}1"
export mkfs_cmd={shlex.quote(args.mkfs_cmd)}
export locale={shlex.quote(args.locales[0])}
export locales={shlex.quote('|'.join([re.escape(locale) for locale in args.locales]))}
export timezone={shlex.quote(args.timezone)}
export hostname={shlex.quote(args.hostname)}
export user={shlex.quote(args.user)}
mirrors=({' '.join(shlex.quote(mirror) for mirror in args.pacman_mirrors)})
packages=({' '.join(shlex.quote(package) for package in args.packages)})
"""
    )
    script.append(
        r"""
# We want IPv6 Router Advertisement enabled even if the ISO disabled it
if [[ -d /etc/systemd/network ]]; then
	find /etc/systemd/network -name '*.network' \
		-exec sed -i '/^IPv6AcceptRA/d' {} \;
fi

# It'd be nice if we could use networkctl reload instead, but that doesn't wait
# for the configuration to be reloaded and applied
systemctl restart systemd-networkd.service
systemctl restart systemd-networkd-wait-online.service

# We need pacman-init.service to populate the pacman keyring, but it is
# configured to run after time-sync.target. If we're behind a firewall, this
# will never succeed. But, QEMU should have set the clock correctly, so we can
# bypass systemd-time-wait-sync.service by touching this file.
touch /run/systemd/timesync/synchronized
systemctl start pacman-init.service

export gateway="$(ip route show default | gawk 'match($0, /^\s*default.*via\s+([0-9.]+)/, a) { print a[1]; exit }')"
[[ -z $gateway ]] && { echo "Could not find gateway" >&2; exit 1; }

export nic="$(ip route show default | gawk 'match($0, /^\s*default.*dev\s+(\S+)/, a) { print a[1]; exit }')"
[[ -z $nic ]] && { echo "Could not find network interface" >&2; exit 1; }

export ip_address="$(ip addr show dev "$nic" | gawk 'match($0, /^\s*inet\s+([0-9.]+\/[0-9]+)/, a) { print a[1]; exit }')"
[[ -z $ip_address ]] && { echo "Could not find IP address" >&2; exit 1; }

export mac_address="$(ip addr show dev "$nic" | gawk 'match($0, /^\s*link\/ether\s+([0-9A-Fa-f:]+)/, a) { print a[1]; exit }')"
[[ -z $mac_address ]] && { echo "Could not find MAC address" >&2; exit 1; }

export dns_server="$(resolvectl dns "$nic" | gawk '$4 ~ /[0-9.]+/ { print $4; exit }')"
[[ -z $dns_server ]] && { echo "Could not find DNS server" >&2; exit 1; }

# Prepare storage devices
wipefs -a "${root_dev}"
parted "${root_dev}" --align optimal --script mklabel msdos mkpart primary 0% 100%
${mkfs_cmd} "${root_part}"
mount "${root_part}" /mnt

# Install packages
# dirmngr doesn't use http_proxy by default. Additionally, its built-in DNS
# resolver doesn't seem to play nicely with QEMU.
mkdir -p /etc/gnupg /etc/pacman.d/gnupg
cat << "EOF" > /etc/gnupg/dirmngr.conf
honor-http-proxy
standard-resolver
EOF
mkdir -p /mnt/etc/gnupg
cp /etc/gnupg/dirmngr.conf /mnt/etc/gnupg/dirmngr.conf
# pacstrap will copy the entire /etc/pacman.d/gnupg directory to the chroot.
cp /etc/gnupg/dirmngr.conf /etc/pacman.d/gnupg/dirmngr.conf
# This will be copied to the installed system by pacstrap
: > /etc/pacman.d/mirrorlist
for mirror in "${mirrors[@]}"; do
	echo "Server = ${mirror}" >> /etc/pacman.d/mirrorlist
done

# For some unknown reason, pacstrap sometimes fails to resolve any hostnames;
# resolving something beforehand seems to kick something in the stack so that
# it works
host aur.archlinux.org > /dev/null

pacstrap /mnt "${packages[@]}"
genfstab -U /mnt >> /mnt/etc/fstab

# arch-chroot bind mounts over /etc/resolv.conf, so we have to do this from
# outside of the chroot.
ln -sf /run/systemd/resolve/resolv.conf /mnt/etc/resolv.conf

arch-chroot /mnt bash -s << "ARCHCHROOTEOF"
set -eux
"""
    )
    if proxy_vars:
        script.append(
            f"""
# Configure proxy
cat << "EOF" > /etc/profile.d/proxy.sh
{proxy_vars}EOF
chmod +x /etc/profile.d/proxy.sh
"""
        )
    script.append(
        r"""
# Configure locale
sed -r -i "s/^#(${locales}) /\\1 /" /etc/locale.gen
echo "LANG=${locale}" > /etc/locale.conf
locale-gen

# Configure time
ln -sf /usr/share/zoneinfo/"${timezone}" /etc/localtime
hwclock --systohc --utc

# Install bootloader
grub-install --target=i386-pc "${root_dev}"
cat << "EOF" > /etc/default/grub
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
grub-mkconfig -o /boot/grub/grub.cfg

# Configure networking
echo "${hostname}" > /etc/hostname

cat << EOF > /etc/systemd/network/virtio-net.network
[Match]
MACAddress=${mac_address}

[Network]
Address=${ip_address}
Gateway=${gateway}
DNS=${dns_server}
EOF

# Configure miscellaneous settings
echo "kernel.sysrq = 1" > /etc/sysctl.d/50-sysrq.conf
useradd -m fsgqa

# Set up the new user account.
useradd -m "${user}" -g users
echo "${user}:${user}" | chpasswd

# Allow the new user to run sudo without a password.
echo "${user} ALL=(ALL) NOPASSWD: ALL" > "/etc/sudoers.d/10-${user}"
echo 'Defaults env_keep += "http_proxy https_proxy ftp_proxy"' > /etc/sudoers.d/10-keep-proxy

# Allow the new user to run Polkit actions without sudo.
cat << EOF > "/etc/polkit-1/rules.d/10-${user}.rules"
polkit.addRule(function(action, subject) {
    if (subject.user == "${user}") {
        return polkit.Result.YES;
    }
});
EOF

# Enable autologin on the console for the new user.
mkdir -p /etc/systemd/system/serial-getty@ttyS0.service.d
cat << EOF > /etc/systemd/system/serial-getty@ttyS0.service.d/autologin.conf
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $(systemd-escape "$user") -o '-p -f -- \\\\u' --keep-baud 115200,38400,9600 %I \$TERM
EOF

# Disable root login.
passwd -l root

# Install vm-modules-mounter.
curl -o /etc/systemd/system/vm-modules-mounter.service https://raw.githubusercontent.com/osandov/osandov-linux/master/scripts/vm-modules-mounter.service

# Install pacaur.
sudo -u "${user}" bash -l << "SUDOEOF"
set -eux
cd /tmp
curl -O https://aur.archlinux.org/cgit/aur.git/snapshot/aurman.tar.gz
tar -xf aurman.tar.gz
cd aurman
makepkg -si --noconfirm --skippgpcheck
SUDOEOF
ARCHCHROOTEOF

# systemctl can't communicate with D-Bus in the chroot.
systemctl enable --root /mnt systemd-networkd.service systemd-resolved.service sshd.service vm-modules-mounter.service
"""
    )
    return "".join(script)


class MiniExpect:
    def __init__(self, args: List[str]) -> None:
        self.pid, self.master = pty.fork()
        if self.pid == 0:
            os.execvp(args[0], args)
        tty.setraw(self.master)
        flags = fcntl.fcntl(self.master, fcntl.F_GETFD)
        fcntl.fcntl(self.master, fcntl.F_SETFD, flags | os.O_NONBLOCK)
        self._buf = bytearray()
        self._sel = selectors.DefaultSelector()
        self._sel.register(self.master, selectors.EVENT_READ)
        self._sel.register(sys.stdin, selectors.EVENT_READ)

    def __enter__(self) -> "MiniExpect":
        self.old_attr = termios.tcgetattr(sys.stdin.fileno())
        self.old_flags = fcntl.fcntl(sys.stdin.fileno(), fcntl.F_GETFD)
        fcntl.fcntl(sys.stdin.fileno(), fcntl.F_SETFD, self.old_flags | os.O_NONBLOCK)
        tty.setraw(sys.stdin.fileno())
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSAFLUSH, self.old_attr)
        fcntl.fcntl(sys.stdin.fileno(), fcntl.F_SETFD, self.old_flags)
        os.close(self.master)
        os.waitpid(self.pid, 0)

    def interact(
        self,
        *,
        expect: Optional[bytes] = None,
        write: Optional[bytes] = None,
        until_eof: bool = False,
    ) -> None:
        if write:
            writebuf = bytearray(write)
            self._sel.modify(self.master, selectors.EVENT_READ | selectors.EVENT_WRITE)
        else:
            writebuf = bytearray()
            self._sel.modify(self.master, selectors.EVENT_READ)
        found_expect = not expect
        while until_eof or writebuf or not found_expect:
            events = self._sel.select()
            for key, mask in events:
                if key.fileobj == self.master:
                    if mask & selectors.EVENT_READ:
                        try:
                            read = os.read(self.master, 4096)
                        except OSError as e:
                            if e.errno == errno.EIO:
                                raise EOFError
                            raise e
                        sys.stdout.buffer.write(read)
                        sys.stdout.buffer.flush()
                        self._buf.extend(read)
                        if not found_expect:
                            found_expect = expect in self._buf  # type: ignore[operator]
                        if len(self._buf) >= 8192:
                            del self._buf[:-4096]
                    if mask & selectors.EVENT_WRITE:
                        written = os.write(self.master, writebuf)
                        del writebuf[:written]
                        if not writebuf:
                            self._sel.modify(self.master, selectors.EVENT_READ)
                else:  # key.fileobj == sys.stdin and mask == selectors.EVENT_READ
                    read = os.read(sys.stdin.fileno(), 4096)
                    writebuf.extend(read)
                    self._sel.modify(
                        self.master, selectors.EVENT_READ | selectors.EVENT_WRITE
                    )


def cmd_archinstall(args: argparse.Namespace, script_config: ScriptConfig) -> None:
    args.packages = [
        # Base system
        "base",
        "grub",
        "inetutils",
        "linux",
        "openssh",
        "polkit",
        "sudo",
        # Utilities
        "rsync",
        # Development
        "asciidoc",
        "base-devel",
        "cscope",
        "gdb",
        "git",
        "ltrace",
        "perf",
        "python",
        "strace",
        "vim",
        # xfstests
        "attr",
        "bc",
        "fio",
        "libaio",
        "psmisc",
        "xfsprogs",
    ]

    if not hasattr(args, "hostname"):
        args.hostname = re.sub(r"[^-a-z0-9]+", "-", args.name.lower()).strip("-")

    if hasattr(args, "iso"):
        iso = Path(args.iso)
    else:
        iso = download_latest_archiso(
            args.pacman_mirrors[0].replace("$repo/os/$arch", "iso/latest"),
            script_config.isos_dir,
        )

    proxy_vars = "".join(
        [
            f"export {name}={os.environ[name]}\r"
            for name in ["http_proxy", "https_proxy", "ftp_proxy"]
            if name in os.environ
        ]
    )

    qemu_args = parse_vm_config(script_config.vms_dir / args.name).qemu_args(
        extra_args=[
            "-drive",
            f"file={iso.resolve()},format=raw,media=cdrom,readonly,if=none,id=cdrom",
            "-device",
            "ide-cd,drive=cdrom,bootindex=0",
            "-no-reboot",
        ]
    )

    os.chdir(script_config.vms_dir)
    with MiniExpect(qemu_args) as proc:
        try:
            proc.interact(expect=b"Arch Linux install medium")
            proc.interact(write=b"\t console=ttyS0,115200\r")
            proc.interact(expect=b"login: ")
            proc.interact(write=b"root\r")
            proc.interact(expect=b"# ")
            # This grmlzsh feature breaks heredocs containing some commands
            # (like git).
            proc.interact(write=b"zstyle ':acceptline:default' nocompwarn true\r")
            # Disable the heredoc> prompt.
            proc.interact(write=b'OLD_PS2="$PS2"; PS2=\r')
            proc.interact(write=proxy_vars.encode())
            proc.interact(write=b'cat > install.sh << "INSTALLSHEOF"\r')
            proc.interact(
                write=install_script(args, proxy_vars).replace("\n", "\r").encode()
            )
            proc.interact(write=b"INSTALLSHEOF\r")
            proc.interact(write=b'PS2="$OLDPS2"\r')
            proc.interact(write=b"chmod +x ./install.sh\r")
            if not args.edit:
                proc.interact(write=b"./install.sh && poweroff\r")
            proc.interact(until_eof=True)
        except EOFError:
            pass
        except Exception as e:
            os.kill(proc.pid, signal.SIGKILL)
            raise e


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage QEMU virtual machines")

    subparsers = parser.add_subparsers(
        title="command", description="command to run", dest="command"
    )
    subparsers.required = True

    parser_create = subparsers.add_parser(
        "create",
        help="create a new virtual machine",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser_create.add_argument("name", metavar="NAME", help="name of the VM to create")
    parser_create.add_argument(
        "-c",
        "--cpu",
        type=str,
        default="2",
        help="number of CPUs to give the guest (QEMU -smp option)",
    )
    parser_create.add_argument(
        "-m",
        "--memory",
        type=str,
        default="2G",
        help="amount of RAM to give the guest (QEMU -m option)",
    )
    parser_create.add_argument(
        "-s",
        "--size",
        type=str,
        default="16G",
        help="size of the guest's root disk (can use k, M, G, and T suffixes)",
    )
    parser_create.set_defaults(func=cmd_create)

    parser_run = subparsers.add_parser(
        "run",
        help="run a virtual machine",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser_run.add_argument("name", metavar="NAME", help="name of the VM to run")
    parser_run.add_argument(
        "-k",
        "--kernel",
        default=argparse.SUPPRESS,
        help="directory containing kernel build to run; "
        "either a directory in the builds directory, "
        "an absolute path, "
        "or a path relative to the current directory",
    )
    parser_run.add_argument(
        "-i",
        "--initrd",
        metavar="FILE",
        default=argparse.SUPPRESS,
        help="file to use as initial ramdisk (only when passing -k)",
    )
    parser_run.add_argument(
        "-a",
        "--append",
        action="append",
        default=argparse.SUPPRESS,
        help="append a kernel command line argument (only when passing -k)",
    )
    parser_run.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="print QEMU command line instead of running",
    )
    parser_run.add_argument(
        "qemu_options",
        metavar="QEMU_OPTION",
        nargs="*",
        help="extra options to pass directly to QEMU",
    )
    parser_run.set_defaults(func=cmd_run)

    parser_archinstall = subparsers.add_parser(
        "archinstall",
        help="install Arch Linux on a virtual machine",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser_archinstall.add_argument(
        "name", metavar="NAME", help="name of the VM to install"
    )
    parser_archinstall.add_argument(
        "-e",
        "--edit",
        action="store_true",
        help="don't run the installation script automatically; "
        "use this if you'd like to edit the script before running it",
    )
    parser_archinstall.add_argument(
        "--root-dev",
        metavar="DEV",
        default="/dev/vda",
        help="device to partition for root file system and bootloader",
    )
    parser_archinstall.add_argument(
        "--mkfs-cmd",
        metavar="CMD",
        default="mkfs.ext4",
        help="command to run on the root device",
    )
    parser_archinstall.add_argument(
        "--pacman-mirrors",
        metavar="URL",
        nargs="+",
        default=["https://mirrors.kernel.org/archlinux/$repo/os/$arch"],
        help="mirror list to use for pacman",
    )
    parser_archinstall.add_argument(
        "--locales",
        metavar="LOCALE",
        nargs="+",
        default=["en_US.UTF-8"],
        help="locales to generate; the first one is used as the default",
    )
    parser_archinstall.add_argument(
        "--timezone",
        metavar="TZ",
        default="America/Los_Angeles",
        help="time zone to use; see tzselect(8)",
    )
    parser_archinstall.add_argument(
        "--hostname",
        metavar="NAME",
        default=argparse.SUPPRESS,
        help="hostname to use for the virtual machine (default: sanitized VM name)",
    )
    parser_archinstall.add_argument(
        "--user", default="vmuser", help="name of user to set up in the VM"
    )
    parser_archinstall.add_argument(
        "--iso",
        metavar="ISO",
        default=argparse.SUPPRESS,
        help="Arch Linux ISO to use (default: download the latest ISO)",
    )
    parser_archinstall.set_defaults(func=cmd_archinstall)

    args = parser.parse_args()
    args.func(args, get_script_config())


if __name__ == "__main__":
    main()
