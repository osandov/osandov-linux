// SPDX-FileCopyrightText: Omar Sandoval <osandov@osandov.com>
// SPDX-License-Identifier: MIT

#define _GNU_SOURCE
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <linux/kexec.h>

int main(int argc, char **argv)
{
	long ret;
	int kernel_fd;
	int initrd_fd;

	if (argc != 4) {
		fprintf(stderr, "usage: %s kernel initrd cmdline\n", argv[0]);
		return EXIT_FAILURE;
	}

	kernel_fd = open(argv[1], O_RDONLY);
	if (kernel_fd == -1) {
		perror("open");
		return EXIT_FAILURE;
	}

	initrd_fd = open(argv[2], O_RDONLY);
	if (initrd_fd == -1) {
		perror("open");
		close(kernel_fd);
		return EXIT_FAILURE;
	}

	ret = syscall(SYS_kexec_file_load, kernel_fd, initrd_fd,
		      (unsigned long)strlen(argv[3]) + 1, argv[3],
		      (unsigned long)KEXEC_FILE_ON_CRASH);
	if (ret == -1) {
		perror("kexec_file_load");
		close(initrd_fd);
		close(kernel_fd);
		return EXIT_FAILURE;
	}

	close(initrd_fd);
	close(kernel_fd);
	return EXIT_SUCCESS;
}
