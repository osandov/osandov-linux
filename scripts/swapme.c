#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/types.h>

#define MEMORY_CGROUP "/sys/fs/cgroup/memory/swapme"

struct mapping {
	void *next;
	uintptr_t this[];
};

static int oprintf(const char *path, const char *format, ...)
{
	va_list ap;
	int fd;
	int ret;

	fd = open(path, O_WRONLY | O_TRUNC);
	if (fd == -1) {
		perror("open");
		return -1;
	}
	va_start(ap, format);
	ret = vdprintf(fd, format, ap);
	va_end(ap);
	if (ret < 0) {
		perror("vdprintf");
		return -1;
	}
	if (close(fd) == -1) {
		perror("close");
		return -1;
	}

	return 0;
}

static int create_memory_cgroup(unsigned long long limit_in_bytes)
{
	int ret;

	ret = rmdir(MEMORY_CGROUP);
	if (ret == -1 && errno != ENOENT) {
		perror("rmdir(" MEMORY_CGROUP ")");
		return -1;
	}

	ret = mkdir(MEMORY_CGROUP, 0777);
	if (ret == -1) {
		perror("mkdir(" MEMORY_CGROUP ")");
		return -1;
	}

	ret = oprintf(MEMORY_CGROUP "/memory.limit_in_bytes", "%llu\n",
		      limit_in_bytes);
	if (ret == -1) {
		perror("oprintf(memory.limit_in_bytes)\n");
		return -1;
	}

	ret = oprintf(MEMORY_CGROUP "/memory.swappiness", "100\n");
	if (ret == -1) {
		perror("oprintf(memory.swappiness)\n");
		return -1;
	}

	ret = oprintf(MEMORY_CGROUP "/tasks", "%ld\n", (long)getpid());
	if (ret == -1) {
		perror("oprintf(tasks)\n");
		return -1;
	}

	ret = oprintf("/proc/sys/vm/swappiness", "0\n");
	if (ret == -1) {
		perror("oprintf(/proc/sys/vm/swappiness)\n");
		return -1;
	}

	return 0;
}

int main(int argc, const char *argv[])
{
	long i, j;
	long sz, pagesize, num_pages, num_this;
	unsigned long long limit_in_bytes;
	struct mapping *ptr = NULL;

	if (argc != 3) {
		fprintf(stderr, "Usage: %s ALLOC_BYTES LIMIT_BYTES\n", argv[0]);
		return EXIT_FAILURE;
	}

	if (mlockall(MCL_CURRENT) == -1) {
		perror("mlockall");
		return EXIT_FAILURE;
	}

	sz = strtol(argv[1], NULL, 0);
	pagesize = sysconf(_SC_PAGESIZE);
	num_pages = (sz + pagesize - 1) / pagesize;
	num_this = (pagesize / sizeof(void *)) - 1;

	limit_in_bytes = strtoull(argv[2], NULL, 0);
	if (create_memory_cgroup(limit_in_bytes) == -1)
		return EXIT_FAILURE;

	for (i = 0; i < num_pages; i++) {
		struct mapping *tmp;

		printf("\rpages = %ld", i);
		fflush(stdout);

		tmp = mmap(NULL, pagesize, PROT_READ | PROT_WRITE,
			   MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
		if (tmp == MAP_FAILED) {
			printf("\n");
			perror("mmap");
			return EXIT_FAILURE;
		}

		tmp->next = ptr;
		for (j = 0; j < num_this; j++)
			tmp->this[j] = (uintptr_t)tmp + j;
		ptr = tmp;
	}
	printf("\rpages = %ld\n", num_pages);

	for (;;) {
		struct mapping *tmp;

		printf("press enter to check...");
		getchar();

		tmp = ptr;
		for (i = 0; tmp; i++) {
			printf("\rchecked %ld pages", i);
			fflush(stdout);
			if (tmp->next == tmp) {
				printf("\npage %p is corrupt: next = %p\n",
				       tmp, tmp->next);
				return EXIT_FAILURE;
			}
			for (j = 0; j < num_this; j++) {
				if (tmp->this[j] - j != (uintptr_t)tmp) {
					printf("\npage %p is corrupt: this[%ld] = 0x%" PRIxPTR "\n",
					       tmp, j, tmp->this[j]);
					return EXIT_FAILURE;
				}
			}
			tmp = tmp->next;
		}
		printf("\rchecked all pages\n");
	}

	return EXIT_SUCCESS;
}
