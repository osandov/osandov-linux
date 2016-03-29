include config.mk

9p-modules-generator: 9p-modules-generator.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

.PHONY: install
install: 9p-modules-generator
	install -d $(DESTDIR)$(PREFIX)/lib/systemd/system-generators
	install -m755 9p-modules-generator $(DESTDIR)$(PREFIX)/lib/systemd/system-generators

.PHONY: clean
clean:
	rm -f 9p-modules-generator
