// SPDX-FileCopyrightText: Omar Sandoval <osandov@osandov.com>
// SPDX-License-Identifier: MIT

#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <inttypes.h>
#include <linux/btrfs.h>
#include <linux/btrfs_tree.h>
#include <linux/fs.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/utsname.h>
#include <unistd.h>
#include <asm/byteorder.h>

static const char *progname = "btrfs_check_space_cache";
#define VERSION "1.0"

#define DEFAULT_NUM_RETRIES 2
#define MAX_NUM_RETRIES 100

static int fd = -1;
static struct btrfs_ioctl_fs_info_args fs_info;
static bool free_space_tree_enabled;
static int retry_num = 0;
static int num_retries = DEFAULT_NUM_RETRIES;
static bool freeze = false;
static bool extent_tree_corrupted = false;
static bool free_space_tree_corrupted = false;

static void usage(bool error)
{
	fprintf(error ? stderr : stdout,
		"usage: %s [OPTION]... PATH\n"
		"\n"
		"Check the extent tree and free space tree on a mounted Btrfs filesystem\n"
		"\n"
		"Options:\n"
		"  --retries N    how many times to retry checking a block group\n"
		"                 (default: %d, max: %d). Since this program runs\n"
		"                 while the filesystem is online, it may race against\n"
		"                 concurrent modifications to the filesystem. Retrying\n"
		"                 the check can reduce the chance of mistaking an\n"
		"                 in-progress update with corruption.\n"
		"  --freeze       freeze the filesystem on the final retry of checking\n"
		"                 a block group. This blocks all write operations for up\n"
		"                 to a few milliseconds at a time if corruption is\n"
		"                 suspected, but effectively rules out racing with\n"
		"                 concurrent modifications to the filesystem.\n"
		"                 If you kill this program while the filesystem is\n"
		"                 frozen, you may have to un-freeze the filesystem with\n"
		"                 fsfreeze --unfreeze PATH.\n"
		"  --help         display this help message and exit\n"
		"\n"
		"The exit status is one of the following:\n"
		"  0: success; no corruption detected\n"
		"  1: internal error\n"
		"  2: usage error\n"
		"  3: corruption detected\n",
		progname, DEFAULT_NUM_RETRIES, MAX_NUM_RETRIES);
	exit(error ? EXIT_FAILURE : EXIT_SUCCESS);
}

static bool retry_start(void)
{
	if (retry_num == num_retries && freeze) {
		fprintf(stderr, "Freezing filesystem\n");
		if (ioctl(fd, FIFREEZE)) {
			perror("FIFREEZE");
			return false;
		}
	} else {
		// Wait a little bit.
		sleep(1);
		// If a transaction is currently committing, might as well wait
		// for that to finish, too.
		if (ioctl(fd, BTRFS_IOC_WAIT_SYNC, NULL)) {
			perror("BTRFS_IOC_WAIT_SYNC");
			return false;
		}
	}
	return true;
}

static bool write_all(int fd, const void *buf, size_t count)
{
	size_t n = 0;
	while (n < count) {
		ssize_t r = write(fd, buf + n, count - n);
		if (r < 0)
			return false;
		n += r;
	}
	return true;
}

static void thaw_fs(void)
{
	if (freeze && ioctl(fd, FITHAW) == 0) {
		static const char message[] = "Un-froze filesystem\n";
		write_all(STDERR_FILENO, message, sizeof(message));
	}
}

static volatile sig_atomic_t received_signal = 0;

static void handle_signal(int signum)
{
	received_signal = 1;

	// fprintf() isn't async-signal-safe, so we have to roll our own.
	static const char prefix[] = "Received signal ";
	char buf[sizeof(prefix) + 32];
	char *p = buf + sizeof(buf);
	*(--p) = '\n';
	while (signum > 0) {
		*(--p) = "0123456789"[signum % 10];
		signum /= 10;
	}
	p -= sizeof(prefix) - 1;
	memcpy(p, prefix, sizeof(prefix) - 1);
	write_all(STDERR_FILENO, p, buf + sizeof(buf) - p);

	// ioctl() technically isn't async-signal-safe, but it's probably fine.
	thaw_fs();
}

