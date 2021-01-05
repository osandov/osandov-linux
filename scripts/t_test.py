#!/usr/bin/env python3
# SPDX-FileCopyrightText: Omar Sandoval <osandov@osandov.com>
# SPDX-License-Identifier: MIT

import argparse
import numpy
import scipy.stats
import shutil
import subprocess
import sys
from typing import List, Tuple


class CustomFormatter(
    argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter
):
    pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="""Compare samples from two commands with a Student's t-test

This script does a statistical comparison of the output of two commands. It can
be used for A/B testing and performance benchmarking.

The simplest usage is that each command run outputs a single decimal value. We
can run the commands multiple times with -n to get enough samples to test. For
example, to compare the runtime of two commands:

  $ t_test.py -n 50 \\
          '/usr/bin/time -f %e my_command --fast 2>&1 > /dev/null' \\
          '/usr/bin/time -f %e my_command 2>&1 > /dev/null'

This alternates between running the first and second commands.

One can also compare multiple values at once by outputting tab-separated
columns of data. For example, to compare the runtime and user CPU time:

  $ t_test.py -n 50 \\
          '/usr/bin/time -f "%e\\\\t%U" my_command --fast 2>&1 > /dev/null' \\
          '/usr/bin/time -f "%e\\\\t%U" my_command 2>&1 > /dev/null'

Each run may also output multiple lines of samples. For example, this has
similar results to the first example above except that it won't alternate
between running the first and second commands:

  $ t_test.py \\
          'for i in $(seq 50); do /usr/bin/time -f %e my_command --fast 2>&1 > /dev/null; done' \\
          'for i in $(seq 50); do /usr/bin/time -f %e my_command 2>&1 > /dev/null; done'

This is also useful for analyzing files with saved data:

  $ cat samples1
  0.3671926408542683
  0.3579949272201213
  0.3550197322542641
  ...
  $ cat samples2
  0.40051392410618175
  0.3253259172893258
  0.4134108200990581
  ...
  $ t_test.py 'cat samples1 'cat samples2'

A t-test tests the null hypothesis that the means of two populations are equal
based on samples from the two populations. If the difference between the
samples is determined to be statistically significant, we REJECT the null
hypothesis. In this case, it is likely that the two populations are different.
If the difference is not statistically significant, we FAIL TO REJECT the null
hypothesis, and we cannot make any conclusions.

For each column, we report the mean, standard deviation, minimum, maximum, and
median of the samples from each command. We also report the difference of the
means of the commands and the t-value and p-value of the t-test. If the
commands differ significantly, we report the relation.
""",
        formatter_class=CustomFormatter,
    )
    parser.add_argument(
        "-n",
        "--repeat",
        type=int,
        default=1,
        metavar="N",
        help="number of times to run each command",
    )
    parser.add_argument(
        "-a",
        "--significance-level",
        type=float,
        default=0.05,
        metavar="A",
        help="maximum p-value considered statistically significant",
    )
    parser.add_argument(
        "--pre",
        type=str,
        metavar="COMMAND",
        help="shell command to run before each command",
    )
    parser.add_argument(
        "--post",
        type=str,
        metavar="COMMAND",
        help="shell command to run after each command",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="print all samples"
    )
    parser.add_argument(
        "--progress",
        choices=("auto", "always", "never"),
        default="auto",
        help="display a progress bar",
    )
    parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="colorize results",
    )
    parser.add_argument("command1", help="first shell command")
    parser.add_argument("command2", help="second shell command")
    args = parser.parse_args()

    runs = 2 * args.repeat

    if args.progress == "auto":
        progress = sys.stderr.isatty()
    else:
        progress = args.progress == "always"
    if progress:
        runs_columns = len(str(runs))
        reserved_columns = 2 * runs_columns + 4

        def print_progress_bar(i: int) -> None:
            columns = shutil.get_terminal_size().columns
            line = "\r"
            if columns > reserved_columns:
                bar_columns = columns - reserved_columns
                filled_columns = int(bar_columns * (i / runs))
                empty_columns = bar_columns - filled_columns
                line += "[" + filled_columns * "#" + empty_columns * "-" + "] "
            line += f"{i:>{runs_columns}}/{runs}"
            sys.stderr.write(line)

    else:

        def print_progress_bar(i: int) -> None:
            pass

    if args.color == "auto":
        color = sys.stdout.isatty()
    else:
        color = args.color == "always"
    if color:

        def red(s: str) -> str:
            return "\033[31m" + s + "\033[0m"

        def green(s: str) -> str:
            return "\033[32m" + s + "\033[0m"

        def bold(s: str) -> str:
            return "\033[1m" + s + "\033[0m"

    else:
        red = green = bold = lambda s: s

    commands = args.command1, args.command2
    populations: List[Tuple[List[float], List[float]]] = []
    for i in range(runs):
        print_progress_bar(i)

        if args.pre is not None:
            subprocess.check_call(args.pre, shell=True)

        output = subprocess.check_output(commands[i % 2], shell=True, text=True)
        for line in output.splitlines():
            for j, token in enumerate(line.split("\t")):
                if token:
                    if len(populations) <= j:
                        populations.append(([], []))
                    populations[j][i % 2].append(float(token))

        if args.post is not None:
            subprocess.check_call(args.post, shell=True)
    if progress:
        sys.stderr.write("\r\033[K")

    for j, (samples1, samples2) in enumerate(populations, 1):
        if j > 1:
            print()
        if len(populations) > 1:
            print(f"POPULATION {j}:")
        means = numpy.mean(samples1), numpy.mean(samples2)
        for i, samples in enumerate((samples1, samples2), 1):
            print(f"Command {i}:")
            print(
                f"  n = {len(samples)} mean = {means[i - 1]:f} SD = {numpy.std(samples):f}"
            )
            print(
                f"  min = {numpy.min(samples):f} max = {numpy.max(samples):f} median = {numpy.median(samples):f}"
            )
            if args.verbose:
                print(
                    "  samples = ", ", ".join([f"{sample:f}" for sample in samples]),
                )

        result = scipy.stats.ttest_ind(samples1, samples2)

        print(f"Difference of sample means = {means[0] - means[1]:f}")
        print(f"Test statistic = {result.statistic:f}")
        if result.pvalue <= args.significance_level:
            rejected = bold("REJECTED") + ", "
            if means[0] < means[1]:
                rejected += green("command1 < command2")
            else:
                rejected += red("command1 > command2")
        else:
            rejected = "FAILED TO REJECT"
        print(f"P(command1 = command2) = {result.pvalue:%} ({rejected})")


if __name__ == "__main__":
    main()
