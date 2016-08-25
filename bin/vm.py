#!/usr/bin/env python3

import argparse
import os.path
import subprocess
import sys

import shlib


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
             '{0}/{0}.qcow2'.format(args.name), args.size])
    sh.write_file('{}/vm.py'.format(args.name), """\
add_option(qemu_options, '-nodefaults')
add_option(qemu_options, '-nographic')
add_option(qemu_options, '-serial', 'mon:stdio')

add_option(qemu_options, '-cpu', 'kvm64')
add_option(qemu_options, '-enable-kvm')
add_option(qemu_options, '-smp', {cpu!r}),
add_option(qemu_options, '-m', {memory!r}),
add_option(qemu_options, '-watchdog', 'i6300esb'),
add_option(qemu_options, '-drive', 'file={name}/{name}.qcow2,index=0,media=disk,if=virtio,cache=none')
add_option(qemu_options, '-netdev', 'user,id=vlan0')
add_option(qemu_options, '-device', 'virtio-net,netdev=vlan0')

append_to_cmdline(qemu_options, 'root=/dev/vda1')
append_to_cmdline(qemu_options, 'console=ttyS0,115200')
""".format(name=args.name, cpu=args.cpu, memory=args.memory))


def cmd_run(sh, args):
    sh.blank()
    sh.chdir(os.path.expanduser('~/linux/vm'))

    qemu_options = []
    vm_script_path = '{}/vm.py'.format(args.name)
    with open(vm_script_path, 'r') as f:
        code = compile(f.read(), vm_script_path, 'exec')
        exec(code, globals(), locals())

    # Command-line arguments.
    if args.kernel:
        build_path = os.path.expanduser('~/linux/builds/{}'.format(args.kernel))
        image_name = subprocess.check_output(['make', '-s', 'image_name'], cwd=build_path)
        image_name = image_name.decode('utf-8').strip()
        kernel_image_path = os.path.join(build_path, image_name)
        replace_option(qemu_options, '-kernel', kernel_image_path)
        virtfs_opts = [
            'local', 'path={}'.format(build_path), 'security_model=none',
            'readonly', 'mount_tag=modules'
        ]
        add_option(qemu_options, '-virtfs', ','.join(virtfs_opts))

    if args.initrd:
        add_option(qemu_options, '-initrd', args.initrd)

    explicit_append = False

    for append_arg in args.append:
        explicit_append = True
        append_to_cmdline(qemu_options, append_arg)

    for option in parse_extra_options(args.qemu_options):
        if option[0] == '-append':
            explicit_append = True
        add_option(qemu_options, *option)

    # Don't use the VM script's default append line if a kernel image was not
    # passed. If it was passed explicitly, let QEMU error out on the user.
    if not explicit_append and not has_option(qemu_options, '-kernel'):
        pop_option(qemu_options, '-append')

    # Convert the options to the actual arguments to execute.
    exec_args = ['qemu-system-x86_64']
    for option in qemu_options:
        exec_args.extend(option)

    sh.exec(exec_args)


def add_option(qemu_options, flag, *args):
    # TODO: do the right thing (append or replace) for any flag
    append_option(qemu_options, flag, *args)


def append_option(qemu_options, flag, *args):
    assert isinstance(flag, str)
    for arg in args:
        assert isinstance(arg, str)

    qemu_options.append((flag,) + args)


def replace_option(qemu_options, flag, *args):
    assert isinstance(flag, str)
    for arg in args:
        assert isinstance(arg, str)

    pop_option(qemu_options, flag)
    qemu_options.append((flag,) + args)


def append_to_cmdline(qemu_options, arg):
    assert isinstance(arg, str)
    # TODO: quoting?
    old_options = pop_option(qemu_options, '-append')
    if old_options is None:
        append_args = arg
    else:
        append_args = '{} {}'.format(old_options[1], arg)
    qemu_options.append(('-append', append_args))


def has_option(qemu_options, flag):
    for option in qemu_options:
        if option[0] == flag:
            return True
    return False


def pop_option(qemu_options, flag):
    for i, option in enumerate(qemu_options):
        if option[0] == flag:
            return qemu_options.pop(i)


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


if __name__ == '__main__':
    main()