__attribute__ ((__format__(__printf__, 1, 2)))
static void log_corruption(const char *format, ...)
{
	// Only log on the last retry.
	if (retry_num == num_retries) {
		va_list ap;
		va_start(ap, format);
		vfprintf(stderr, format, ap);
		va_end(ap);
	}
}

struct extent {
	__u64 start;
	__u64 size;
};

struct extent *free_extents = NULL;
static size_t free_extents_capacity = 0;
static size_t num_free_extents = 0;

static bool append_free_extent(__u64 start, __u64 size)
{
	if (num_free_extents == free_extents_capacity) {
		size_t new_capacity = 2 * free_extents_capacity + 1;
		struct extent *new_extents =
			realloc(free_extents, sizeof(free_extents[0]) * new_capacity);
		if (!new_extents) {
			perror("realloc");
			return false;
		}
		free_extents = new_extents;
		free_extents_capacity = new_capacity;
	}
	free_extents[num_free_extents++] = (struct extent){ start, size };
	return true;
}

static __u32 get_le32(const __le32 *ptr)
{
	__le32 x;
	memcpy(&x, ptr, sizeof(x));
	return __le32_to_cpu(x);
}

struct btrfs_tree_iterator {
	struct btrfs_ioctl_search_args search;
	size_t buf_offset;
	bool done;
};

static int btrfs_tree_iterator_next(struct btrfs_tree_iterator *it,
				    struct btrfs_ioctl_search_header *header_ret,
				    void **item_ret)
{
	if (it->search.key.nr_items == 0) {
		if (it->done)
			return 0;
		it->search.key.nr_items = 4096;
		it->buf_offset = 0;
		if (ioctl(fd, BTRFS_IOC_TREE_SEARCH, &it->search))
			return -1;
		if (it->search.key.nr_items == 0) {
			it->done = true;
			return 0;
		}
	}
	memcpy(header_ret, it->search.buf + it->buf_offset,
	       sizeof(*header_ret));
	*item_ret = it->search.buf + it->buf_offset + sizeof(*header_ret);

	it->search.key.nr_items--;
	it->buf_offset += sizeof(*header_ret) + header_ret->len;
	it->search.key.min_objectid = header_ret->objectid;
	it->search.key.min_type = header_ret->type;
	it->search.key.min_offset = header_ret->offset;
	// Increment the key. Note that min_type is a u32 in struct
	// btrfs_ioctl_search_key, but it's actually a u8.
	if (++it->search.key.min_offset == 0 &&
	    (it->search.key.min_type = (it->search.key.min_type + 1) & 0xff) == 0 &&
	    ++it->search.key.min_objectid == 0)
		it->done = true;

	return 1;
}

static void btrfs_tree_iterator_reset(struct btrfs_tree_iterator *it)
{
	it->search.key.nr_items = 0;
	it->buf_offset = 0;
	it->done = false;
}

static const char *key_type_to_str(__u8 type)
{
	switch (type) {
#define X(name) case BTRFS_##name##_KEY: return #name;
	X(BLOCK_GROUP_ITEM)
	X(EXTENT_ITEM)
	X(METADATA_ITEM)
	X(FREE_SPACE_INFO)
	X(FREE_SPACE_EXTENT)
	X(FREE_SPACE_BITMAP)
#undef X
	default: return "<unknown>";
	}
}

