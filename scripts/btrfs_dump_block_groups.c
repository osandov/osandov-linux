#include <stdbool.h>
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

void print_block_group(uint64_t flags, uint64_t offset, uint64_t length,
		       uint64_t used, uint64_t num_extents,
		       uint64_t max_free_extent)
{
	double percent_used = 100.0 * used / length;

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
	printf("\t%" PRIu64 "\t%" PRIu64 "\t%" PRIu64 "\t%" PRIu64 "\t%" PRIu64 "\t%.2f\n",
	       offset, length, used, num_extents, max_free_extent,
	       percent_used);
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
	size_t items_pos = 0, buf_off = 0;
	bool have_block_group = false;
	struct btrfs_ioctl_fs_info_args fs_info;
	uint64_t block_group_flags;
	uint64_t block_group_offset;
	uint64_t block_group_length;
	uint64_t block_group_used;
	uint64_t num_extents = 0;
	uint64_t max_free_extent = 0;
	uint64_t free_extent_offset = 0;
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

	ret = ioctl(fd, BTRFS_IOC_FS_INFO, &fs_info);
	if (ret == -1) {
		perror("BTRFS_IOC_FS_INFO");
		goto err;
	}

	printf("TYPE\tOFFSET\tLENGTH\tUSED\tNUM EXTENTS\tMAX EXTENT\tUSE%%\n");
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
		if (header->type == BTRFS_EXTENT_ITEM_KEY ||
		    header->type == BTRFS_METADATA_ITEM_KEY) {
			uint64_t extent_offset, extent_length;
			uint64_t free_extent;

			extent_offset = header->objectid;
			if (header->type == BTRFS_EXTENT_ITEM_KEY) {
				extent_length = header->offset;
			} else {
				extent_length = fs_info.nodesize;
			}

			if (have_block_group) {
				/*
				 * EXTENT_ITEM_KEY and METADATA_ITEM_KEY are
				 * less than BLOCK_GROUP_ITEM_KEY, so if there
				 * is an extent at the beginning of the block
				 * group, we will hit the extent item before we
				 * know about the next block group.
				 */
				if (extent_offset >= block_group_offset + block_group_length) {
					free_extent = block_group_offset + block_group_length - free_extent_offset;
					if (free_extent > max_free_extent)
						max_free_extent = free_extent;
					print_block_group(block_group_flags,
							  block_group_offset,
							  block_group_length,
							  block_group_used,
							  num_extents,
							  max_free_extent);
					num_extents = 0;
					max_free_extent = 0;
					have_block_group = false;
				} else {
					free_extent = extent_offset - free_extent_offset;
					if (free_extent > max_free_extent)
						max_free_extent = free_extent;
				}
			}

			num_extents++;
			free_extent_offset = extent_offset + extent_length;
		} else if (header->type == BTRFS_BLOCK_GROUP_ITEM_KEY) {
			const struct btrfs_block_group_item *block_group = (void *)(header + 1);

			if (have_block_group) {
				uint64_t free_extent;

				free_extent = block_group_offset + block_group_length - free_extent_offset;
				if (free_extent > max_free_extent)
					max_free_extent = free_extent;
				print_block_group(block_group_flags,
						  block_group_offset,
						  block_group_length,
						  block_group_used,
						  num_extents,
						  max_free_extent);
				num_extents = 0;
				max_free_extent = 0;
			}

			block_group_flags = le64_to_cpu(block_group->flags);
			block_group_offset = header->objectid;
			block_group_length = header->offset;
			block_group_used = le64_to_cpu(block_group->used);

			have_block_group = true;
			if (block_group_offset > free_extent_offset)
				free_extent_offset = block_group_offset;
		}


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

	if (have_block_group) {
		uint64_t free_extent;

		free_extent = block_group_offset + block_group_length - free_extent_offset;
		if (free_extent > max_free_extent)
			max_free_extent = free_extent;
		print_block_group(block_group_flags,
				  block_group_offset,
				  block_group_length,
				  block_group_used,
				  num_extents,
				  max_free_extent);
	}

	close(fd);
	return EXIT_SUCCESS;

err:
	close(fd);
	return EXIT_FAILURE;
}
