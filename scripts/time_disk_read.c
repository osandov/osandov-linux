#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/types.h>

static const char *progname = "time_disk_read";

static void usage(bool error)
{
	fprintf(error ? stderr : stdout,
		"usage: %s [OPTION]... PATH OFFSET\n"
		"\n"
		"Time reading from a specific disk block\n"
		"\n"
		"Options:\n"
		"  -b, --blocksize BYTES    read a block of this size (default: 4096)\n"
		"  -c, --cachesize BYTES    read this many bytes after the given block in order\n"
		"                           to evict the block from the disk cache (default: 0)\n"
		"  -l, --loops N            repeat the read this many times (default: 1000)\n"
		"  -h, --help               display this help message and exit\n",
		progname);
	exit(error ? EXIT_FAILURE : EXIT_SUCCESS);
}

int main(int argc, char **argv)
{
	struct option long_options[] = {
		{"blocksize", no_argument, NULL, 'b'},
		{"block-size", no_argument, NULL, 'b'},
		{"cache-size", no_argument, NULL, 'c'},
		{"cache-size", no_argument, NULL, 'c'},
		{"help", no_argument, NULL, 'h'},
	};
	int fd;
	void *buf;
	int status = EXIT_FAILURE;
	size_t blocksize = 4096;
	size_t cachesize = 0;
	long loops = 1000;
	off_t offset;

	progname = argv[0];

	for (;;) {
		int c;

		c = getopt_long(argc, argv, "b:c:l:h", long_options, NULL);
		if (c == -1)
			break;

		switch (c) {
		case 'b':
			blocksize = strtoul(optarg, NULL, 0);
			break;
		case 'c':
			cachesize = strtoul(optarg, NULL, 0);
			break;
		case 'l':
			loops = strtol(optarg, NULL, 0);
			break;
		case 'h':
			usage(false);
		default:
			usage(true);
		}
	}
	if (optind != argc - 2)
		usage(true);

	if (!blocksize) {
		fprintf(stderr, "invalid block size\n");
		return EXIT_FAILURE;
	}
	if (cachesize % blocksize) {
		fprintf(stderr, "cache size is not multiple of block size\n");
		return EXIT_FAILURE;
	}

	fd = open(argv[optind], O_RDONLY | O_DIRECT);
	if (fd == -1) {
		perror(argv[1]);
		return EXIT_FAILURE;
	}

	offset = strtoll(argv[optind + 1], NULL, 0);

	errno = posix_memalign(&buf, blocksize,
			       cachesize > blocksize ? cachesize : blocksize);
	if (errno) {
		perror("posix_memalign");
		buf = NULL;
		goto out;
	}

	while (loops--) {
		struct timespec before, after;
		long long elapsed;
		ssize_t sret;

		if (lseek(fd, offset, SEEK_SET) == -1) {
			perror("lseek");
			goto out;
		}

		/* Time the read of the block in question. */
		if (clock_gettime(CLOCK_MONOTONIC, &before) == -1) {
			perror("clock_gettime");
			goto out;
		}
		sret = read(fd, buf, blocksize);
		if (sret == -1) {
			perror("read");
			goto out;
		}
		if (sret != blocksize) {
			fprintf(stderr, "short read\n");
			goto out;
		}
		if (clock_gettime(CLOCK_MONOTONIC, &after) == -1) {
			perror("clock_gettime");
			goto out;
		}

		elapsed = ((after.tv_sec - before.tv_sec) * 1000000000LL +
			   (after.tv_nsec - before.tv_nsec));
		printf("%lld.%06lld ms\n", elapsed / 1000000, elapsed % 1000000);

		if (cachesize) {
			sret = read(fd, buf, cachesize);
			if (sret == -1) {
				perror("read");
				goto out;
			}
			if (sret != cachesize) {
				fprintf(stderr, "short read\n");
				goto out;
			}
		}
	}

	status = EXIT_SUCCESS;
out:
	free(buf);
	close(fd);
	return status;
}
