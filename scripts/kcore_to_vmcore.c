// Copyright (c) Facebook, Inc. and its affiliates.
// SPDX-License-Identifier: MIT

#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/types.h>

#include <libelf.h>

static const char *progname = "kcore_to_vmcore";

static void usage(bool error)
{
	fprintf(error ? stderr : stdout,
		"usage: %s OUTFILE [INFILE]\n"
		"\n"
		"Copy a kernel core dump from INFILE (which defaults to \"/proc/kcore\",\n"
		"i.e. a memory dump of the running system) to OUTFILE.\n"
		"\n"
		"Note that a dump of \"/proc/kcore\" is not self-consistent. The dump\n"
		"will race with changes happening in the running system.\n"
		"\n"
		"Options:\n"
		"  -h, --help   display this help message and exit\n",
		progname);
	exit(error ? EXIT_FAILURE : EXIT_SUCCESS);
}

static void print_libelf_error(void)
{
	fprintf(stderr, "%s\n", elf_errmsg(-1));
}

static bool include_phdr(const Elf64_Phdr *phdr)
{
	if (phdr->p_type == PT_NOTE)
		return true;
	if (phdr->p_type != PT_LOAD)
		return false;
	/*
	 * Only dump segments with a physical address: the direct mapping and
	 * the text mapping. New kernels set p_paddr to -1 for segments with an
	 * unknown physical address. Old kernels use 0. At least for x86, the
	 * kernel doesn't use physical address 0, so we can skip those, too.
	 *
	 * TODO: we should be more clever about the text mapping and make it
	 * reference the same file data as the direct mapping.
	 */
	return phdr->p_paddr && phdr->p_paddr != UINT64_MAX;
}

static int copy_data(int fd_in, loff_t off_in, int fd_out, loff_t off_out,
		     size_t len)
{
	char copy_buffer[128 * 1024];
	while (len) {
		ssize_t sret;
		size_t n = len < sizeof(copy_buffer) ? len : sizeof(copy_buffer);
		size_t bytes_read = 0;
		while (bytes_read < n) {
			sret = pread(fd_in, copy_buffer + bytes_read,
				     n - bytes_read, off_in);
			if (sret < 0) {
				if (errno == EINTR)
					continue;
				return sret;
			}
			if (sret == 0) {
				errno = ENODATA;
				return -1;
			}
			off_in += sret;
			bytes_read += sret;
		}
		size_t bytes_written = 0;
		while (bytes_written < n) {
			sret = pwrite(fd_out, copy_buffer + bytes_written,
				      n - bytes_written, off_out);
			if (sret < 0) {
				if (errno == EINTR)
					continue;
				return sret;
			}
			off_out += sret;
			bytes_written += sret;
		}
		len -= n;
	}
	return 0;
}

