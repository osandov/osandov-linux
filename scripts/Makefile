all: my_kdump_load swapme

my_kdump_load: my_kdump_load.c
	$(CC) -Wall -O2 -o $@ $<

swapme: swapme.c
	$(CC) -Wall -O2 -o $@ $<
