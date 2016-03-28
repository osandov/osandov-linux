# My `~/linux` infrastructure

This is a collection of scripts and notes that I use for Linux kernel
development.

## `vm.py`

`vm.py` is my bare-bones wrapper script around QEMU for managing virtual
machines. Virtual machines are created under `~/linux/vm`; each virtual machine
has a `vm.py` "configuration file" which is actually just a Python script. Run
`vm.py -h` for a list of commands. The `--dry-run` flag is particularly useful:
it outputs the shell commands equivalent to what `vm.py` would do for any given
command line.
