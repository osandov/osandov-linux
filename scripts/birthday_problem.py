#!/usr/bin/env python3

import argparse
import math


def main():
    parser = argparse.ArgumentParser(
        description="Print the approximate probability of a birthday collision (or hash collision)"
    )
    parser.add_argument(
        "days",
        type=int,
        help="number of possible birthdays (alternatively, number of possible hash values or number of pigeonholes)",
    )
    parser.add_argument(
        "people",
        type=int,
        help="number of people (alternatively, number of hashes or number of pigeons)",
    )
    args = parser.parse_args()

    p = 1 - math.exp(-(args.people ** 2) / (2 * args.days))
    print(f"{p:%}")


if __name__ == "__main__":
    main()
