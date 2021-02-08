// SPDX-FileCopyrightText: Omar Sandoval <osandov@osandov.com>
// SPDX-License-Identifier: MIT

#include <stdbool.h>
#include <fcntl.h>
#include <inttypes.h>
#include <getopt.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <linux/btrfs.h>
#include <linux/btrfs_tree.h>
#include <asm/byteorder.h>

#define le16_to_cpu __le16_to_cpu
#define le32_to_cpu __le32_to_cpu
#define le64_to_cpu __le64_to_cpu

static const char *progname = "btrfs_count_file_extent_items";

static void usage(bool error)
{
	fprintf(error ? stderr : stdout,
		"usage: %s [OPTION]... PATH\n"
		"\n"
		"Count the number of file extent items in a Btrfs filesystem\n"
		"\n"
		"Options:\n"
		"  -t, --tree TREE_ID    only count extents in the given tree\n"
		"  -h, --help            display this help message and exit\n",
		progname);
	exit(error ? EXIT_FAILURE : EXIT_SUCCESS);
}

static bool file_extent_items_in_tree(int fd, uint64_t tree_id,
				      uint64_t *num_file_extent_items)
{
	struct btrfs_ioctl_search_args search = {
		.key = {
			.tree_id = tree_id,
			.min_objectid = 0,
			.min_type = BTRFS_EXTENT_DATA_KEY,
			.min_offset = 0,
			.max_objectid = UINT64_MAX,
			.max_type = BTRFS_EXTENT_DATA_KEY,
			.max_offset = UINT64_MAX,
			.min_transid = 0,
			.max_transid = UINT64_MAX,
			.nr_items = 0,
		},
	};
	size_t items_pos = 0, buf_off = 0;
	for (;;) {
		if (items_pos >= search.key.nr_items) {
			search.key.nr_items = 4096;
			if (ioctl(fd, BTRFS_IOC_TREE_SEARCH, &search) == -1) {
				perror("BTRFS_IOC_TREE_SEARCH");
				return false;
			}
			items_pos = 0;
			buf_off = 0;
			if (search.key.nr_items == 0)
				break;
		}

		const struct btrfs_ioctl_search_header *header =
			(void *)(search.buf + buf_off);
		if (header->type == BTRFS_EXTENT_DATA_KEY)
			(*num_file_extent_items)++;

		items_pos++;
		buf_off += sizeof(*header) + header->len;
		search.key.min_objectid = header->objectid;
		search.key.min_type = header->type;
		search.key.min_offset = header->offset;
		if (search.key.min_offset < UINT64_MAX) {
			search.key.min_offset++;
		} else {
			search.key.min_offset = 0;
			if (search.key.min_type < UINT8_MAX) {
				search.key.min_type++;
			} else {
				search.key.min_type = 0;
				if (search.key.min_objectid == UINT64_MAX)
					break;
			}
		}
	}
	return true;
}

int main(int argc, char **argv)
{
	progname = argv[0];

	struct btrfs_ioctl_search_args search = {
		.key = {
			.tree_id = BTRFS_ROOT_TREE_OBJECTID,
			.min_objectid = BTRFS_FS_TREE_OBJECTID,
			.min_type = BTRFS_ROOT_ITEM_KEY,
			.min_offset = 0,
			.max_objectid = BTRFS_LAST_FREE_OBJECTID,
			.max_type = BTRFS_ROOT_ITEM_KEY,
			.max_offset = UINT64_MAX,
			.min_transid = 0,
			.max_transid = UINT64_MAX,
			.nr_items = 0,
		},
	};

	struct option long_options[] = {
		{"help", no_argument, NULL, 'h'},
	};
	for (;;) {
		int c = getopt_long(argc, argv, "ht:", long_options, NULL);
		if (c == -1)
			break;
		switch (c) {
		case 't':
			search.key.min_objectid = search.key.max_objectid =
				strtoull(optarg, NULL, 10);
			break;
		case 'h':
			usage(false);
		default:
			usage(true);
		}
	}
	if (optind != argc - 1)
		usage(true);

	int fd = open(argv[optind], O_RDONLY);
	if (fd == -1) {
		perror(argv[1]);
		return EXIT_FAILURE;
	}

	uint64_t num_file_extent_items = 0;

	size_t items_pos = 0, buf_off = 0;
	for (;;) {
		if (items_pos >= search.key.nr_items) {
			search.key.nr_items = 4096;
			if (ioctl(fd, BTRFS_IOC_TREE_SEARCH, &search) == -1) {
				perror("BTRFS_IOC_TREE_SEARCH");
				goto err;
			}
			items_pos = 0;
			buf_off = 0;
			if (search.key.nr_items == 0)
				break;
		}

		const struct btrfs_ioctl_search_header *header =
			(void *)(search.buf + buf_off);
		if (header->type == BTRFS_ROOT_ITEM_KEY &&
		    (header->objectid == BTRFS_FS_TREE_OBJECTID ||
		     (header->objectid >= BTRFS_FIRST_FREE_OBJECTID &&
		      header->objectid <= BTRFS_LAST_FREE_OBJECTID))) {
			if (!file_extent_items_in_tree(fd, header->objectid,
						       &num_file_extent_items))
				goto err;

		} else if (header->type == BTRFS_EXTENT_DATA_KEY) {
			/* Extent from free space cache. */
			num_file_extent_items++;
		}

		items_pos++;
		buf_off += sizeof(*header) + header->len;
		search.key.min_objectid = header->objectid;
		search.key.min_type = header->type;
		search.key.min_offset = header->offset;
		if (search.key.min_offset < UINT64_MAX) {
			search.key.min_offset++;
		} else {
			search.key.min_offset = 0;
			if (search.key.min_type < UINT8_MAX) {
				search.key.min_type++;
			} else {
				search.key.min_type = 0;
				if (search.key.min_objectid == UINT64_MAX)
					break;
			}
		}
	}
	printf("%" PRIu64 "\n", num_file_extent_items);
	close(fd);
	return EXIT_SUCCESS;

err:
	close(fd);
	return EXIT_FAILURE;
}
