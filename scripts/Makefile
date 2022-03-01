TARGETS := \
	btrfs_count_file_extent_items \
	btrfs_dump_block_groups \
	btrfs_extent_tree_du \
	btrfs_ino_lookup \
	btrfs_map_physical \
	gnu_build_id \
	kcore_to_vmcore \
	my_kdump_load \
	swapme \
	time_disk_read

all: $(TARGETS)

clean:
	rm -f $(TARGETS)

%: %.c
	$(CC) -Wall -O2 -o $@ $<

btrfs_csum_file: btrfs_csum_file.c
	$(CC) -g -Wall -O2 -o $@ $< -lbtrfs

gnu_build_id: gnu_build_id.c
	$(CC) -g -Wall -O2 -o $@ $< -ldw -lelf

kcore_to_vmcore: kcore_to_vmcore.c
	$(CC) -g -Wall -O2 -o $@ $< -lelf

.PHONY: all clean
