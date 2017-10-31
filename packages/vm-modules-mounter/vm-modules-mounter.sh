#!/bin/sh

set -e

KERNELRELEASE="$(uname -r)"

# First, clean up empty modules directories.
find /lib/modules -mindepth 1 -maxdepth 1 -type d -empty -delete

# Check if the 9p modules mount is available.
if ! grep -Fxq modules /sys/bus/virtio/drivers/9pnet_virtio/virtio*/mount_tag 2>/dev/null; then
	echo "9p modules mount is not available" >&2
	# Only error out if modules are not already installed,
	if [ -e "/lib/modules/${KERNELRELEASE}/kernel" ]; then
		echo "Modules are already installed" >&2
		exit 0
	else
		exit 1
	fi
fi

# The only persistent thing we create is the /lib/modules/$(uname -r)
# directory. This is used as a mountpoint for a tmpfs containing everything
# else.
if [ ! -d "/lib/modules/${KERNELRELEASE}" ]; then
	mkdir "/lib/modules/${KERNELRELEASE}"
fi
mount -t tmpfs -o mode=755,strictatime tmpfs "/lib/modules/${KERNELRELEASE}"

# Mount the build tree over 9p.
mkdir "/lib/modules/${KERNELRELEASE}/build"
mount -t 9p -o trans=virtio,ro modules "/lib/modules/${KERNELRELEASE}/build"

# Set up all of the necessary modules files which are normally created when the
# kernel is installed.
ln -s build/modules.order "/lib/modules/${KERNELRELEASE}/modules.order"
ln -s build/modules.builtin "/lib/modules/${KERNELRELEASE}/modules.builtin"
ln -s build "/lib/modules/${KERNELRELEASE}/kernel"
depmod "${KERNELRELEASE}"
