all: btrfs_ino_lookup my_kdump_load swapme

btrfs_ino_lookup: btrfs_ino_lookup.c
	$(CC) -Wall -O2 -o $@ $<

my_kdump_load: my_kdump_load.c
	$(CC) -Wall -O2 -o $@ $<

swapme: swapme.c
	$(CC) -Wall -O2 -o $@ $<
