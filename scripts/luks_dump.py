#!/usr/bin/env python3
# SPDX-FileCopyrightText: Omar Sandoval <osandov@osandov.com>
# SPDX-License-Identifier: MIT

import argparse
import struct


def c_string(b):
    return b[:b.index(0)].decode('ascii')


def main():
    parser = argparse.ArgumentParser(description='dump LUKS header')
    parser.add_argument('dev', help='encrypted block device')
    parser.add_argument(
        '--all-key-slots', help='show all key slots, not just active ones')
    args = parser.parse_args()

    with open(args.dev, 'rb') as f:
        (
            magic,
            version,
            cipher_name,
            cipher_mode,
            hash_spec,
            payload_offset,
            key_bytes,
            mk_digest,
            mk_digest_salt,
            mk_digest_iter,
            uuid,
        ) = struct.unpack_from('>6sH32s32s32sII20s32sI40s', f.read(208))

        assert magic == b'LUKS\xba\xbe'
        assert version == 1
        print(f"""\
PHDR
  magic = {repr(magic)[2:-1]}
  version = {version}
  cipher_name = {c_string(cipher_name)}
  cipher_mode = {c_string(cipher_mode)}
  hash_spec = {c_string(hash_spec)}
  payload_offset = {payload_offset}
  key_bytes = {key_bytes}
  mk_digest = {mk_digest.hex()}
  mk_digest_salt = {mk_digest_salt.hex()}
  mk_digest_iter = {mk_digest_iter}
  uuid = {c_string(uuid)}""")

        for i, key_slot in enumerate(struct.iter_unpack('>II32sII', f.read(384)), 1):
            active, iterations, salt, key_material_offset, stripes = key_slot
            if args.all_key_slots or active == 0xac71f3:
                print(f"""\
  Key Slot {i}
    active = 0x{active:x}
    iterations = {iterations}
    salt = {salt.hex()}
    key_material_offset = {key_material_offset}
    stripes = {stripes}""")


if __name__ == '__main__':
    main()