static bool check_free_extent(const struct extent *free_extents,
			      size_t num_free_extents, size_t *i, __u64 start,
			      __u64 size, bool from_bitmap)
{
	if (*i >= num_free_extents) {
		if (from_bitmap) {
			log_corruption("extra %llu+%llu in FREE_SPACE_BITMAP\n",
				       start, size);
		} else {
			log_corruption("extra (%llu FREE_SPACE_EXTENT %llu)\n",
				       start, size);
		}
		return false;
	} else if (free_extents[*i].start != start ||
		   free_extents[*i].size != size) {
		if (from_bitmap) {
			log_corruption("%llu+%llu in FREE_SPACE_BITMAP", start,
				       size);
		} else {
			log_corruption("(%llu FREE_SPACE_EXTENT %llu)", start,
				       size);
		}
		log_corruption(" does not match expected free space %llu+%llu\n",
			       free_extents[*i].start, free_extents[*i].size);
		while (*i < num_free_extents && free_extents[*i].start <= start)
			(*i)++;
		return false;
	} else {
		(*i)++;
		return true;
	}
}

enum check_result {
	CHECK_ERROR = -1,
	CHECK_OK = 0,
	CHECK_CORRUPTED = 1,
};

static enum check_result
check_free_space_tree(__u64 bg_start, __u64 bg_size,
		      const struct extent *free_extents,
		      size_t num_free_extents)
{
	enum check_result result = CHECK_OK;

	if (!free_space_tree_enabled)
		return result;

	struct btrfs_tree_iterator tree_it = {
		.search.key = {
			.tree_id = BTRFS_FREE_SPACE_TREE_OBJECTID,
			.min_objectid = bg_start,
			.min_type = BTRFS_FREE_SPACE_INFO_KEY,
			.min_offset = bg_size,
			.max_objectid = bg_start + bg_size - 1,
			.max_type = UINT8_MAX,
			.max_offset = UINT64_MAX,
			.min_transid = 0,
			.max_transid = UINT64_MAX,
		},
	};

	bool have_free_space_info = false;
	__u32 expected_extent_count = 0;
	bool bitmaps = false;
	__u64 prev_bitmap_objectid = 0, prev_bitmap_offset = 0;
	bool have_prev_bitmap = false;
	__u64 first_bit_offset = 0;
	bool last_bit = false;
	__u32 extent_count = 0;
	size_t i = 0;

	struct btrfs_ioctl_search_header header;
	void *item;
	int ret;
	while ((ret = btrfs_tree_iterator_next(&tree_it, &header, &item)) > 0) {
		if (received_signal)
			return false;

		if (header.type == BTRFS_FREE_SPACE_INFO_KEY) {
			if (have_free_space_info) {
				log_corruption("duplicate (%llu FREE_SPACE_INFO %llu)\n",
					       header.objectid, header.offset);
				result = CHECK_CORRUPTED;
				continue;
			}
			if (header.objectid != bg_start ||
			    header.offset != bg_size) {
				log_corruption("(%llu FREE_SPACE_INFO %llu) does not match (%llu BLOCK_GROUP_ITEM %llu)\n",
					       header.objectid, header.offset,
					       bg_start, bg_size);
				result = CHECK_CORRUPTED;
				continue;
			}
			struct btrfs_free_space_info *info = item;
			if (header.len < sizeof(*info)) {
				log_corruption("(%llu FREE_SPACE_INFO %llu) item is truncated\n",
					       header.objectid, header.offset);
				return CHECK_CORRUPTED;
			}
			expected_extent_count = get_le32(&info->extent_count);
			bitmaps = (get_le32(&info->flags)
				   & BTRFS_FREE_SPACE_USING_BITMAPS);
			have_free_space_info = true;
		} else if (header.type == BTRFS_FREE_SPACE_EXTENT_KEY) {
			if (!have_free_space_info) {
				log_corruption("missing (%llu FREE_SPACE_INFO %llu)\n",
					       bg_start, bg_size);
				return CHECK_CORRUPTED;
			}
			extent_count++;
			if (bitmaps) {
				log_corruption("got (%llu FREE_SPACE_EXTENT %llu) but (%llu FREE_SPACE_INFO %llu) has bitmap flag",
					       header.objectid, header.offset,
					       bg_start, bg_size);
				result = CHECK_CORRUPTED;
				continue;
			}
			if (!check_free_extent(free_extents, num_free_extents,
					       &i, header.objectid,
					       header.offset, false))
				result = CHECK_CORRUPTED;
		} else if (header.type == BTRFS_FREE_SPACE_BITMAP_KEY) {
			if (!have_free_space_info) {
				log_corruption("missing (%llu FREE_SPACE_INFO %llu)\n",
					       bg_start, bg_size);
				return CHECK_CORRUPTED;
			}
			if (!bitmaps) {
				log_corruption("got (%llu FREE_SPACE_BITMAP %llu) but (%llu FREE_SPACE_INFO %llu) does not have bitmap flag",
					       header.objectid, header.offset,
					       bg_start, bg_size);
				result = CHECK_CORRUPTED;
				continue;
			}
			if (!have_prev_bitmap && header.objectid != bg_start) {
				log_corruption("gap between start of (%llu FREE_SPACE_INFO %llu) and first (%llu FREE_SPACE_BITMAP %llu)\n",
					       bg_start, bg_size,
					       header.objectid, header.offset);
				return CHECK_CORRUPTED;
			} else if (have_prev_bitmap &&
				   header.objectid != prev_bitmap_objectid + prev_bitmap_offset) {
				log_corruption("gap between (%llu FREE_SPACE_BITMAP %llu) and (%llu FREE_SPACE_BITMAP %llu)\n",
					       prev_bitmap_objectid,
					       prev_bitmap_offset,
					       header.objectid, header.offset);
				return CHECK_CORRUPTED;
			}
			__u64 num_bits = header.offset / fs_info.sectorsize;
			if (num_bits > 8 * header.len) {
				log_corruption("(%llu FREE_SPACE_BITMAP %llu) is truncated\n",
					       header.objectid, header.offset);
				return CHECK_CORRUPTED;
			}
			__u8 *p = item;
			for (__u64 bi = 0; bi < num_bits; bi++) {
				__u64 bit_offset = header.objectid + bi * fs_info.sectorsize;
				bool bit = p[bi / 8] & (1 << (bi % 8));
				if (last_bit && !bit) {
					extent_count++;
					if (!check_free_extent(free_extents,
							       num_free_extents,
							       &i,
							       first_bit_offset,
							       bit_offset - first_bit_offset,
							       true))
						result = CHECK_CORRUPTED;
				} else if (!last_bit && bit) {
					first_bit_offset = bit_offset;
				}
				last_bit = bit;
			}
			prev_bitmap_objectid = header.objectid;
			prev_bitmap_offset = header.offset;
			have_prev_bitmap = true;
		}
	}
	if (ret) {
		perror("BTRFS_IOC_TREE_SEARCH");
		return false;
	}
	if (bitmaps) {
		if (!have_prev_bitmap) {
			log_corruption("no bitmaps\n");
			return CHECK_CORRUPTED;
		} else if (prev_bitmap_objectid + prev_bitmap_offset !=
			   bg_start + bg_size) {
			log_corruption("gap between (%llu FREE_SPACE_BITMAP %llu) and end of (%llu FREE_SPACE_INFO %llu)\n",
				       prev_bitmap_objectid, prev_bitmap_offset,
				       bg_start, bg_size);
			return CHECK_CORRUPTED;
		}
		if (last_bit) {
			extent_count++;
			if (!check_free_extent(free_extents, num_free_extents,
					       &i, first_bit_offset,
					       bg_start + bg_size - first_bit_offset,
					       true))
				result = CHECK_CORRUPTED;

		}
	}
	for (; i < num_free_extents; i++) {
		log_corruption("missing expected free space %llu+%llu\n",
			       free_extents[i].start, free_extents[i].size);
		result = CHECK_CORRUPTED;
	}
	if (have_free_space_info && extent_count != expected_extent_count) {
		log_corruption("(%llu FREE_SPACE_INFO %llu) should have %u extents, got %u\n",
			       bg_start, bg_size, expected_extent_count,
			       extent_count);
		result = CHECK_CORRUPTED;
	}
	return result;
}

