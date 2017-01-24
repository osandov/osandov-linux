include config.mk

9p-modules-generator: 9p-modules-generator.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

.PHONY: install
install: 9p-modules-generator
	install -d $(DESTDIR)$(PREFIX)/lib/systemd/system-generators
	install -m755 9p-modules-generator $(DESTDIR)$(PREFIX)/lib/systemd/system-generators
	install -D -m644 10-shutdown.conf -t $(DESTDIR)$(PREFIX)/lib/systemd/system/systemd-udevd-control.socket.d
	install -D -m644 10-shutdown.conf -t $(DESTDIR)$(PREFIX)/lib/systemd/system/systemd-udevd-kernel.socket.d
	install -D -m644 10-shutdown.conf -t $(DESTDIR)$(PREFIX)/lib/systemd/system/systemd-udevd.service.d

.PHONY: clean
clean:
	rm -f 9p-modules-generator
