#include <fcntl.h>
#include <getopt.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <unistd.h>

#ifndef MADV_COLLAPSE
#define MADV_COLLAPSE 25
#endif

static const char *progname = "alloc_hugepage";

static void usage(bool error)
{
	fprintf(error ? stderr : stdout,
		"usage: %s [OPTION]... [PATH [OFFSET]]\n"
		"\n"
		"Allocate a huge page.\n"
		"\n"
		"Options:\n"
		"  -s, --size SIZE     size of allocation\n"
		"  -x, --executable    map executable instead of read-write\n"
		"  -p, --pause         pause instead of exiting immediately\n"
		"  -h, --help          display this help message and exit\n",
		progname);
	exit(error ? EXIT_FAILURE : EXIT_SUCCESS);
}

int main(int argc, char **argv)
{
	if (argv[0])
		progname = argv[0];

	unsigned long size = 2 * 1024 * 1024;
	int o_flags = O_RDWR;
	int fd = -1;
	off_t offset = 0;
	int protection = PROT_READ | PROT_WRITE;
	int map_flags = MAP_PRIVATE | MAP_ANONYMOUS;
	bool do_pause = false;

	static struct option long_options[] = {
		{"size", required_argument, NULL, 's'},
		{"executable", no_argument, NULL, 'x'},
		{"pause", no_argument, NULL, 'p'},
		{"help", no_argument, NULL, 'h'},
		{},
	};
	for (;;) {
		int c = getopt_long(argc, argv, "s:xph", long_options, NULL);
		if (c == -1)
			break;
		switch (c) {
		case 's':
			size = strtoul(optarg, NULL, 10);
			break;
		case 'x':
			o_flags = O_RDONLY;
			protection = PROT_READ | PROT_EXEC;
			break;
		case 'p':
			do_pause = true;
			break;
		case 'h':
			usage(false);
		default:
			usage(true);
		}
	}
	if (argc - optind > 2)
		usage(true);

	if (argc - optind >= 1) {
		fd = open(argv[optind], o_flags);
		if (fd < 0) {
			perror(argv[optind]);
			return EXIT_FAILURE;
		}

		if (argc - optind >= 2)
			offset = strtoul(argv[optind + 1], NULL, 10);

		map_flags = MAP_SHARED;
	}

	// Reserve some address space so that we can align the mapping to the
	// huge page size.
	void *placeholder_map = mmap(NULL, size * 2, PROT_NONE,
				     MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
	if (placeholder_map == MAP_FAILED) {
		perror("mmap (placeholder)");
		return EXIT_FAILURE;
	}

	void *aligned_address =
		(void *)(((uintptr_t)placeholder_map + size - 1) & ~(size - 1));

	void *map = mmap(aligned_address, size, protection,
			 map_flags | MAP_FIXED | MAP_POPULATE, fd, offset);
	if (map == MAP_FAILED) {
		perror("mmap");
		return EXIT_FAILURE;
	}

	if (madvise(map, size, MADV_COLLAPSE) < 0) {
		perror("madvise");
		return EXIT_FAILURE;
	}

	printf("%p\n", map);

	if (do_pause)
		pause();

	return EXIT_SUCCESS;
}
