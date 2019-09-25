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

static const char *progname = "btrfs_map_physical";

static void usage(bool error)
{
	fprintf(error ? stderr : stdout,
		"usage: %s [OPTION]... PATH\n"
		"\n"
		"Map the logical and physical extents of a file on Btrfs\n\n"
		"Pipe this to `column -ts $'\\t'` for prettier output.\n"
		"\n"
		"Options:\n"
		"  -h, --help   display this help message and exit\n",
		progname);
	exit(error ? EXIT_FAILURE : EXIT_SUCCESS);
}

struct stripe {
	uint64_t devid;
	uint64_t offset;
};

struct chunk {
	uint64_t offset;
	uint64_t length;
	uint64_t stripe_len;
	uint64_t type;
	struct stripe *stripes;
	size_t num_stripes;
	size_t sub_stripes;
};

struct chunk_tree {
	struct chunk *chunks;
	size_t num_chunks;
};

static int read_chunk_tree(int fd, struct chunk **chunks, size_t *num_chunks)
{
	struct btrfs_ioctl_search_args search = {
		.key = {
			.tree_id = BTRFS_CHUNK_TREE_OBJECTID,
			.min_objectid = BTRFS_FIRST_CHUNK_TREE_OBJECTID,
			.max_objectid = BTRFS_FIRST_CHUNK_TREE_OBJECTID,
			.min_type = BTRFS_CHUNK_ITEM_KEY,
			.max_type = BTRFS_CHUNK_ITEM_KEY,
			.min_offset = 0,
			.max_offset = UINT64_MAX,
			.min_transid = 0,
			.max_transid = UINT64_MAX,
			.nr_items = 0,
		},
	};
	size_t items_pos = 0, buf_off = 0;
	size_t capacity = 0;
	int ret;

	*chunks = NULL;
	*num_chunks = 0;
	for (;;) {
		const struct btrfs_ioctl_search_header *header;
		const struct btrfs_chunk *item;
		struct chunk *chunk;
		size_t i;

		if (items_pos >= search.key.nr_items) {
			search.key.nr_items = 4096;
			ret = ioctl(fd, BTRFS_IOC_TREE_SEARCH, &search);
			if (ret == -1) {
				perror("BTRFS_IOC_TREE_SEARCH");
				return -1;
			}
			items_pos = 0;
			buf_off = 0;

			if (search.key.nr_items == 0)
				break;
		}

		header = (struct btrfs_ioctl_search_header *)(search.buf + buf_off);
		if (header->type != BTRFS_CHUNK_ITEM_KEY)
			goto next;

		item = (void *)(header + 1);
		if (*num_chunks >= capacity) {
			struct chunk *tmp;

			if (capacity == 0)
				capacity = 1;
			else
				capacity *= 2;
			tmp = realloc(*chunks, capacity * sizeof(**chunks));
			if (!tmp) {
				perror("realloc");
				return -1;
			}
			*chunks = tmp;
		}

		chunk = &(*chunks)[*num_chunks];
		chunk->offset = header->offset;
		chunk->length = le64_to_cpu(item->length);
		chunk->stripe_len = le64_to_cpu(item->stripe_len);
		chunk->type = le64_to_cpu(item->type);
		chunk->num_stripes = le16_to_cpu(item->num_stripes);
		chunk->sub_stripes = le16_to_cpu(item->sub_stripes);
		chunk->stripes = calloc(chunk->num_stripes,
					sizeof(*chunk->stripes));
		if (!chunk->stripes) {
			perror("calloc");
			return -1;
		}
		(*num_chunks)++;

		for (i = 0; i < chunk->num_stripes; i++) {
			const struct btrfs_stripe *stripe;

			stripe = &item->stripe + i;
			chunk->stripes[i].devid = le64_to_cpu(stripe->devid);
			chunk->stripes[i].offset = le64_to_cpu(stripe->offset);
		}

next:
		items_pos++;
		buf_off += sizeof(*header) + header->len;
		if (header->offset == UINT64_MAX)
			break;
		else
			search.key.min_offset = header->offset + 1;
	}
	return 0;
}

static struct chunk *find_chunk(struct chunk *chunks, size_t num_chunks,
				uint64_t logical)
{
	size_t lo, hi;

	if (!num_chunks)
		return NULL;

	lo = 0;
	hi = num_chunks - 1;
	while (lo <= hi) {
		size_t mid = lo + (hi - lo) / 2;

		if (logical < chunks[mid].offset)
			hi = mid - 1;
		else if (logical >= chunks[mid].offset + chunks[mid].length)
			lo = mid + 1;
		else
			return &chunks[mid];
	}
	return NULL;
}

