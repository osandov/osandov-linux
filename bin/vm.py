#!/usr/bin/env python3

import argparse
from collections import OrderedDict
import os
import os.path
import pprint
import subprocess


def main():
    parser = argparse.ArgumentParser(
        usage='usage: vm.py [OPTIONS] VM -- [QEMU_OPTION [QEMU_OPTION ...]]',
        description='Run a virtual machine with QEMU over KVM')
    parser.add_argument('vm', metavar='VM', help='name of the VM to run')
    parser.add_argument(
        'qemu_options', metavar='QEMU_OPTION', nargs='*',
        help='extra options to pass directly to QEMU')
    parser.add_argument('-k', '--kernel', help='kernel in ~/linux/builds to run')
    parser.add_argument(
        '-a', '--append', action='append', default=[],
        help='append a command line argument for the kernel when passing -k')
    args = parser.parse_args()

    try:
        run_vm(args)
    except VMError as e:
        exit(e)


class VMError(Exception):
    pass


def run_vm(args):
    os.chdir(os.path.expanduser('~/linux/vm'))

    if not os.path.isdir(args.vm):
        raise VMError('No VM named {}'.format(args.vm))

    # Default arguments.
    qemu_options = [
        ('-cpu', 'kvm64'),
        ('-enable-kvm',),
        ('-nographic',),
        ('-m', '1G'),
        ('-smp', '1'),
        ('-watchdog', 'i6300esb'),
        ('-drive', 'file={0}/{0}.qcow2,index=0,media=disk,if=virtio'.format(args.vm)),
    ]

    # Per-VM arguments.
    try:
        vm_script_path = '{}/vm.py'.format(args.vm)
        with open(vm_script_path, 'r') as f:
            code = compile(f.read(), vm_script_path, 'exec')
            exec(code, globals(), locals())
    except FileNotFoundError:
        pass

    # Command-line arguments.
    if args.kernel:
        build_path = os.path.expanduser('~/linux/builds/{}'.format(args.kernel))
        image_name = subprocess.check_output(['make', '-s', 'image_name'], cwd=build_path)
        image_name = image_name.decode('utf-8').strip()
        kernel_image_path = os.path.join(build_path, image_name)
        add_option(qemu_options, '-kernel', kernel_image_path)

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

    returncode = subprocess.call(exec_args)
    if returncode:
        raise VMError('QEMU returned {}'.format(returncode))


REPEATABLE_OPTIONS = {
    '-drive'
}


def add_option(qemu_options, flag, *args):
    assert isinstance(flag, str)
    for arg in args:
        assert isinstance(arg, str)

    if flag not in REPEATABLE_OPTIONS:
        pop_option(qemu_options, flag)
    qemu_options.append((flag,) + args)


def append_to_cmdline(qemu_options, arg):
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
