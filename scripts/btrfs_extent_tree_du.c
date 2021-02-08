// SPDX-FileCopyrightText: Omar Sandoval <osandov@osandov.com>
// SPDX-License-Identifier: MIT

#include <fcntl.h>
#include <getopt.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stddef.h>
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

static const char *progname = "btrfs_extent_tree_du";

static bool human_readable = false;
static bool root_only = false;

static void print_number(uint64_t number)
{
	static const char *suffixes[] = {"", "k", "M", "G", "T", "P", "E", "Z"};
	static const size_t num_suffixes = sizeof(suffixes) / sizeof(suffixes[0]);

	if (human_readable) {
		uint64_t fraction = 0;
		size_t i;

		for (i = 0; i < num_suffixes; i++) {
			if (number < 1024)
				break;
			fraction = number % 1024;
			number /= 1024;
		}

		printf("%g%s", (double)number + fraction / 1024.0, suffixes[i]);
	} else {
		printf("%" PRIu64, number);
	}
}

static void usage(bool error)
{
	fprintf(error ? stderr : stdout,
		"usage: %s [OPTION]... PATH\n"
		"\n"
		"Get Btrfs disk usage by walking the extent tree\n"
		"\n"
		"Options:\n"
		"  -h, --human-readable   print sizes in powers of 1024 (e.g., 1023M)\n"
		"  -r, --root             group only by root (e.g., subvolume), not by objectid\n"
		"                         (e.g., file)\n"
		"  --help                 display this help message and exit\n",
		progname);
	exit(error ? EXIT_FAILURE : EXIT_SUCCESS);
}

struct du_hash_entry {
	uint64_t root;
	uint64_t objectid;
	uint64_t prev_bytenr;
	uint64_t bytes;
};

static struct du_hash_entry *du_hash_find(struct du_hash_entry *du_hash,
					  size_t capacity, uint64_t root,
					  uint64_t objectid)
{
	static const uint32_t golden_ratio32 = UINT32_C(0x61C88647);
	static const uint64_t golden_ratio64 = UINT64_C(0x61C8864680B583EB);
	uint32_t hash = (golden_ratio32 * root) ^ (golden_ratio64 * objectid);
	size_t i = hash & (capacity - 1);

	for (;;) {
		struct du_hash_entry *entry = &du_hash[i];

		if (!entry->root ||
		    (entry->root == root && entry->objectid == objectid))
			return entry;
		i = (i + 1) & (capacity - 1);
	}
}

static int du_hash_add(struct du_hash_entry **du_hash, size_t *size,
		       size_t *capacity, uint64_t bytenr, uint64_t root,
		       uint64_t objectid, uint64_t bytes)
{
	struct du_hash_entry *entry;

	entry = du_hash_find(*du_hash, *capacity, root, objectid);
	if (entry->root) {
		if (bytenr != entry->prev_bytenr) {
			entry->prev_bytenr = bytenr;
			entry->bytes += bytes;
		}
		return 0;
	}

	entry->root = root;
	entry->objectid = objectid;
	entry->prev_bytenr = bytenr;
	entry->bytes = bytes;
	(*size)++;

	if (*size >= *capacity * 3 / 4) {
		struct du_hash_entry *new_du_hash;
		uint64_t new_capacity = *capacity * 2;
		size_t i;

		new_du_hash = calloc(new_capacity, sizeof(*new_du_hash));
		if (!new_du_hash)
			return -1;

		for (i = 0; i < *capacity; i++) {
			entry = &(*du_hash)[i];
			if (entry->root) {
				struct du_hash_entry *new_entry;

				new_entry = du_hash_find(new_du_hash,
							 new_capacity,
							 entry->root,
							 entry->objectid);
				*new_entry = *entry;
			}
		}

		free(*du_hash);
		*du_hash = new_du_hash;
		*capacity = new_capacity;
	}
	return 0;
}

static int process_data_ref(uint64_t bytenr,
			    const struct btrfs_extent_data_ref *data_ref,
			    uint64_t bytes, struct du_hash_entry **du_hash,
			    size_t *du_hash_size, size_t *du_hash_capacity)
{
	uint64_t root, objectid;
	int ret;

	root = le64_to_cpu(data_ref->root);
	if (root_only)
		objectid = 0;
	else
		objectid = le64_to_cpu(data_ref->objectid);
	ret = du_hash_add(du_hash, du_hash_size, du_hash_capacity, bytenr, root,
			  objectid, bytes);
	if (ret == -1)
		fprintf(stderr, "%m\n");
	return ret;
}

static void print_du_hash(struct du_hash_entry *du_hash,
			  size_t capacity)
{
	size_t i;

	for (i = 0; i < capacity; i++) {
		struct du_hash_entry *entry = &du_hash[i];

		if (entry->root) {
			printf("root %" PRIu64, entry->root);
			if (!root_only)
				printf(" objectid %" PRIu64, entry->objectid);
			printf(" references ");
			print_number(entry->bytes);
			putc('\n', stdout);
		}
	}
}

