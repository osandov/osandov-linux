#!/bin/sh

cat << "EOF" |
btrfs/010 # snapshot-aware defrag is disabled in the kernel
btrfs/012 # expects /lib/modules/$(uname -r) to exist
btrfs/017 # qgroups
btrfs/022 # qgroups
btrfs/057 # qgroups
btrfs/091 # qgroups
generic/015 # not sure why, but the list seems to acknowledge it
generic/092 # fallocate+truncate, not sure when this is fixed
generic/224 # OOMs

# Fixed in 4.2
btrfs/087 # incremental send, fixed in rc1
btrfs/089 # premature subvol unmount, fixed in rc1
btrfs/092 # incremental send, fixed in rc1
btrfs/094 # incremental send, fixed in rc1
btrfs/096 # clone inline extent into non-zero offset, fixed in rc3
generic/090 # fsync, fixed in rc2
generic/094 # fiemap UNWRITTEN, fixed in rc1
generic/098 # truncate+no_holes, fixed in rc3
generic/101 # fsync, fixed in rc2
shared/002 # fsync, fixed in rc2

# Fixed in 4.3
btrfs/097 # fixed in integration-4.3
generic/104 # fsync, fixed in integration-4.3
generic/106 # fsync, fixed in integration-4.3

# Take a long time to run
generic/083 # ~10 mins
generic/269 # ~5 mins
EOF
sed -e 's/\s*#.*$//' -e '/^$/d' | sort
