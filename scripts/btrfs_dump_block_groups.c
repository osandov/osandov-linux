#include <fcntl.h>
#include <inttypes.h>
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

int main(int argc, char **argv)
{
	struct btrfs_ioctl_search_args search = {
		.key = {
			.tree_id = BTRFS_EXTENT_TREE_OBJECTID,
			.min_objectid = 0,
			.max_objectid = UINT64_MAX,
			.min_type = BTRFS_BLOCK_GROUP_ITEM_KEY,
			.max_type = BTRFS_BLOCK_GROUP_ITEM_KEY,
			.min_offset = 0,
			.max_offset = UINT64_MAX,
			.min_transid = 0,
			.max_transid = UINT64_MAX,
			.nr_items = 0,
		},
	};
	size_t items_pos = 0, buf_off = 0;
	int ret;
	int fd;

	if (argc != 2) {
		fprintf(stderr, "usage: %s PATH\n", argv[0]);
		return EXIT_FAILURE;
	}

	fd = open(argv[1], O_RDONLY);
	if (fd == -1) {
		perror("open");
		return EXIT_FAILURE;
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

		header = (struct btrfs_ioctl_search_header *)(search.buf + buf_off);
		if (header->type == BTRFS_BLOCK_GROUP_ITEM_KEY) {
			const struct btrfs_block_group_item *block_group = (void *)(header + 1);
			uint64_t size = header->offset;
			uint64_t used = le64_to_cpu(block_group->used);
			uint64_t flags = le64_to_cpu(block_group->flags);
			double percent_used = 100.0 * used / size;

			block_group = (struct btrfs_block_group_item *)(header + 1);
			switch (flags & BTRFS_BLOCK_GROUP_TYPE_MASK) {
			case BTRFS_BLOCK_GROUP_DATA:
				printf("DATA");
				break;
			case BTRFS_BLOCK_GROUP_SYSTEM:
				printf("SYSTEM");
				break;
			case BTRFS_BLOCK_GROUP_METADATA:
				printf("METADATA");
				break;
			case BTRFS_BLOCK_GROUP_DATA | BTRFS_BLOCK_GROUP_METADATA:
				printf("MIXED");
				break;
			default:
				printf("0x%" PRIx64, (uint64_t)(flags & BTRFS_BLOCK_GROUP_TYPE_MASK));
				break;
			}
			printf(" block group %" PRIu64 " has %" PRIu64 " used out of %" PRIu64 " (%.2f%%)\n",
			       (uint64_t)header->objectid, used, size, percent_used);
		}

		items_pos++;
		buf_off += sizeof(*header) + header->len;
		search.key.min_objectid = header->objectid;
		search.key.min_offset = header->offset + 1;
	}

	close(fd);
	return EXIT_SUCCESS;

err:
	close(fd);
	return EXIT_FAILURE;
}
