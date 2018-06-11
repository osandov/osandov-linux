#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <getopt.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <sys/types.h>
#include <linux/btrfs.h>
#include <linux/btrfs_tree.h>
#include <linux/fiemap.h>
#include <linux/fs.h>
#include <btrfs/crc32c.h>

#define BTRFS_MAX_EXTENT (128 * 1024 * 1024)
#define FM_EXTENT_COUNT 64

static const char *progname = "btrfs_csum_file";

struct chunk {
	uint64_t logical;
	uint64_t length;
	uint64_t physical;
};

static int read_chunk_map(int fd, struct chunk **chunks, size_t *num_chunks)
{
	struct btrfs_ioctl_search_args search = {
		.key = {
			.tree_id = BTRFS_CHUNK_TREE_OBJECTID,
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
	size_t capacity = 0;

	*chunks = NULL;
	*num_chunks = 0;

	for (;;) {
		const struct btrfs_ioctl_search_header *header;
		const struct btrfs_chunk *item;

		if (items_pos >= search.key.nr_items) {
			search.key.nr_items = 4096;
			if (ioctl(fd, BTRFS_IOC_TREE_SEARCH, &search) == -1) {
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

		if (!(le64_to_cpu(item->type) & BTRFS_BLOCK_GROUP_DATA))
			goto next;

		if (le16_to_cpu(item->num_stripes) != 1) {
			fprintf(stderr, "data chunk has more than one stripe\n");
			return -1;
		}

		if (le16_to_cpu(item->stripe.devid) != 1) {
			fprintf(stderr, "data chunk is not on devid 1\n");
			return -1;
		}

		if (*num_chunks >= capacity) {
			size_t new_capacity;
			struct chunk *tmp;

			if (capacity)
				new_capacity = capacity * 2;
			else
				new_capacity = 1;

			tmp = realloc(*chunks, new_capacity * sizeof(**chunks));
			if (!tmp) {
				perror("realloc");
				return -1;
			}

			*chunks = tmp;
			capacity = new_capacity;
		}

		(*chunks)[*num_chunks].logical = header->offset;
		(*chunks)[*num_chunks].length = le64_to_cpu(item->length);
		(*chunks)[*num_chunks].physical = le64_to_cpu(item->stripe.offset);
		(*num_chunks)++;

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

	return 0;
}

static int map_logical_to_physical(struct chunk *chunks, size_t num_chunks,
				   uint64_t logical, uint64_t *physical,
				   uint64_t *length)
{
	ssize_t i;

	for (i = num_chunks; i >= 0; i--) {
		uint64_t logical_start = chunks[i].logical;
		uint64_t logical_end = logical_start + chunks[i].length;

		if (logical_start <= logical && logical < logical_end) {
			*physical = chunks[i].physical + (logical - logical_start);
			*length = chunks[i].length - (logical - logical_start);
			break;
		}
	}

	if (i < 0) {
		fprintf(stderr, "chunk containing %" PRIu64 " not found\n", logical);
		return -1;
	}

	/*
	 * Move the found chunk to the end of the array so we find it faster
	 * next time.
	 */
	if (i < num_chunks - 1) {
		struct chunk tmp = chunks[i];

		memmove(&chunks[i], &chunks[i + 1],
			(num_chunks - i - 1) * sizeof(chunks[0]));
		chunks[num_chunks - 1] = tmp;
	}

	return 0;
}

static inline bool csum_item_contains(struct btrfs_ioctl_search_header *header,
				      uint64_t offset, uint32_t sectorsize)
{
	return (header->offset <= offset &&
		offset < header->offset + (header->len / sizeof(uint32_t)) * sectorsize);
}

static int find_csum(int fd, uint64_t offset, uint32_t sectorsize,
		     struct btrfs_ioctl_search_args_v2 *search,
		     uint32_t *csum)
{
	struct btrfs_ioctl_search_header *header = (void *)search->buf;

	if (!search->key.nr_items || !csum_item_contains(header, offset, sectorsize)) {
		search->key.min_offset = offset;

		for (;;) {
			search->key.max_offset = search->key.min_offset;
			search->key.nr_items = 1;

			if (ioctl(fd, BTRFS_IOC_TREE_SEARCH_V2, search) == -1) {
				perror("BTRFS_IOC_TREE_SEARCH");
				return -1;
			}

			if (search->key.nr_items &&
			    csum_item_contains(header, offset, sectorsize))
				break;

			/*
			 * We should stop searching if we hit an csum item which
			 * doesn't contain the given offset, we hit the
			 * beginning of the block address space, or we searched
			 * back the maximum length of an extent.
			 */
			if (search->key.nr_items ||
			    search->key.min_offset == 0 ||
			    offset - search->key.min_offset + sectorsize >= BTRFS_MAX_EXTENT) {
				fprintf(stderr, "csum not found for %" PRIu64 "\n", offset);
				return -1;
			}

			search->key.min_offset -= sectorsize;
		}
	}

	*csum = le32_to_cpu(((uint32_t *)(header + 1))[(offset - header->offset) / sectorsize]);
	return 0;
}

static void usage(bool error)
{
	fprintf(error ? stderr : stdout,
		"usage: %s [OPTION]... PATH DEV [OFFSET [LENGTH]]\n"
		"\n"
		"Check the checksums on a Btrfs file from userspace\n"
		"\n"
		"Arguments:\n"
		"  PATH              file to checksum\n"
		"  DEV               block device containing filesystem\n"
		"  OFFSET, LENGTH    if given, only check extents overlapping this range\n"
		"Options:\n"
		"  -v, --verbose    print more information, namely, the checksum of each\n"
		"                   corrupted disk block\n"
		"  -h, --help       display this help message and exit\n",
		progname);
	exit(error ? EXIT_FAILURE : EXIT_SUCCESS);
}

int main(int argc, char **argv)
{
	struct option long_options[] = {
		{"verbose", no_argument, NULL, 'v'},
		{"help", no_argument, NULL, 'h'},
	};
	bool verbose = false;
	uint64_t check_offset, check_length;
	int fd, devfd;
	struct chunk *chunks = NULL;
	size_t num_chunks;
	struct statfs sfs;
	uint64_t sectorsize;
	struct btrfs_ioctl_search_args_v2 *search = NULL;
	size_t search_buf_size;
	void *buf = NULL;
	struct fiemap *fm = NULL;
	int status = EXIT_FAILURE;

	crc32c_optimization_init();

	progname = argv[0];

	for (;;) {
		int c;

		c = getopt_long(argc, argv, "vh", long_options, NULL);
		if (c == -1)
			break;

		switch (c) {
		case 'v':
			verbose = true;
			break;
		case 'h':
			usage(false);
		default:
			usage(true);
		}
	}
	if (argc - optind != 2 && argc - optind != 3 && argc - optind != 4)
		usage(true);

	fd = open(argv[optind], O_RDONLY);
	if (fd == -1) {
		perror(argv[1]);
		return EXIT_FAILURE;
	}

	devfd = open(argv[optind + 1], O_RDONLY | O_DIRECT);
	if (devfd == -1) {
		perror(argv[2]);
		close(fd);
		return EXIT_FAILURE;
	}

	if (fstatfs(fd, &sfs) == -1) {
		perror("fstatfs");
		goto out;
	}
	sectorsize = sfs.f_bsize;

	if (argc - optind >= 3)
		check_offset = strtoull(argv[optind + 2], NULL, 0);
	else
		check_offset = 0;
	if (argc - optind >= 4)
		check_length = strtoull(argv[optind + 3], NULL, 0);
	else
		check_length = sectorsize;

	if (read_chunk_map(fd, &chunks, &num_chunks) == -1)
		goto out;

	/*
	 * We can have one 32-bit checksum for each filesystem sector, up to the
	 * maximum extent size.
	 */
	search_buf_size = BTRFS_MAX_EXTENT / sectorsize * sizeof(uint32_t);
	search = malloc(sizeof(*search) +
			sizeof(struct btrfs_ioctl_search_header) +
			search_buf_size);
	if (!search) {
		perror("calloc");
		goto out;
	}
	memset(&search->key, 0, sizeof(search->key));
	search->key.tree_id = BTRFS_CSUM_TREE_OBJECTID;
	search->key.min_objectid = BTRFS_EXTENT_CSUM_OBJECTID;
	search->key.max_objectid = BTRFS_EXTENT_CSUM_OBJECTID;
	search->key.min_type = BTRFS_EXTENT_CSUM_KEY;
	search->key.max_type = BTRFS_EXTENT_CSUM_KEY;
	search->key.min_transid = 0;
	search->key.max_transid = UINT64_MAX;
	search->key.nr_items = 0;
	search->buf_size = search_buf_size;

	errno = posix_memalign(&buf, sectorsize, sectorsize);
	if (errno) {
		perror("posix_memalign");
		goto out;
	}

	fm = calloc(1, sizeof(*fm) + FM_EXTENT_COUNT * sizeof(fm->fm_extents[0]));
	if (!fm) {
		perror("calloc");
		goto out;
	}
	fm->fm_length = (uint64_t)-1;
	fm->fm_extent_count = FM_EXTENT_COUNT;

	for (;;) {
		struct fiemap_extent *fe = NULL;
		unsigned int i;

		if (ioctl(fd, FS_IOC_FIEMAP, fm) == -1)
			goto out;

		for (i = 0; i < fm->fm_mapped_extents; i++) {
			uint64_t offset, logical, end;
			uint64_t physical = 0, physical_length = 0;
			uint64_t extent_offset = 0, extent_logical = 0;
			uint64_t extent_physical = 0, extent_length = 0;
			uint64_t uncorrupted_offset = 0, corrupted_offset = 0;
			bool printed_extent = false;

			fe = &fm->fm_extents[i];

			if (fe->fe_logical + fe->fe_length <= check_offset ||
			    check_offset + check_length <= fe->fe_logical)
				continue;

			if (fe->fe_flags & FIEMAP_EXTENT_UNKNOWN) {
				printf("extent %llu location is unknown; skipping\n",
				       fe->fe_logical);
				continue;
			}
			if (fe->fe_flags & FIEMAP_EXTENT_NOT_ALIGNED) {
				printf("extent %llu is not aligned; skipping\n",
				       fe->fe_logical);
				continue;
			}
			if (fe->fe_flags & FIEMAP_EXTENT_ENCODED) {
				printf("extent %llu is encoded; skipping\n",
				       fe->fe_logical);
				continue;
			}
			if (fe->fe_flags & FIEMAP_EXTENT_UNWRITTEN) {
				printf("extent %llu is unwritten; skipping\n",
				       fe->fe_logical);
				continue;
			}

			offset = fe->fe_logical;
			logical = fe->fe_physical;
			end = logical + fe->fe_length;

			while (logical < end) {
				uint32_t calculated_csum, disk_csum;
				ssize_t sret;

				if (!physical_length) {
					if (printed_extent) {
						if (offset != corrupted_offset)
							printf("%" PRIu64 " bytes with invalid csums at offset %" PRIu64 "\n",
							       offset - corrupted_offset, corrupted_offset);
						if (offset != uncorrupted_offset)
							printf("%" PRIu64 " bytes with valid csums at offset %" PRIu64 "\n",
							       offset - uncorrupted_offset, uncorrupted_offset);
					}

					if (map_logical_to_physical(chunks,
								    num_chunks,
								    logical,
								    &physical,
								    &physical_length) == -1)
						goto out;
					extent_offset = offset;
					extent_logical = logical;
					extent_physical = physical;
					extent_length = end - logical;
					if (physical_length < extent_length)
						extent_length = physical_length;
					uncorrupted_offset = corrupted_offset = offset;
					printed_extent = false;
				}

				sret = pread(devfd, buf, sectorsize, physical);
				if (sret == -1) {
					perror("pread");
					goto out;
				} else if (sret != sectorsize) {
					fprintf(stderr, "short read from device");
					goto out;
				}

				calculated_csum = crc32c_le(0xffffffff, buf, sectorsize) ^ 0xffffffff;

				if (find_csum(fd, logical, sectorsize, search,
					      &disk_csum) == -1)
					goto out;

				if (calculated_csum == disk_csum) {
					if (offset != corrupted_offset)
						printf("%" PRIu64 " bytes with invalid csums at offset %" PRIu64 "\n",
						       offset - corrupted_offset, corrupted_offset);
					corrupted_offset = offset + sectorsize;
				} else {
					if (!printed_extent) {
						printf("extent at offset %" PRIu64 " logical %" PRIu64 " physical %" PRIu64 " length %" PRIu64 " has csum errors\n",
						       extent_offset,
						       extent_logical,
						       extent_physical,
						       extent_length);
						printed_extent = true;
					}
					if (offset != uncorrupted_offset)
						printf("%" PRIu64 " bytes with valid csums at offset %" PRIu64 "\n",
						       offset - uncorrupted_offset, uncorrupted_offset);
					uncorrupted_offset = offset + sectorsize;
					if (verbose)
						printf("block at offset %" PRIu64 " logical %" PRIu64 " physical %" PRIu64 " calculated csum 0x%08" PRIx32 " != disk csum 0x%08" PRIx32 "\n",
						       offset, logical, physical, calculated_csum, disk_csum);
				}

				offset += sectorsize;
				logical += sectorsize;
				physical += sectorsize;
				physical_length -= sectorsize;
			}

			if (printed_extent) {
				if (offset != corrupted_offset)
					printf("%" PRIu64 " bytes with invalid csums at offset %" PRIu64 "\n",
					       offset - corrupted_offset, corrupted_offset);
				if (offset != uncorrupted_offset)
					printf("%" PRIu64 " bytes with valid csums at offset %" PRIu64 "\n",
					       offset - uncorrupted_offset, uncorrupted_offset);
			}
		}

		/*
		 * If fm->fm_mapped_extents == 0, fe is NULL. Otherwise, fe is
		 * still the last extent.
		 */
		if (!fe || (fe->fe_flags & FIEMAP_EXTENT_LAST))
			break;

		fm->fm_start = fe->fe_logical + fe->fe_length;
	}

	status = EXIT_SUCCESS;
out:
	free(fm);
	free(buf);
	free(search);
	free(chunks);
	close(devfd);
	close(fd);
	return status;
}
