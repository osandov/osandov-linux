#!/usr/bin/env python3

import argparse
import signal


def main():
    parser = argparse.ArgumentParser(
        description='decode a signal set in /proc/status')
    parser.add_argument('value', help='hexdecimal bitmask value')
    args = parser.parse_args()

    value = int(args.value, base=16)
    i = 1
    while value:
        if value & 1:
            try:
                print(signal.Signals(i).name)
            except ValueError:
                print(i)
        value >>= 1
        i += 1

if __name__ == '__main__':
    main()
