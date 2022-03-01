// SPDX-FileCopyrightText: Omar Sandoval <osandov@osandov.com>
// SPDX-License-Identifier: MIT

#include <elfutils/libdwelf.h>
#include <fcntl.h>
#include <getopt.h>
#include <libelf.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static const char *progname = "gnu_build_id";

static void usage(bool error)
{
	fprintf(error ? stderr : stdout,
		"usage: %s FILE...\n"
		"\n"
		"Print the GNU Build ID of one or more ELF files, one per line.\n"
		"If a file does not have a GNU Build ID, a blank line is printed.\n"
		"\n"
		"Options:\n"
		"  -h, --help   display this help message and exit\n",
		progname);
	exit(error ? EXIT_FAILURE : EXIT_SUCCESS);
}

int main(int argc, char **argv)
{
	if (argv[0])
		progname = argv[0];
	struct option long_options[] = {
		{"help", no_argument, NULL, 'h'},
	};
	for (;;) {
		int c = getopt_long(argc, argv, "h", long_options, NULL);
		if (c == -1)
			break;
		switch (c) {
		case 'h':
			usage(false);
		default:
			usage(true);
		}
	}
	if (optind >= argc)
		usage(true);

	elf_version(EV_CURRENT);

	int status = EXIT_SUCCESS;
	for (int i = optind; i < argc; i++) {
		int fd = open(argv[i], O_RDONLY);
		if (fd < 0) {
			perror(argv[i]);
			status = EXIT_FAILURE;
			continue;
		}
		Elf *elf = dwelf_elf_begin(fd);
		if (elf) {
			if (elf_kind(elf) == ELF_K_ELF) {
				const void *build_id;
				ssize_t build_id_len =
					dwelf_elf_gnu_build_id(elf, &build_id);
				if (build_id_len < 0) {
					fprintf(stderr, "%s: %s\n", argv[i],
						elf_errmsg(-1));
					status = EXIT_FAILURE;
				} else {
					for (ssize_t i = 0; i < build_id_len; i++)
						printf("%02x",
						       ((uint8_t *)build_id)[i]);
					putc('\n', stdout);
				}
			} else {
				fprintf(stderr, "%s: not an ELF file\n",
					argv[i]);
				status = EXIT_FAILURE;
			}
			elf_end(elf);
		} else {
			fprintf(stderr, "%s: %s\n", argv[i], elf_errmsg(-1));
			status = EXIT_FAILURE;
		}
		close(fd);
	}
	return status;
}
