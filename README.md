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
something like libvirt but is much simpler. The `--dry-run` flag outputs the
shell commands equiivalent to what `vm.py` would do for any given command line.

VMs live in `~/linux/vm`. Each VM has its own directory containing all of its
disk images and its configuration file.

`vm.py create` creates a new VM under `~/linux/vm`. A few basic configuration
options (CPUs, memory, disk size) can be given. The new VM only has a
virtio-net NIC, a (blank) virtio-blk root disk, and a serial console.

The configuration file for each VM is named `vm.py`. It's a Python script which
must define a `qemu_options` list and `kernel_cmdline` list.

`vm.py run` runs a VM. Arbitrary QEMU options may be added to those in the
configuration. The killer feature, however, is the `-k` option: this runs the
VM with a kernel from the host machine.

### Running Kernel Builds

Running a custom kernel build on a VM usually requires installing that kernel
on the VM. This is wasteful and slow. Instead, I use a combination of QEMU's
`-kernel` option and VirtFS to allow booting a kernel straight off of the host
system.

QEMU's `-kernel` option boots the VM straight into a kernel image. This,
however, doesn't handle kernel modules. For that, `vm.py` provides a VirtFS to
the guest containing the modules. The guest mounts this while booting
(implemented with a systemd generator in `packages/vm-modules-mounter`).

### `setup_arch_vm.py`

The above components don't depend on any particular distro (althought
vm-modules-mounter does depend on systemd), but I use Arch Linux. Installing a
new VM is tedious, so I have another script to do the installation after
booting the Arch Linux ISO. It assumes a VM created with `vm.py create`. This
script also takes a `--dry-run` parameter, in which case it will output a shell
script that can be run directly.

### Full Installation Workflow

On the host, run

```
$ vm.py create -c "$(nproc)" -m 2G -s 16G TestVM
$ vm.py run TestVM -- -boot d ~/Downloads/archlinux-2017.03.01-dual.iso -no-reboot
```

Press tab on the `Boot Arch Linux` menu option to edit the kernel command line
and add `console=ttyS0`. Log in as `root` and run

```
# git clone https://github.com/osandov/osandov-linux.git
# cd osandov-linux
# ./bin/setup_arch_vm.py --hostname testvm
```

Alternatively, on the host, run

```
$ setup_arch_vm.py --dry-run --hostname testvm
```

and copy and run the output on the VM.

Enter a root password when prompted and then run `poweroff`.

Boot up the VM.

```
$ vm.py run TestVM
```

Build the VM module support package on the host

```
$ cd ~/linux/osandov-linux/packages/vm-modules-mounter
$ makepkg
```

and copy the package to the VM. Install it with `pacman -U`. (This step will
likely be automated by `setup_arch_vm.py` in the future.)

Now you can boot into kernels with `vm.py run -k`. Note that there are a few
required kernel configuration options; see `configs/qemu.fragment`.
