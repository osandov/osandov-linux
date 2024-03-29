# QEMU Notes

## Enabling KVM

If `/dev/kvm` doesn't exist, check dmesg for a line like:

```
[   24.781959] kvm: disabled by bios
```

Enable virtualization support in BIOS.

## Installing on QEMU from an ISO

```
vm.py run $VM -- -boot d -cdrom $ISO -no-reboot
```

You might need to run with graphics enabled as per below. Alternatively, if the installation CD allows you to pass command line arguments to the kernel, you can try `console=ttyS0,115200`.

## Graphics

By default, `vm.py` disables graphics with `-nodefaults` and `-nographic`. However, this can be reenabled with the `-vga` and `-display` flags. QEMU's default card is `cirrus`, but here's how to use the virtio VGA card:

```
-vga virtio -display sdl
```

## GRUB and TTY on Serial Console

Edit `/etc/default/grub`:

```
GRUB_CMDLINE_LINUX_DEFAULT="quiet console=ttyS0,115200"
# Remove GRUB_TERMINAL_{INPUT,OUTPUT}
GRUB_TERMINAL="console serial"
GRUB_SERIAL_COMMAND="serial --speed=115200"
```

And run `grub-mkconfig -o /boot/grub/grub.cfg`.

## Host Forwarding to QEMU

To forward port 2222 on the host to port 22 on the VM, start QEMU with:

```
-netdev user,id=vlan0,hostfwd=tcp::2222-:22 -device virtio-net,netdev=vlan0
```

## Storage Devices

NVMe

```
-device nvme,id=nvme,drive=nvme,serial=1337
-drive file=VM/nvme.qcow2,id=nvme,if=none,cache=none
```

SCSI

```
-device virtio-scsi-pci
-device scsi-hd,id=scsi,drive=scsi
-drive file=VM/scsi.qcow2,id=scsi,if=none,cache=none
```

ATA

```
-device ahci,id=ahci
-device ide-drive,drive=ata,bus=ahci.0
-drive file=VM/ata.qcow2,id=ata,if=none,cache=none
```

## Accessing the Host's USB Devices

A QEMU guest can access the host's USB devices. QEMU uses libusb to access the USB device node directly.

For example, to access my USB SATA enclosure, I do the following.

First, remove the disks from the host just to be safe:

```
$ for dev_delete in /sys/block/sd[b-e]/device/delete; do
	sudo sh -c "echo 1 > ${dev_delete}"
done
```

Then, find the bus and device number of the enclosure:

```
$ lsusb
...
Bus 002 Device 004: ID 152d:0567 JMicron Technology Corp. / JMicron USA Technology Corp. JMS567 SATA 6Gb/s bridge
...
$ bus=002
$ device=004
```

Make it owned by myself so I don't have to run QEMU as root:

```
$ sudo chown osandov:users "/dev/bus/usb/${bus}/${device}"
```

Then run QEMU with

```
-usb -device nec-usb-xhci,id=xhci -device "usb-host,hostbus=${bus},hostaddr=${device}"
```

`-usb` creates a USB 2 hub, `-device nec-usb-xhci,id=xhci` creates a USB 3 hub, and `-device usb-host` attaches the device.
