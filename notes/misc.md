# Miscellaneous Notes

## Disabling coredumps with systemd

systemd installs `/usr/lib/sysctl.d/50-coredump.conf` which sets the
`kernel.core_pattern` sysctl to use `systemd-coredump`. This is owned by the
package manager, so instead of editing it directly, mask it as follows:

```
ln -s /dev/null /etc/sysctl.d/50-coredump.conf
```