static bool walk_extent_tree(void)
{
	struct btrfs_tree_iterator tree_it = {
		.search.key = {
			.tree_id = BTRFS_EXTENT_TREE_OBJECTID,
			.min_objectid = 0,
			.min_type = 0,
			.min_offset = 0,
			.max_objectid = UINT64_MAX,
			.max_type = UINT8_MAX,
			.max_offset = UINT64_MAX,
			.min_transid = 0,
			.max_transid = UINT64_MAX,
		},
	};

	bool done;

	__u64 bg_start;
	__u64 bg_size;
	__u64 bg_end;
	bool have_bg;

	__u64 prev_objectid;
	__u8 prev_type;
	__u64 prev_offset;
	__u64 cursor;

	__u64 saved_objectid;
	__u8 saved_type;
	__u64 saved_offset;
	__u64 saved_end;
	bool have_saved;

	bool bg_extent_tree_corrupted;

retry:
	num_free_extents = 0;

	btrfs_tree_iterator_reset(&tree_it);

	done = false;

	bg_start = 0;
	bg_size = 0;
	bg_end = 0;
	have_bg = false;

	prev_objectid = 0;
	prev_type = 0;
	prev_offset = 0;
	cursor = 0;

	saved_objectid = 0;
	saved_type = 0;
	saved_offset = 0;
	saved_end = 0;
	have_saved = false;

	bg_extent_tree_corrupted = false;

	struct btrfs_ioctl_search_header header;
	void *item;
	int ret;
	while ((ret = btrfs_tree_iterator_next(&tree_it, &header, &item)) > 0) {
		if (received_signal)
			return false;

		if (header.type == BTRFS_BLOCK_GROUP_ITEM_KEY) {
end_bg:
			if (have_bg) {
				if (cursor < bg_end) {
					if (!append_free_extent(cursor,
								bg_end - cursor))
						return false;
				}
				bool bg_free_space_tree_corrupted = false;
				switch (check_free_space_tree(bg_start, bg_size,
							      free_extents,
							      num_free_extents)) {
				case CHECK_ERROR:
					return false;
				case CHECK_OK:
					break;
				case CHECK_CORRUPTED:
					bg_free_space_tree_corrupted = true;
					break;
				}
				thaw_fs();
				if ((bg_extent_tree_corrupted ||
				     bg_free_space_tree_corrupted) &&
				    retry_num < num_retries) {
					retry_num++;
					fprintf(stderr, "Retry %d for %llu\n",
						retry_num, bg_start);
					if (!retry_start())
						return false;
					tree_it.search.key.min_objectid = bg_start;
					tree_it.search.key.min_type = 0;
					tree_it.search.key.min_offset = 0;
					goto retry;
				}
				extent_tree_corrupted |= bg_extent_tree_corrupted;
				free_space_tree_corrupted |= bg_free_space_tree_corrupted;
				bg_extent_tree_corrupted = false;
				retry_num = 0;
			}
			if (done)
				return true;

			num_free_extents = 0;
			bg_start = header.objectid;
			bg_size = header.offset;
			bg_end = bg_start + bg_size;
			have_bg = true;
			cursor = bg_start;

			if (have_saved) {
				if (saved_objectid == bg_start) {
					cursor = saved_end;
				} else {
					log_corruption("(%llu %s %llu) before (%llu BLOCK_GROUP_ITEM %llu)\n",
						       saved_objectid,
						       key_type_to_str(saved_type),
						       saved_offset,
						       header.objectid,
						       header.offset);
					bg_extent_tree_corrupted = true;
				}
			}
			have_saved = false;
		} else if (header.type == BTRFS_EXTENT_ITEM_KEY ||
			   header.type == BTRFS_METADATA_ITEM_KEY) {
			__u64 start = header.objectid;
			__u64 size;
			if (header.type == BTRFS_METADATA_ITEM_KEY)
				size = fs_info.nodesize;
			else
				size = header.offset;
			__u64 end = start + size;

			if (start >= bg_end) {
				if (have_saved) {
					log_corruption("(%llu %s %llu) and (%llu %s %llu) outside of block group\n",
						       saved_objectid,
						       key_type_to_str(saved_type),
						       saved_offset,
						       header.objectid,
						       key_type_to_str(header.type),
						       header.offset);
					bg_extent_tree_corrupted = true;
				}
				saved_objectid = header.objectid;
				saved_type = header.type;
				saved_offset = header.offset;
				saved_end = end;
				have_saved = true;
			} else {
				if (start < cursor) {
					log_corruption("(%llu %s %llu) overlaps previous (%llu %s %llu)\n",
						       header.objectid,
						       key_type_to_str(header.type),
						       header.offset,
						       prev_objectid,
						       key_type_to_str(prev_type),
						       prev_offset);
					bg_extent_tree_corrupted = true;
				} else if (start > cursor) {
					if (!append_free_extent(cursor,
								start - cursor))
						return false;
				}
				cursor = end;
			}
		} else {
			continue;
		}

		prev_objectid = header.objectid;
		prev_type = header.type;
		prev_offset = header.offset;
	}
	if (ret) {
		perror("BTRFS_IOC_TREE_SEARCH");
		return false;
	}
	done = true;
	goto end_bg;
}

