// SPDX-FileCopyrightText: Omar Sandoval <osandov@osandov.com>
// SPDX-License-Identifier: MIT

/*
 * Template for a benchmark that should run as many iterations as possible in
 * one second.
 */
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static volatile unsigned long long counter;

static void handler(int sig)
{
	/*
	 * Really we only need ceil(8 * sizeof(counter)) / log2(10)) + 1, but
	 * this is easier.
	 */
	char buf[8 * sizeof(counter) + 1];
	char *p = &buf[sizeof(buf)];
	unsigned long long n = counter;

	/* The printf() family is not async-signal-safe, but write() is. */
	*--p = '\n';
	while (n) {
		*--p = '0' + (n % 10);
		n /= 10;
	}
	write(STDOUT_FILENO, p, &buf[sizeof(buf)] - p);
	_exit(EXIT_SUCCESS);
}

int main(void)
{
	struct sigaction act = {
		.sa_handler = handler,
	};

	if (sigaction(SIGALRM, &act, NULL) == -1) {
		perror("sigaction");
		return EXIT_FAILURE;
	}
	alarm(1);
	for (;;)
		counter++;
}
