all: btrfs_csum_file \
	btrfs_dump_block_groups \
	btrfs_extent_tree_du \
	btrfs_ino_lookup \
	my_kdump_load \
	swapme

%: %.c
	$(CC) -Wall -O2 -o $@ $<

btrfs_csum_file: btrfs_csum_file.c
	$(CC) -g -Wall -O2 -o $@ $< -lbtrfs