int main(int argc, char **argv)
{
	if (argv[0])
		progname = argv[0];

	struct option long_options[] = {
		{"retries", required_argument, NULL, 'R'},
		{"freeze", no_argument, NULL, 'F'},
		{"help", no_argument, NULL, 'h'},
	};
	for (;;) {
		int c = getopt_long(argc, argv, "h", long_options, NULL);
		if (c == -1)
			break;

		switch (c) {
		case 'R': {
			if (optarg[0] == '\0')
				usage(true);
			char *end;
			errno = 0;
			unsigned long n = strtoul(optarg, &end, 10);
			if (errno || *end != '\0' || n > MAX_NUM_RETRIES)
				usage(true);
			num_retries = n;
			break;
		}
		case 'F':
			freeze = true;
			break;
		case 'h':
			usage(false);
		default:
			usage(true);
		}
	}
	const char *path;
	if (optind == argc)
		path = "/";
	else if (optind == argc - 1)
		path = argv[optind];
	else
		usage(true);

	fprintf(stderr, "Space cache checker %s\n", VERSION);
	struct utsname uts;
	if (uname(&uts)) {
		perror("uname");
		return 1;
	}
	fprintf(stderr, "retries = %d, freeze = %d\n", num_retries, freeze);
	fprintf(stderr, "Running on %s %s %s %s\n",
		uts.sysname, uts.release, uts.version, uts.machine);

	fd = open(path, O_RDONLY);
	if (fd < 0) {
		perror("open");
		return 1;
	}

	int status = 1;

	if (ioctl(fd, BTRFS_IOC_FS_INFO, &fs_info) < 0) {
		if (errno == ENOTTY) {
			fprintf(stderr, "not a Btrfs filesystem\n");
			status = 2;
			goto out;
		}
		perror("BTRFS_IOC_FS_INFO");
		goto out;
	}

	struct btrfs_ioctl_feature_flags feature_flags;
	if (ioctl(fd, BTRFS_IOC_GET_FEATURES, &feature_flags) < 0) {
		perror("BTRFS_IOC_GET_FEATURES");
		goto out;
	}
	free_space_tree_enabled =
		(feature_flags.compat_ro_flags &
		 (BTRFS_FEATURE_COMPAT_RO_FREE_SPACE_TREE |
		  BTRFS_FEATURE_COMPAT_RO_FREE_SPACE_TREE_VALID)) ==
		(BTRFS_FEATURE_COMPAT_RO_FREE_SPACE_TREE |
		 BTRFS_FEATURE_COMPAT_RO_FREE_SPACE_TREE_VALID);
	fprintf(stderr, "Free space tree is %senabled\n",
		free_space_tree_enabled ? "" : "not ");

#define catch_signal(signum) do {				\
	struct sigaction sa = { .sa_handler = handle_signal };	\
	if (sigaction(signum, &sa, NULL)) {			\
		perror("sigaction");				\
		goto out;					\
	}							\
} while (0)
	catch_signal(SIGHUP);
	catch_signal(SIGINT);
	catch_signal(SIGQUIT);
	catch_signal(SIGPIPE);
	catch_signal(SIGTERM);
