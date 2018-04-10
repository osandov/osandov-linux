To run QEMU: Install the qemu-arch-extra package. Download the initrd and
vmlinux from http://http.us.debian.org/debian/dists/jessie/main/installer-mips/current/images/malta/netboot/,
then run

```
qemu-system-mips \
	-M malta \
	-nographic \
	-m 2G \
	-kernel vmlinux* \
	-initrd initrd.gz
```

To build the big-endian toolchain, build and install the following Arch Linux
`PKGBUILD`s:


mips-linux-gnu-binutils:

```
_target=mips-linux-gnu
pkgname=$_target-binutils
pkgver=2.30
pkgrel=1
pkgdesc='A set of programs to assemble and manipulate binary and object files for the MIPS Linux target'
arch=(x86_64)
url='http://www.gnu.org/software/binutils/'
license=(GPL)
depends=(zlib)
source=(ftp://ftp.gnu.org/gnu/binutils/binutils-$pkgver.tar.bz2{,.sig})
sha1sums=('33d807f7fa680b00439eb5560acd0c2ef645e5f9'
          'SKIP')

prepare() {
  cd binutils-$pkgver
  sed -i "/ac_cpp=/s/\$CPPFLAGS/\$CPPFLAGS -O2/" libiberty/configure
}

build() {
  cd binutils-$pkgver

  ./configure --target=$_target \
              --with-sysroot=/usr/$_target \
              --prefix=/usr \
              --enable-multilib \
              --enable-interwork \
              --with-gnu-as \
              --with-gnu-ld \
              --disable-nls \
              --enable-ld=default \
              --enable-gold \
              --enable-plugins \
              --enable-deterministic-archives

  make
}

check() {
  cd binutils-$pkgver
  
  # unset LDFLAGS as testsuite makes assumptions about which ones are active
  # do not abort on errors - manually check log files
  make LDFLAGS="" -k check
}

package() {
  cd binutils-$pkgver

  make DESTDIR="$pkgdir" install

  # Remove file conflicting with host binutils and manpages for MS Windows tools
  rm "$pkgdir"/usr/share/man/man1/$_target-{dlltool,nlmconv,windres,windmc}*

  # Remove info documents that conflict with host version
  rm -r "$pkgdir"/usr/share/info
}
```

mips-linux-gnu-gcc:

```
_target=mips-linux-gnu
pkgname=$_target-gcc
_pkgname=gcc
pkgver=7.3.0
pkgrel=1
pkgdesc="The GNU Compiler Collection for the MIPS Linux target"
url="http://www.gnu.org/software/gcc/"
arch=('i686' 'x86_64')
license=('GPL')
depends=('libmpc' "$_target-binutils")
options=('!ccache' '!distcc' '!emptydirs' '!libtool' '!strip')
source=("ftp://ftp.gnu.org/gnu/gcc/gcc-${pkgver}/${_pkgname}-${pkgver}.tar.xz")
sha256sums=('832ca6ae04636adbb430e865a1451adf6979ab44ca1c8374f61fba65645ce15c')

prepare() {
  cd ${srcdir}/${_pkgname}-${pkgver}
  sed -i "/ac_cpp=/s/\$CPPFLAGS/\$CPPFLAGS -O2/" {libiberty,gcc}/configure
}

build() {
  cd ${srcdir}/${_pkgname}-${pkgver}

  ./configure \
    --target=$_target \
    --prefix=/usr \
    --with-sysroot=/usr/$_target \
    --with-native-system-header-dir=/include \
    --libexecdir=/usr/lib \
    --enable-languages=c,c++ \
    --enable-plugins \
    --disable-multilib \
    --disable-nls \
    --disable-shared \
    --disable-threads \
    --with-gnu-as \
    --with-gnu-ld \
    --without-headers

  make -j4 all-gcc "inhibit_libc=true"
}

package() {
  cd ${srcdir}/${_pkgname}-${pkgver}

  make DESTDIR=${pkgdir} install-gcc

  rm -r "$pkgdir"/usr/share/man/man7
  rm -r "$pkgdir"/usr/share/info
}
```

To cross-compile the kernel: 

```
cp arch/mips/configs/malta_defconfig .config
make ARCH=mips CROSS_COMPILE=mips-linux-gnu- menuconfig
#  -> Kernel Type -> High memory (y)
#  -> Endianess Selection (Big endian)
#  -> Enable loadable module support (n)
#  -> General Setup -> Initial RAM filesystem and RAM disk (initramfs/initrd) support (y)
#  -> File systems -> Btrfs filesystem support (y)
#  -> File systems -> Btrfs will run sanity tests upon loading (y)
make ARCH=mips CROSS_COMPILE=mips-linux-gnu- -j4 vmlinux
```

I also had to comment out `test_find_delalloc()` in `btrfs_test_extent_io()`;
it allocates too much memory.

To run with this kernel, point the QEMU `-kernel` flag at the compiled vmlinux.
