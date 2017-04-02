.PHONY: install
install:
	install -D -m755 vm-modules-mounter.sh -t $(DESTDIR)/usr/bin
	install -D -m644 vm-modules-mounter.service -t $(DESTDIR)/usr/lib/systemd/system
	install -D -m644 10-shutdown.conf -t $(DESTDIR)/usr/lib/systemd/system/systemd-udevd-control.socket.d
	install -D -m644 10-shutdown.conf -t $(DESTDIR)/usr/lib/systemd/system/systemd-udevd-kernel.socket.d
	install -D -m644 10-shutdown.conf -t $(DESTDIR)/usr/lib/systemd/system/systemd-udevd.service.d