#undef catch_signal

	if (atexit(thaw_fs)) {
		perror("atexit");
		goto out;
	}

	if (!walk_extent_tree()) {
		status = 1;
		goto out;
	}

	if (!extent_tree_corrupted && !free_space_tree_corrupted) {
		status = 0;
		fprintf(stderr,
			"\n"
			"No corruption detected :)\n"
			"\n"
			"You should install a kernel with the fix as soon as possible and avoid\n"
			"rebooting until then.\n"
			"\n"
			"Once you are running a kernel with the fix:\n"
			"\n"
			"1. Run this program again.\n"
			"2. Run btrfs scrub.\n");
		if (!free_space_tree_enabled) {
			fprintf(stderr,
				"\n"
				"If you want to be extra cautious, you can also clear the v1 space cache.\n"
				"There are two ways to do this. The first is:\n"
				"\n"
				"1. Add the clear_cache mount option to this filesystem in fstab.\n"
				"2. Unmount then mount the filesystem. Note that `mount -o remount` is\n"
				"   not sufficient; you need a full unmount/mount cycle. You can also\n"
				"   reboot instead.\n"
				"3. Remove the clear_cache mount option from fstab.\n"
				"\n"
				"The second way to clear the space cache is:\n"
				"\n"
				"1. Unmount the filesystem.\n"
				"2. Run `btrfs check --clear-space-cache v1 <device>`.\n"
				"3. Mount the filesystem.\n");
		}
	} else {
		status = 3;
		fprintf(stderr, "\n");
		if (extent_tree_corrupted) {
			fprintf(stderr, "Extent tree corruption %s.\n",
				freeze ? "detected" : "suspected");
		}
		if (free_space_tree_corrupted) {
			fprintf(stderr, "Free space tree tree corruption %s.\n",
				freeze ? "detected" : "suspected");
		}
		if (!freeze) {
			fprintf(stderr,
				"\n"
				"Consider re-running with --freeze for a more confident diagnosis. Note\n"
				"that this may block write operations for intervals of up to a few\n"
				"milliseconds.\n");
		}
		fprintf(stderr,
			"\n"
			"File data or metadata may have been lost. You will most likely still be\n"
			"able to access most of the data on this filesystem for now. Files with\n"
			"checksums enabled will be unreadable if they were corrupted. Files with\n"
			"checksums disabled may have been silently corrupted.\n");

		if (extent_tree_corrupted) {
			fprintf(stderr,
				"\n"
				"As soon as possible, you should back up any files that you wish to keep.\n"
				"\n"
				"Then, when you are able to:\n"
				"\n"
				"1. Unmount the filesystem.\n"
				"2. Reformat the filesystem. Do not mount it yet.\n"
				"3. Install a kernel with the fix.\n"
				"4. Reboot into the fixed kernel.\n"
				"5. Mount the filesystem and restore it from backups.\n");
		} else if (free_space_tree_corrupted) {
			fprintf(stderr,
				"\n"
				"You may be able to recover this filesystem by clearing the space cache.\n"
				"Do the following as soon as possible:\n"
				"\n"
				"1. Back up any files that you wish to keep if this recovery fails.\n"
				"2. Unmount the filesystem.\n"
				"3. Clear the space cache with\n"
				"  `btrfs check --clear-space-cache v2 <device>`.\n"
				"4. Install a kernel with the fix.\n"
				"5. Reboot into the fixed kernel.\n"
				"6. Run this program again and follow the instructions.\n");
		}
	}

out:
	free(free_extents);
	close(fd);
	return status;
}
