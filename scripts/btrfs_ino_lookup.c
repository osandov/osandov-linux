// SPDX-FileCopyrightText: Omar Sandoval <osandov@osandov.com>
// SPDX-License-Identifier: MIT

#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <linux/btrfs.h>

int main(int argc, char **argv)
{
	struct btrfs_ioctl_ino_lookup_args args;
	int fd;
	int ret;

	if (argc != 4) {
		fprintf(stderr, "usage: %s path treeid objectid\n", argv[0]);
		return EXIT_FAILURE;
	}

	fd = open(argv[1], O_RDONLY);
	if (fd == -1) {
		perror(argv[1]);
		return EXIT_FAILURE;
	}

	args.treeid = strtoull(argv[2], NULL, 0);
	args.objectid = strtoull(argv[3], NULL, 0);
	ret = ioctl(fd, BTRFS_IOC_INO_LOOKUP, &args);
	if (ret == -1) {
		perror("BTRFS_IOC_INO_LOOKUP");
		close(fd);
		return EXIT_FAILURE;
	}

	puts(args.name);

	close(fd);
	return EXIT_FAILURE;
}
