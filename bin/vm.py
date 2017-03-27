#!/usr/bin/env python3

import argparse
import os.path
import runpy
import subprocess
import sys

import shlib


def my_input(prompt=None):
    if prompt is not None:
        sys.stderr.write(prompt)
        sys.stderr.flush()
    return input()


def cmd_create(sh, args):
    sh.blank()
    sh.chdir(os.path.expanduser('~/linux/vm'))

    sh.mkdir(args.name)
    if args.size is None:
        args.size = my_input('Size of root disk: ')
    sh.call(['qemu-img', 'create', '-f', 'qcow2', '-o', 'nocow=on',
             f'{args.name}/{args.name}.qcow2', args.size])
    sh.write_file(f'{args.name}/vm.py', f"""\
qemu_options = [
    ('-nodefaults',),
    ('-nographic',),
    ('-serial', 'mon:stdio'),

    ('-cpu', 'kvm64'),
    ('-enable-kvm',),
    ('-smp', {args.cpu!r}),
    ('-m', {args.memory!r}),
    ('-watchdog', 'i6300esb'),

    # Host forwarding can be enabled by adding to the -netdev option:
    # hostfwd=[tcp|udp]:[hostaddr]:hostport-[guestaddr]:guestport
    # e.g., hostfwd=tcp:127.0.0.1:2222-:22
    ('-netdev', 'user,id=vlan0'),
    ('-device', 'virtio-net,netdev=vlan0'),

    ('-drive', 'file={args.name}/{args.name}.qcow2,index=0,media=disk,if=virtio,cache=none'),
]

kernel_cmdline = [
    'root=/dev/vda1',
    'console=ttyS0,115200',
]
""")


def cmd_run(sh, args):
    sh.blank()
    sh.chdir(os.path.expanduser('~/linux/vm'))

    config = runpy.run_path(os.path.join(args.name, 'vm.py'))
    config.setdefault('qemu_options', [])
    config.setdefault('kernel_cmdline', [])

    for option in config['qemu_options']:
        assert all(isinstance(arg, str) for arg in option)

    # Command-line arguments.
    if args.kernel:
        build_path = os.path.expanduser(f'~/linux/builds/{args.kernel}')
        image_name = subprocess.check_output(
            ['make', '-s', 'image_name'], cwd=build_path,
            universal_newlines=True).strip()
        kernel_image_path = os.path.join(build_path, image_name)
        config['qemu_options'].append(('-kernel', kernel_image_path))
        virtfs_opts = [
            'local', f'path={build_path}', 'security_model=none', 'readonly',
            'mount_tag=modules'
        ]
        config['qemu_options'].append(('-virtfs', ','.join(virtfs_opts)))

    if args.initrd:
        config['qemu_options'].append(('-initrd', args.initrd))

    if args.append:
        config['kernel_cmdline'].extend(args.append)

    for option in parse_extra_options(args.qemu_options):
        config['qemu_options'].append(option)

    # Don't use the VM script's default append line if a kernel image was not
    # passed. If it was passed explicitly, let QEMU error out on the user.
    if ((has_option(config['qemu_options'], '-kernel') or args.append) and
        not has_option(config['qemu_options'], '-append')):
        config['qemu_options'].append(('-append', ' '.join(config['kernel_cmdline'])))

    # Convert the options to the actual arguments to execute.
    exec_args = ['qemu-system-x86_64']
    for option in config['qemu_options']:
        exec_args.extend(option)

    sh.exec(exec_args)


def has_option(qemu_options, flag):
    for option in qemu_options:
        if option[0] == flag:
            return True
    return False


def parse_extra_options(extra_options):
    option = None
    for arg in extra_options:
        if arg.startswith('-'):
            if option:
                yield tuple(option)
            option = [arg]
        else:
            option.append(arg)
    if option:
        yield tuple(option)


def main():
    parser = argparse.ArgumentParser(
        description='Manage QEMU virtual machines')
    parser.add_argument(
        '--dry-run', action='store_true',
        help='print the command lines that would be run instead of running them')

    subparsers = parser.add_subparsers(
        title='command', description='command to run', dest='command')
    subparsers.required = True

    parser_create = subparsers.add_parser(
        'create', help='create a new virtual machine')
    parser_create.add_argument(
        'name', metavar='NAME', help='name of the VM to create')
    parser_create.add_argument(
        '-c', '--cpu', type=str, default='1',
        help='number of CPUs to give the guest (QEMU -smp option)')
    parser_create.add_argument(
        '-m', '--memory', type=str, default='1G',
        help='amount of RAM to give the guest (QEMU -m option)')
    parser_create.add_argument(
        '-s', '--size', type=str, default=None,
        help="size of the guest's root disk (can use k, M, G, and T suffixes)")
    parser_create.set_defaults(func=cmd_create)

    parser_run = subparsers.add_parser(
        'run', help='run a virtual machine')
    parser_run.add_argument(
        'name', metavar='NAME', help='name of the VM to run')
    parser_run.add_argument(
        '-k', '--kernel', help='kernel in ~/linux/builds to run')
    parser_run.add_argument(
        '-i', '--initrd', metavar='FILE',
        help='file to use as initial ramdisk (only when passing -k)')
    parser_run.add_argument(
        '-a', '--append', action='append', default=[],
        help='append a kernel command line argument (only when passing -k)')
    parser_run.add_argument(
        'qemu_options', metavar='QEMU_OPTION', nargs='*',
        help='extra options to pass directly to QEMU')
    parser_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    sh = shlib.Shlib(dry_run=args.dry_run)
    args.func(sh, args)


if __name__ == '__main__':
    main()
