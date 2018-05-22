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

static const char *progname = "btrfs_extent_tree_du";

static bool human_readable = false;

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
		"Get Btrfs disk usage by walking the extent tree"
		"\n"
		"Options:\n"
		"  -h, --human-readable   print sizes in powers of 1024 (e.g., 1023M)\n"
		"  --help                 display this help message and exit\n",
		progname);
	exit(error ? EXIT_FAILURE : EXIT_SUCCESS);
}

struct du_hash_entry {
	uint64_t root;
	uint64_t objectid;
	uint64_t bytes;
	struct du_hash_entry *next;
};

static void du_hash_really_add(struct du_hash_entry *du_hash,
			       size_t capacity, uint64_t root,
			       uint64_t objectid, uint64_t bytes)
{
	uint64_t hash = 53 * root + objectid;
	uint64_t i = hash & (capacity - 1);

	for (;;) {
		struct du_hash_entry *entry = &du_hash[i];

		if (entry->root == root &&
		    entry->objectid == objectid) {
			entry->bytes += bytes;
			break;
		} else if (!entry->root) {
			entry->root = root;
			entry->objectid = objectid;
			entry->bytes = bytes;
			break;
		} else {
			i = (i + 1) & (capacity - 1);
		}
	}
}

static int du_hash_add(struct du_hash_entry **du_hash,
		       size_t *size, size_t *capacity,
		       uint64_t root, uint64_t objectid, uint64_t bytes)
{
	if (*size >= *capacity * 3 / 4) {
		struct du_hash_entry *new_du_hash;
		uint64_t new_capacity;
		size_t i;

		if (*capacity)
			new_capacity = *capacity * 2;
		else
			new_capacity = 1;

		new_du_hash = calloc(new_capacity, sizeof(*new_du_hash));
		if (!new_du_hash)
			return -1;

		for (i = 0; i < *capacity; i++) {
			struct du_hash_entry *entry = &(*du_hash)[i];

			if (entry->root) {
				du_hash_really_add(new_du_hash, new_capacity,
						   entry->root, entry->objectid,
						   entry->bytes);
			}
		}

		*du_hash = new_du_hash;
		*capacity = new_capacity;
	}

	du_hash_really_add(*du_hash, *capacity, root, objectid, bytes);
	(*size)++;
	return 0;
}

static void print_du_hash(struct du_hash_entry *du_hash,
			  size_t capacity)
{
	size_t i;

	for (i = 0; i < capacity; i++) {
		struct du_hash_entry *entry = &du_hash[i];

		if (entry->root) {
			printf("root %" PRIu64 " objectid %" PRIu64 " references ",
			       entry->root, entry->objectid);
			print_number(entry->bytes);
			puts("");
		}
	}
}

int main(int argc, char **argv)
{
	struct btrfs_ioctl_search_args search = {
		.key = {
			.tree_id = BTRFS_EXTENT_TREE_OBJECTID,
			.min_objectid = 0,
			.max_objectid = UINT64_MAX,
			.min_type = 0,
			.max_type = UINT32_MAX,
			.min_offset = 0,
			.max_offset = UINT64_MAX,
			.min_transid = 0,
			.max_transid = UINT64_MAX,
			.nr_items = 0,
		},
	};
	struct option long_options[] = {
		{"human-readable", no_argument, NULL, 'h'},
		{"help", no_argument, NULL, 'H'},
	};
	size_t items_pos = 0, buf_off = 0;
	struct btrfs_ioctl_fs_info_args fs_info;
	struct du_hash_entry *du_hash = NULL;
	size_t du_hash_size = 0;
	size_t du_hash_capacity = 0;
	int ret;
	int fd;

	progname = argv[0];

	for (;;) {
		int c;

		c = getopt_long(argc, argv, "h", long_options, NULL);
		if (c == -1)
			break;

		switch (c) {
		case 'h':
			human_readable = true;
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

	for (;;) {
		const struct btrfs_ioctl_search_header *header;
		const struct btrfs_extent_item *item;
		const struct btrfs_extent_inline_ref *ref;
		uint64_t refs, flags;

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

		header = (struct btrfs_ioctl_search_header *)(search.buf + buf_off);
		if (header->type != BTRFS_EXTENT_ITEM_KEY)
			goto next;

		item = (void *)(header + 1);
		refs = le64_to_cpu(item->refs);
		flags = le64_to_cpu(item->flags);
		if (!(flags & BTRFS_EXTENT_FLAG_DATA))
			goto next;

		ref = (void *)(item + 1);
		while (refs) {
			if (ref->type == BTRFS_TREE_BLOCK_REF_KEY ||
			    ref->type == BTRFS_SHARED_BLOCK_REF_KEY) {
				refs--;
				ref++;
			} else if (ref->type == BTRFS_EXTENT_DATA_REF_KEY) {
				const struct btrfs_extent_data_ref *data_ref;
				uint64_t root, objectid;

				data_ref = (void *)&ref->offset;
				root = le64_to_cpu(data_ref->root);
				objectid = le64_to_cpu(data_ref->objectid);
				ret = du_hash_add(&du_hash, &du_hash_size,
						  &du_hash_capacity, root,
						  objectid, header->offset);
				if (ret == -1)
					goto err;
				refs -= le32_to_cpu(data_ref->count);
				ref = (void *)(data_ref + 1);
			} else if (ref->type == BTRFS_SHARED_DATA_REF_KEY) {
				const struct btrfs_shared_data_ref *data_ref;

				data_ref = (void *)(ref + 1);
				refs -= le32_to_cpu(data_ref->count);
				ref = (void *)(data_ref + 1);
			} else {
				fprintf(stderr, "unknown ref type 0x%x\n",
					ref->type);
				goto err;
			}
		}

next:
		items_pos++;
		buf_off += sizeof(*header) + header->len;
		search.key.min_objectid = header->objectid;
		search.key.min_type = header->type;
		search.key.min_offset = header->offset;
		if (search.key.min_offset == UINT64_MAX) {
			if (search.key.min_type == UINT32_MAX) {
				if (search.key.min_objectid == UINT64_MAX)
					break;
				else
					search.key.min_objectid++;
			} else {
				search.key.min_type++;
			}
		} else {
			search.key.min_offset++;
		}
	}

	print_du_hash(du_hash, du_hash_capacity);

	close(fd);
	return EXIT_SUCCESS;

err:
	close(fd);
	return EXIT_FAILURE;
}
