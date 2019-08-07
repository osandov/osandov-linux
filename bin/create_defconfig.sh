#!/bin/sh

# Create a stripped-down defconfig based on the running system. The idea is
# that the defconfig should only contain the system configuration options like
# preempt, hz, etc. Modules and more niche settings are provided in other
# config files.

# Start with a config based on the running system with a few tweaks.
zcat -f "${1:-/proc/config.gz}" |
	grep -v -E 'CONFIG_(BLK_DEV_NVME|DEFAULT_HOSTNAME|HYPERVISOR_GUEST|LEDS_CLASS|LOCALVERSION|NVM|NVME_CORE|USB|VFIO)=' > .config
cat << EOF >> .config
CONFIG_LOCALVERSION_AUTO=y
CONFIG_IKCONFIG=y
CONFIG_IKCONFIG_PROC=y
CONFIG_KALLSYMS=y
CONFIG_KALLSYMS_ALL=y
CONFIG_MODULE_SIG=n
CONFIG_MODVERSIONS=n
CONFIG_CONSOLE_LOGLEVEL_DEFAULT=7
CONFIG_HID=n
EOF
make olddefconfig

# Disable all modules. If any are built in in the original config, they won't
# be disabled, but Arch doesn't do that for many modules.
lsmod | head -1 > lsmod
make LSMOD=lsmod localmodconfig
make savedefconfig
rm -f lsmod
