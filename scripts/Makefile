CFLAGS ?= -Wall -O2 -g

TARGETS := \
	alloc_hugepage \
	btrfs_check_space_cache \
	btrfs_count_file_extent_items \
	btrfs_dump_block_groups \
	btrfs_extent_tree_du \
	btrfs_ino_lookup \
	btrfs_map_physical \
	debuginfod_client \
	gnu_build_id \
	kcore_to_vmcore \
	malloc_usable_size \
	my_kdump_load \
	swapme \
	time_disk_read

btrfs_check_space_cache_CFLAGS := -Wno-address-of-packed-member
btrfs_csum_file_LDLIBS := -lbtrfs
debuginfod_client_LDLIBS := -ldebuginfod
gnu_build_id_LDLIBS := -ldw -lelf
kcore_to_vmcore_LDLIBS := -lelf

all: $(TARGETS)

clean:
	rm -f $(TARGETS)

%: %.c
	$(CC) $($@_CFLAGS) $(CFLAGS) $($@_CPPFLAGS) $(CPPFLAGS) $($@_LDFLAGS) $(LDFLAGS) $^ $($@_LDLIBS) $(LDLIBS) -o $@

.PHONY: all clean