int main(int argc, char **argv)
{
	struct btrfs_ioctl_search_args search = {
		.key = {
			.tree_id = BTRFS_EXTENT_TREE_OBJECTID,
			.min_objectid = 0,
			.min_type = 0,
			.min_offset = 0,
			.max_objectid = UINT64_MAX,
			.max_type = UINT8_MAX,
			.max_offset = UINT64_MAX,
			.min_transid = 0,
			.max_transid = UINT64_MAX,
			.nr_items = 0,
		},
	};
	struct option long_options[] = {
		{"human-readable", no_argument, NULL, 'h'},
		{"root", no_argument, NULL, 'r'},
		{"help", no_argument, NULL, 'H'},
	};
	size_t items_pos = 0, buf_off = 0;
	uint64_t prev_objectid = 0, num_bytes = 0;
	struct btrfs_ioctl_fs_info_args fs_info;
	struct du_hash_entry *du_hash = NULL;
	size_t du_hash_size;
	size_t du_hash_capacity;
	int ret;
	int fd;

	progname = argv[0];

	for (;;) {
		int c;

		c = getopt_long(argc, argv, "hr", long_options, NULL);
		if (c == -1)
			break;

		switch (c) {
		case 'h':
			human_readable = true;
			break;
		case 'r':
			root_only = true;
			break;
		case 'H':
			usage(false);
		default:
			usage(true);
		}
	}
	if (optind != argc - 1)
		usage(true);

	fd = open(argv[optind], O_RDONLY);
	if (fd == -1) {
		perror("open");
		return EXIT_FAILURE;
	}

	ret = ioctl(fd, BTRFS_IOC_FS_INFO, &fs_info);
	if (ret == -1) {
		perror("BTRFS_IOC_FS_INFO");
		goto err;
	}

	du_hash_size = 0;
	du_hash_capacity = 4096;
	du_hash = calloc(du_hash_capacity, sizeof(*du_hash));
	if (!du_hash) {
		perror("calloc");
		goto err;
	}

	for (;;) {
		const struct btrfs_ioctl_search_header *header;

		if (items_pos >= search.key.nr_items) {
			search.key.nr_items = 4096;
			ret = ioctl(fd, BTRFS_IOC_TREE_SEARCH, &search);
			if (ret == -1) {
				perror("BTRFS_IOC_TREE_SEARCH");
				goto err;
			}
			items_pos = 0;
			buf_off = 0;

			if (search.key.nr_items == 0)
				break;
		}

		header = (void *)(search.buf + buf_off);
		buf_off += sizeof(*header);
		if (header->type == BTRFS_EXTENT_ITEM_KEY) {
			const struct btrfs_extent_item *item;
			size_t ref_off;

			if (sizeof(search.buf) - buf_off < sizeof(*item)) {
				fprintf(stderr,
					"extent item (%llu, %u, %llu) is truncated\n",
					header->objectid, header->type,
					header->offset);
				goto err;
			}
			item = (void *)(search.buf + buf_off);
			if (!(le64_to_cpu(item->flags) & BTRFS_EXTENT_FLAG_DATA))
				goto next;

			prev_objectid = header->objectid;
			num_bytes = header->offset;
			ref_off = sizeof(*item);
			while (ref_off < header->len) {
				const struct btrfs_extent_inline_ref *ref;

				if (header->len - ref_off < sizeof(*ref)) {
					fprintf(stderr,
						"inline ref (%llu, %u, %llu) is truncated\n",
						header->objectid, header->type,
						header->offset);
					goto err;
				}
				ref = (void *)(search.buf + buf_off + ref_off);
				if (ref->type == BTRFS_EXTENT_DATA_REF_KEY) {
					const struct btrfs_extent_data_ref *data_ref;

					ref_off += offsetof(struct btrfs_extent_inline_ref,
							    offset);
					if (header->len - ref_off <
					    sizeof(*data_ref)) {
						fprintf(stderr,
							"inline data ref (%llu, %u, %llu) is truncated\n",
							header->objectid, header->type,
							header->offset);
						goto err;
					}
					data_ref = (void *)(search.buf +
							    buf_off + ref_off);
					ref_off += sizeof(*data_ref);
					ret = process_data_ref(header->objectid,
							       data_ref,
							       num_bytes,
							       &du_hash,
							       &du_hash_size,
							       &du_hash_capacity);
					if (ret == -1)
						goto err;
				} else {
					ref_off += sizeof(*ref);
					if (ref->type == BTRFS_SHARED_DATA_REF_KEY) {
						ref_off += sizeof(struct btrfs_shared_data_ref);
					} else if (ref->type != BTRFS_TREE_BLOCK_REF_KEY &&
						   ref->type != BTRFS_SHARED_BLOCK_REF_KEY) {
						fprintf(stderr,
							"(%llu, %u, %llu) has unknown inline ref type 0x%x\n",
							header->objectid,
							header->type,
							header->offset,
							ref->type);
						goto err;
					}
				}
			}
		} else if (header->type == BTRFS_EXTENT_DATA_REF_KEY) {
			const struct btrfs_extent_data_ref *data_ref;

			if (sizeof(search.buf) - buf_off < sizeof(*data_ref)) {
				fprintf(stderr,
					"data ref (%llu, %u, %llu) is truncated\n",
					header->objectid, header->type,
					header->offset);
				goto err;
			}
			if (header->objectid != prev_objectid) {
				fprintf(stderr,
					"found data ref (%llu, %u, %llu) without extent item\n",
					header->objectid, header->type,
					header->offset);
				goto err;
			}
			data_ref = (void *)(search.buf + buf_off);
			ret = process_data_ref(header->objectid, data_ref,
					       num_bytes, &du_hash,
					       &du_hash_size,
					       &du_hash_capacity);
			if (ret == -1)
				goto err;
		}

next:
		buf_off += header->len;
		items_pos++;
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

	print_du_hash(du_hash, du_hash_capacity);

	free(du_hash);
	close(fd);
	return EXIT_SUCCESS;

err:
	free(du_hash);
	close(fd);
	return EXIT_FAILURE;
}
