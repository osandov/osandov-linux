#!/bin/sh

set -e

usage () {
	USAGE_STRING="usage: $0 [-h] [PROG]...

Unmount the root filesystem and drop into a tmpfs

Arguments:
  PROG    executable to copy into the tmpfs, along with any libraries it
	  depends on, either as a path or a basename (e.g., fsck.ext4 or btrfs)

Miscellaneous:
  -h    display this help message and exit"

	case "$1" in
		out)
			echo "$USAGE_STRING"
			exit 0
			;;
		err)
			echo "$USAGE_STRING" >&2
			exit 1
			;;
	esac
}

while getopts "h" OPT; do
	case "$OPT" in
		h)
			usage "out"
			;;
		*)
			usage "err"
			;;
	esac
done

# This will be our chroot
mkdir -p /newroot
mount -t tmpfs tmpfs /newroot
cd /newroot

# Populate the chroot with busybox and any requested executables.
mkdir -p usr/bin usr/lib
ln -s usr/bin bin
ln -s usr/lib lib
ln -s usr/lib lib64
cp "$(which busybox)" usr/bin
./usr/bin/busybox --install ./usr/bin

while [ $# -gt 0 ]; do
	path="$(which "$1")"
	cp "$path" usr/bin
	ldd "$path" | awk '$1 ~ /^\// { print $1 } $3 ~ /^\// { print $3 }' | while read -r lib; do
		cp "$lib" usr/lib
	done
	shift
done

cat << "EOF" > kill_systemd.sh
#!/bin/sh

mkdir dev proc run sys
# Need these for basic sanity.
mount -o move /oldroot/dev /dev
mount -o move /oldroot/proc /proc
mount -o move /oldroot/sys /sys
# systemd will ignore SIGTERM if it can't find /run/systemd.
mount -o move /oldroot/run /run

# Tell systemd to reexec itself, which will actually execute the script we put
# in /sbin/init as PID 1.
exec kill -TERM 1
EOF
chmod +x kill_systemd.sh

mkdir sbin
cat << "EOF" > sbin/init
#!/bin/sh

# Kill everything but PID 1.
echo i > /proc/sysrq-trigger

# Unmount /oldroot and everything underneath it. If busybox supported umount -R
# (recursive), we'd use that, but it doesn't, so we let the kernel do it
# lazily.
umount -l /oldroot

# Drop into a shell.
exec /bin/sh
EOF
chmod +x sbin/init

# pivot_root(2) fails if anything is shared
mount --make-rprivate /
mkdir oldroot
pivot_root . oldroot
exec chroot . /kill_systemd.sh
