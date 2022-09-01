// SPDX-FileCopyrightText: Omar Sandoval <osandov@osandov.com>
// SPDX-License-Identifier: MIT

#include <elfutils/debuginfod.h>
#include <errno.h>
#include <getopt.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static const char *progname = "debuginfod_client";

static void usage(bool error)
{
	fprintf(error ? stderr : stdout,
		"usage: %s BUILD-ID [-e|--executable] [-d|--debuginfo] [-s|--source SOURCE] ...\n"
		"\n"
		"Download files from debuginfod.\n"
		"\n"
		"Options:\n"
		"  -e, --executable     download the executable file\n"
		"  -d, --debuginfo      download the debuginfo file\n"
		"  -s, --source PATH    download a source file\n"
		"  -h, --help           display this help message and exit\n",
		progname);
	exit(error ? EXIT_FAILURE : EXIT_SUCCESS);
}

int main(int argc, char **argv)
{
	if (argv[0])
		progname = argv[0];

	static struct option long_options[] = {
		{"executable", no_argument, NULL, 'e'},
		{"debuginfo", no_argument, NULL, 'd'},
		{"source", required_argument, NULL, 's'},
		{"help", no_argument, NULL, 'h'},
		{},
	};
	static const char optstring[] = "-eds:h";
	const char *build_id = NULL;
	// Validate the options before doing anything.
	for (;;) {
		int c = getopt_long(argc, argv, optstring, long_options, NULL);
		if (c == -1)
			break;
		switch (c) {
		case 1:
			build_id = optarg;
			break;
		case 'e':
		case 'd':
		case 's':
			if (!build_id)
				usage(true);
			break;
		case 'h':
			usage(false);
		default:
			usage(true);
		}
	}
	if (!build_id)
		usage(true);

	debuginfod_client *client = debuginfod_begin();
	if (!client) {
		fprintf(stderr, "couldn't create debuginfod client\n");
		return EXIT_FAILURE;
	}
	int status = EXIT_SUCCESS;
	char *path;
	int fd;
	optind = 1;
	for (;;) {
		int c = getopt_long(argc, argv, optstring, long_options, NULL);
		if (c == -1)
			break;
		switch (c) {
		case 1:
			build_id = optarg;
			break;
		case 'e':
			fd = debuginfod_find_executable(client,
							(unsigned char *)build_id,
							0, &path);
			if (fd >= 0) {
				close(fd);
				printf("executable(%s): %s\n", build_id, path);
				free(path);
			} else {
				errno = -fd;
				fprintf(stderr, "executable(%s) failed: %m\n",
					build_id);
				status = EXIT_FAILURE;
			}
			break;
		case 'd':
			fd = debuginfod_find_debuginfo(client,
						       (unsigned char *)build_id,
						       0, &path);
			if (fd >= 0) {
				close(fd);
				printf("debuginfo(%s): %s\n", build_id, path);
				free(path);
			} else {
				errno = -fd;
				fprintf(stderr, "debuginfo(%s) failed: %m\n",
					build_id);
				status = EXIT_FAILURE;
			}
			break;
		case 's':
			fd = debuginfod_find_source(client,
						    (unsigned char *)build_id,
						    0, optarg, &path);
			if (fd >= 0) {
				close(fd);
				printf("source(%s, %s): %s\n", build_id, optarg,
				       path);
				free(path);
			} else {
				errno = -fd;
				fprintf(stderr, "source(%s, %s) failed: %m\n",
					build_id, optarg);
				status = EXIT_FAILURE;
			}
			break;
		}
	}
	debuginfod_end(client);
	return status;
}