static bool kcore_to_vmcore64(int kcore_fd, Elf *kcore_elf, int vmcore_fd,
			      Elf *vmcore_elf)
{
	Elf64_Ehdr *kcore_ehdr = elf64_getehdr(kcore_elf);
	if (!kcore_ehdr) {
		print_libelf_error();
		return false;
	}
	Elf64_Ehdr *vmcore_ehdr = elf64_newehdr(vmcore_elf);
	if (!vmcore_ehdr) {
		print_libelf_error();
		return false;
	}

	memcpy(vmcore_ehdr->e_ident, kcore_ehdr->e_ident,
	       sizeof(vmcore_ehdr->e_ident));
	vmcore_ehdr->e_type = kcore_ehdr->e_type;
	vmcore_ehdr->e_machine = kcore_ehdr->e_machine;
	vmcore_ehdr->e_version = kcore_ehdr->e_version;
	vmcore_ehdr->e_entry = kcore_ehdr->e_entry;
	vmcore_ehdr->e_flags = kcore_ehdr->e_flags;

	vmcore_ehdr->e_version = EV_CURRENT;
	vmcore_ehdr->e_ehsize = sizeof(Elf64_Ehdr);
	vmcore_ehdr->e_phentsize = sizeof(Elf64_Phdr);

	size_t kcore_phdrnum;
	if (elf_getphdrnum(kcore_elf, &kcore_phdrnum) < 0) {
		print_libelf_error();
		return false;
	}
	if (kcore_phdrnum == 0) {
		fprintf(stderr, "/proc/kcore has no segments\n");
		return false;
	}
	const Elf64_Phdr *kcore_phdrs = elf64_getphdr(kcore_elf);
	if (!kcore_phdrs) {
		print_libelf_error();
		return false;
	}
	size_t vmcore_phdrnum = 0;
	uint64_t copy_bytes = 0;
	for (size_t i = 0; i < kcore_phdrnum; i++) {
		const Elf64_Phdr *phdr = &kcore_phdrs[i];
		if (!include_phdr(phdr))
			continue;
		vmcore_phdrnum++;
		copy_bytes += phdr->p_filesz;
	}

	if (vmcore_phdrnum == 0) {
		fprintf(stderr, "Found no segments to copy\n");
		return false;
	}
	fprintf(stderr, "Copying %zu segments, %" PRIu64 " bytes\n",
		vmcore_phdrnum, copy_bytes);

	Elf64_Phdr *vmcore_phdrs = elf64_newphdr(vmcore_elf, vmcore_phdrnum);
	int64_t size = elf_update(vmcore_elf, ELF_C_NULL);
	if (size < 0) {
		print_libelf_error();
		return false;
	}
	uint64_t offset = size;
	for (size_t i = 0, j = 0; i < kcore_phdrnum && j < vmcore_phdrnum; i++) {
		const Elf64_Phdr *kcore_phdr = &kcore_phdrs[i];
		if (!include_phdr(kcore_phdr))
			continue;

		if (kcore_phdr->p_align) {
			uint64_t remainder = offset % kcore_phdr->p_align;
			if (remainder)
				offset = offset + kcore_phdr->p_align - remainder;
		}

		Elf64_Phdr *vmcore_phdr = &vmcore_phdrs[j++];
		vmcore_phdr->p_type = kcore_phdr->p_type;
		vmcore_phdr->p_flags = kcore_phdr->p_flags;
		vmcore_phdr->p_offset = offset;
		vmcore_phdr->p_vaddr = kcore_phdr->p_vaddr;
		vmcore_phdr->p_paddr = kcore_phdr->p_paddr;
		vmcore_phdr->p_filesz = kcore_phdr->p_filesz;
		vmcore_phdr->p_memsz = kcore_phdr->p_memsz;
		vmcore_phdr->p_align = kcore_phdr->p_align;

		offset += vmcore_phdr->p_filesz;
	}

	if (elf_update(vmcore_elf, ELF_C_WRITE) < 0) {
		print_libelf_error();
		return false;
	}

	for (size_t i = 0, j = 0; i < kcore_phdrnum && j < vmcore_phdrnum; i++) {
		const Elf64_Phdr *kcore_phdr = &kcore_phdrs[i];
		if (!include_phdr(kcore_phdr))
			continue;
		Elf64_Phdr *vmcore_phdr = &vmcore_phdrs[j++];
		if (copy_data(kcore_fd, kcore_phdr->p_offset,
			      vmcore_fd, vmcore_phdr->p_offset,
			      kcore_phdr->p_filesz) < 0) {
			fprintf(stderr,
				"copying from kcore to vmcore failed: %m\n");
			return false;
		}
	}

	return true;
}

int main(int argc, char **argv)
{
	if (argv[0])
		progname = argv[0];
	struct option long_options[] = {
		{"help", no_argument, NULL, 'h'},
	};
	for (;;) {
		int c;

		c = getopt_long(argc, argv, "h", long_options, NULL);
		if (c == -1)
			break;

		switch (c) {
		case 'h':
			usage(false);
		default:
			usage(true);
		}
	}
	const char *kcore_path;
	if (optind == argc - 2)
		kcore_path = argv[optind + 1];
	else if (optind == argc - 1)
		kcore_path = "/proc/kcore";
	else
		usage(true);
	const char *vmcore_path = argv[optind];

	elf_version(EV_CURRENT);

	int status = EXIT_FAILURE;
	int kcore_fd = open(kcore_path, O_RDONLY);
	if (kcore_fd == -1) {
		perror(kcore_path);
		goto out;
	}

	Elf *kcore_elf = elf_begin(kcore_fd, ELF_C_READ, NULL);
	if (!kcore_elf) {
		print_libelf_error();
		goto out_kcore_fd;
	}

	int vmcore_fd = creat(vmcore_path, 0600);
	if (vmcore_fd == -1) {
		perror(vmcore_path);
		goto out_kcore_elf;
	}

	Elf *vmcore_elf = elf_begin(vmcore_fd, ELF_C_WRITE, NULL);
	if (!vmcore_elf) {
		print_libelf_error();
		goto out_vmcore_fd;
	}

	char *e_ident = elf_getident(kcore_elf, NULL);
	if (!e_ident) {
		print_libelf_error();
		goto out_vmcore_fd;
	}
	if (e_ident[EI_CLASS] != ELFCLASS64) {
		fprintf(stderr, "only 64-bit dumps are supported\n");
		goto out_vmcore_fd;
	}
	if (kcore_to_vmcore64(kcore_fd, kcore_elf, vmcore_fd, vmcore_elf))
		status = EXIT_SUCCESS;

out_vmcore_fd:
	close(vmcore_fd);
out_kcore_elf:
	elf_end(kcore_elf);
out_kcore_fd:
	close(kcore_fd);
out:
	return status;
}
