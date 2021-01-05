#!/bin/bash
# SPDX-FileCopyrightText: Omar Sandoval <osandov@osandov.com>
# SPDX-License-Identifier: MIT

set -e

git remote add history git://git.kernel.org/pub/scm/linux/kernel/git/history/history.git
git fetch -t history
cat >> .git/info/grafts << EOF
1da177e4c3f41524e886b7f1b8a0c1fc7321cac2 e7e173af42dbf37b1d946f9ee00219cb3b2bea6a
7a2deb32924142696b8174cdf9b38cd72a11fc96 379a6be1eedb84ae0d476afbc4b4070383681178
EOF
