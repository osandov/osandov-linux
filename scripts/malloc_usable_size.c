// SPDX-FileCopyrightText: Omar Sandoval <osandov@osandov.com>
// SPDX-License-Identifier: MIT

#include <malloc.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>

int main(void)
{
	bool have_prev = false;
	size_t prev_start;
	size_t prev_usable_size;

	void *buf = malloc(0);
	if (buf) {
		have_prev = true;
		prev_start = 0;
		prev_usable_size = malloc_usable_size(buf);
		free(buf);
	} else {
		puts("0 -> null");
	}

	size_t end = 262144;
	for (size_t i = 1; i <= end; i++) {
		void *buf = malloc(i);
		if (!buf) {
			perror("malloc");
			return EXIT_FAILURE;
		}
		size_t usable_size = malloc_usable_size(buf);
		free(buf);
		if (have_prev && usable_size != prev_usable_size) {
			if (i == prev_start + 1)
				printf("%zu -> %zu\n", prev_start, prev_usable_size);
			else
				printf("%zu..%zu -> %zu\n", prev_start, i - 1, prev_usable_size);
		}
		if (!have_prev || usable_size != prev_usable_size) {
			have_prev = true;
			prev_start = i;
			prev_usable_size = usable_size;
		}
	}
	if (have_prev) {
		if (end == prev_start)
			printf("%zu -> %zu\n", prev_start, prev_usable_size);
		else
			printf("%zu..%zu -> %zu\n", prev_start, end, prev_usable_size);
	}
	return EXIT_SUCCESS;
}
