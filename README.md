# My `~/linux` infrastructure

This is a collection of scripts and notes that I use for Linux kernel
development.

## Top-level directories

- `bin`: scripts that I add to my `$PATH`
- `configs`: kernel configs
- `modules`: experimental/testing kernel modules
- `notes`: various development notes
- `packages`: Arch Linux packages used for development
- `scripts`: tests, bug reproducers, and other one-off scripts

## VM Setup

I use QEMU for kernel development. My setup allows for running kernels straight
off of the host system without installing onto the guest, which makes for a
super fast edit-compile-test cycle.

### `vm.py`

`vm.py` is my VM management script. It fills a role similar to that of
something like libvirt but is much simpler.

VMs live in `~/linux/vm`. Each VM has its own directory containing all of its
disk images and its configuration file.

`vm.py create` creates a new VM under `~/linux/vm`. A few basic configuration
options (CPUs, memory, disk size) can be given. The new VM only has a
virtio-net NIC, a (blank) virtio-blk root disk, and a serial console.

The configuration file for each VM is named `config.py`. It's a Python script
which must define a `qemu_options` list and `kernel_cmdline` list.

`vm.py run` runs a VM. Arbitrary QEMU options may be added to those in the
configuration. The killer feature, however, is the `-k` option: this runs the
VM with a kernel from the host machine.

`vm.py archinstall` installs and configures Arch Linux on a new VM. It
automatically downloads the latest Arch Linux ISO and runs an automated setup
process. If there is an error during this process, you will be dropped into a
shell on the VM. If this happens, you can edit `install.sh` on the VM and try
again manually (but please also open an issue on GitHub so I can fix it). If
the installation process succeeds, the VM will power off, after which you can
restart it with `vm.py run`. The default username is `vmuser`, and the default
password is the hostname of the virtual machine (which is shown at the login
prompt).

### Running Custom Kernel Builds

Running a custom kernel build on a VM usually requires installing that kernel
on the VM. This is wasteful and slow. Instead, I use a combination of QEMU's
`-kernel` option and VirtFS to allow booting a kernel straight off of the host
system.

QEMU's `-kernel` option boots the VM straight into a kernel image. This,
however, doesn't handle kernel modules. For that, `vm.py` provides a VirtFS to
the guest containing the modules, which the guest mounts while booting (see
`scripts/vm-modules-mounter.service`). `vm.py archinstall` automatically
installs `vm-modules-mounter`. You can install it manually by copying
`vm-modules-mounter.service` to `/etc/systemd/system` and running `systemctl
enable vm-modules-mounter.service`.

Note that this setup requires a few kernel configuration options; see
`configs/qemu.fragment`.