static int print_extents(int fd, struct chunk *chunks, size_t num_chunks)
{
	struct btrfs_ioctl_search_args search = {
		.key = {
			.min_type = BTRFS_EXTENT_DATA_KEY,
			.max_type = BTRFS_EXTENT_DATA_KEY,
			.min_offset = 0,
			.max_offset = UINT64_MAX,
			.min_transid = 0,
			.max_transid = UINT64_MAX,
			.nr_items = 0,
		},
	};
	struct btrfs_ioctl_ino_lookup_args args = {
		.treeid = 0,
		.objectid = BTRFS_FIRST_FREE_OBJECTID,
	};
	size_t items_pos = 0, buf_off = 0;
	struct stat st;
	int ret;

	puts("FILE OFFSET\tEXTENT TYPE\tLOGICAL SIZE\tLOGICAL OFFSET\tPHYSICAL SIZE\tDEVID\tPHYSICAL OFFSET");

	ret = fstat(fd, &st);
	if (ret == -1) {
		perror("fstat");
		return -1;
	}

	ret = ioctl(fd, BTRFS_IOC_INO_LOOKUP, &args);
	if (ret == -1) {
		perror("BTRFS_IOC_INO_LOOKUP");
		return -1;
	}

	search.key.tree_id = args.treeid;
	search.key.min_objectid = search.key.max_objectid = st.st_ino;
	for (;;) {
		const struct btrfs_ioctl_search_header *header;
		const struct btrfs_file_extent_item *item;

		if (items_pos >= search.key.nr_items) {
			search.key.nr_items = 4096;
			ret = ioctl(fd, BTRFS_IOC_TREE_SEARCH, &search);
			if (ret == -1) {
				perror("BTRFS_IOC_TREE_SEARCH");
				return -1;
			}
			items_pos = 0;
			buf_off = 0;

			if (search.key.nr_items == 0)
				break;
		}

		header = (struct btrfs_ioctl_search_header *)(search.buf + buf_off);
		if (header->type != BTRFS_EXTENT_DATA_KEY)
			goto next;

		item = (void *)(header + 1);

		printf("%" PRIu64 "\t", (uint64_t)header->offset);
		switch (item->type) {
		case BTRFS_FILE_EXTENT_INLINE:
			printf("inline");
			break;
		case BTRFS_FILE_EXTENT_REG:
			if (item->disk_bytenr)
				printf("regular");
			else
				printf("hole");
			break;
		case BTRFS_FILE_EXTENT_PREALLOC:
			printf("prealloc");
			break;
		default:
			printf("type%u", item->type);
			break;
		}
		switch (item->compression) {
		case 0:
			break;
		case 1:
			printf(",compression=zlib");
			break;
		case 2:
			printf(",compression=lzo");
			break;
		case 3:
			printf(",compression=zstd");
			break;
		default:
			printf(",compression=%u", item->compression);
			break;
		}
		if (item->encryption)
			printf(",encryption=%u", item->encryption);
		if (item->other_encoding) {
			printf(",other_encoding=%u",
			       le16_to_cpu(item->other_encoding));
		}

		if (item->type == BTRFS_FILE_EXTENT_INLINE) {
			uint64_t len;

			len = (header->len -
			       offsetof(struct btrfs_file_extent_item,
					disk_bytenr));
			printf("\t%" PRIu64 "\t\t%" PRIu64 "\n",
			       (uint64_t)le64_to_cpu(item->ram_bytes), len);
		} else if (item->type == BTRFS_FILE_EXTENT_REG ||
			   item->type == BTRFS_FILE_EXTENT_PREALLOC) {
			uint64_t disk_bytenr, disk_num_bytes, num_bytes, offset;
			uint64_t stripe_nr, stripe_offset;
			size_t stripe_index, num_stripes;
			struct chunk *chunk;
			size_t i;

			disk_bytenr = le64_to_cpu(item->disk_bytenr);
			disk_num_bytes = le64_to_cpu(item->disk_num_bytes);
			num_bytes = le64_to_cpu(item->num_bytes);

			if (disk_bytenr == 0) {
				printf("\t%" PRIu64 "\n", num_bytes);
				goto next;
			}

			disk_bytenr += le64_to_cpu(item->offset);
			disk_num_bytes -= le64_to_cpu(item->offset);

			chunk = find_chunk(chunks, num_chunks, disk_bytenr);
			if (!chunk) {
				putc('\n', stdout);
				fprintf(stderr,
					"could not find chunk containing %" PRIu64 "\n",
					disk_bytenr);
				return -1;
			}

			offset = disk_bytenr - chunk->offset;
			stripe_nr = offset / chunk->stripe_len;
			stripe_offset = offset - stripe_nr * chunk->stripe_len;
			switch (chunk->type & BTRFS_BLOCK_GROUP_PROFILE_MASK) {
			case 0:
			case BTRFS_BLOCK_GROUP_RAID0:
				if (chunk->type & BTRFS_BLOCK_GROUP_RAID0)
					printf(",raid0");
				stripe_index = stripe_nr % chunk->num_stripes;
				stripe_nr /= chunk->num_stripes;
				num_stripes = 1;
				break;
			case BTRFS_BLOCK_GROUP_RAID1:
			case BTRFS_BLOCK_GROUP_DUP:
				if (chunk->type & BTRFS_BLOCK_GROUP_RAID1)
					printf(",raid1");
				else
					printf(",dup");
				stripe_index = 0;
				num_stripes = chunk->num_stripes;
				break;
			case BTRFS_BLOCK_GROUP_RAID10: {
				size_t factor;

				printf(",raid10");
				factor = chunk->num_stripes / chunk->sub_stripes;
				stripe_index = (stripe_nr % factor *
						chunk->sub_stripes);
				stripe_nr /= factor;
				num_stripes = chunk->sub_stripes;
				break;
			}
			case BTRFS_BLOCK_GROUP_RAID5:
			case BTRFS_BLOCK_GROUP_RAID6: {
				size_t nr_parity_stripes, nr_data_stripes;

				if (chunk->type & BTRFS_BLOCK_GROUP_RAID6) {
					printf(",raid6");
					nr_parity_stripes = 2;
				} else {
					printf(",raid5");
					nr_parity_stripes = 1;
				}
				nr_data_stripes = (chunk->num_stripes -
						   nr_parity_stripes);
				stripe_index = stripe_nr % nr_data_stripes;
				stripe_nr /= nr_data_stripes;
				stripe_index = ((stripe_nr + stripe_index) %
						chunk->num_stripes);
				num_stripes = 1;
				break;
			}
			default:
				printf(",profile%" PRIu64,
				       (uint64_t)(chunk->type &
						  BTRFS_BLOCK_GROUP_PROFILE_MASK));
				num_stripes = 0;
				break;
			}

			printf("\t%" PRIu64 "\t%" PRIu64 "\t%" PRIu64,
			       num_bytes, disk_bytenr, disk_num_bytes);
			if (!num_stripes)
				printf("\n");

			for (i = 0; i < num_stripes; i++) {
				if (i != 0)
					printf("\t\t\t\t");
				printf("\t%" PRIu64 "\t%" PRIu64 "\n",
				       chunk->stripes[stripe_index].devid,
				       chunk->stripes[stripe_index].offset +
				       stripe_nr * chunk->stripe_len +
				       stripe_offset);
				stripe_index++;
			}
		}

next:
		items_pos++;
		buf_off += sizeof(*header) + header->len;
		if (header->offset == UINT64_MAX)
			break;
		else
			search.key.min_offset = header->offset + 1;
	}
	return 0;
}

int main(int argc, char **argv)
{
	struct option long_options[] = {
		{"help", no_argument, NULL, 'h'},
	};
	int fd, ret;
	struct chunk *chunks;
	size_t num_chunks, i;

	if (argv[0])
		progname = argv[0];

	for (;;) {
		int c;

		c = getopt_long(argc, argv, "h", long_options, NULL);
		if (c == -1)
			break;

		switch (c) {
		case 'h':
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

	ret = read_chunk_tree(fd, &chunks, &num_chunks);
	if (ret == -1)
		goto out;

	ret = print_extents(fd, chunks, num_chunks);
out:
	for (i = 0; i < num_chunks; i++)
		free(chunks[i].stripes);
	free(chunks);
	close(fd);
	return ret ? EXIT_FAILURE : EXIT_SUCCESS;
}
