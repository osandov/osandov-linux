#!/usr/bin/env python3
# SPDX-FileCopyrightText: Omar Sandoval <osandov@osandov.com>
# SPDX-License-Identifier: MIT

import argparse
import itertools
import shutil
import subprocess
import sys
from typing import Iterator, List, Tuple
import warnings

import numpy
import scipy.stats


class CustomFormatter(
    argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter
):
    pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="""Compare samples from two commands with a Welch's t-test

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
        "--equal-variances",
        action="store_true",
        help="assume equal population variances and perform a Student's t-test instead",
    )

    order_group = parser.add_mutually_exclusive_group()
    order_group.add_argument(
        "--alternating",
        dest="order",
        action="store_const",
        const="alternating",
        default=argparse.SUPPRESS,
        help="alternate between running command1 and command2 (default)",
    )
    order_group.add_argument(
        "--consecutive",
        dest="order",
        action="store_const",
        const="consecutive",
        default=argparse.SUPPRESS,
        help="run command1 repeatedly and then run command2 repeatedly",
    )

    parser.add_argument(
        "-w",
        "--warmup",
        type=int,
        default=0,
        metavar="N",
        help="additional number of times to run each command before collecting data",
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
        help="display progress",
    )
    parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="colorize results",
    )

    parser.add_argument(
        "commands", metavar="command1", action="append", help="first shell command"
    )
    parser.add_argument(
        "commands", metavar="command2", action="append", help="second shell command"
    )
    args = parser.parse_args()

    runs: Iterator[Tuple[int, bool]]
    if getattr(args, "order", "alternating") == "alternating":
        runs = itertools.chain.from_iterable(
            itertools.chain(
                itertools.repeat(((0, False), (1, False)), args.warmup),
                itertools.repeat(((0, True), (1, True)), args.repeat),
            ),
        )
    else:  # args.order == "consecutive"
        runs = itertools.chain(
            itertools.repeat((0, False), args.warmup),
            itertools.repeat((0, True), args.repeat),
            itertools.repeat((1, False), args.warmup),
            itertools.repeat((1, True), args.repeat),
        )
    num_runs = 2 * args.warmup + 2 * args.repeat

    populations: List[Tuple[List[float], List[float]]] = []

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

    if args.progress == "auto":
        progress = sys.stdout.isatty()
    else:
        progress = args.progress == "always"

    if progress:
        num_runs_columns = len(str(num_runs))
        reserved_columns = 2 * num_runs_columns + 4

    prev_num_progress_lines = 0

    warnings.filterwarnings("error", category=RuntimeWarning)

    def print_progress(run: int) -> None:
        lines = []

        if progress:
            columns = shutil.get_terminal_size().columns
            if columns > reserved_columns:
                bar_columns = columns - reserved_columns
                filled_columns = int(bar_columns * (run / num_runs))
                empty_columns = bar_columns - filled_columns
                progress_bar = "[" + filled_columns * "#" + empty_columns * "-" + "] "
            else:
                progress_bar = ""
            progress_bar += f"{run:>{num_runs_columns}}/{num_runs}"
            lines.append(progress_bar)

        for j, (samples1, samples2) in enumerate(populations, 1):
            if j > 1:
                lines.append("")
            if len(populations) > 1:
                lines.append(f"POPULATION {j}:")
            means = [
                numpy.mean(samples1) if samples1 else None,
                numpy.mean(samples2) if samples2 else None,
            ]
            for i, samples in enumerate((samples1, samples2), 1):
                if samples:
                    lines.append(f"Command {i}:")
                    lines.append(
                        f"  n = {len(samples)} mean = {means[i - 1]:f} SD = {numpy.std(samples):f}"
                    )
                    lines.append(
                        f"  min = {numpy.min(samples):f} max = {numpy.max(samples):f} median = {numpy.median(samples):f}"
                    )
                    if args.verbose:
                        lines.append(
                            "  samples = "
                            + ", ".join([f"{sample:f}" for sample in samples])
                        )
            if means[0] is not None and means[1] is not None:
                lines.append(f"Difference of sample means = {means[0] - means[1]:f}")
                if run == num_runs:
                    try:
                        result = scipy.stats.ttest_ind(
                            samples1, samples2, equal_var=args.equal_variances
                        )
                    except RuntimeWarning as w:
                        lines.append("warning: " + str(w))
                    else:
                        lines.append(f"Test statistic = {result.statistic:f}")
                        if result.pvalue <= args.significance_level:
                            rejected = bold("REJECTED") + ", "
                            if means[0] < means[1]:
                                rejected += green("command1 < command2")
                            else:
                                rejected += red("command1 > command2")
                        else:
                            rejected = "FAILED TO REJECT"
                        lines.append(f"P(command1 = command2) = {result.pvalue:%} ({rejected})")

        if progress:
            nonlocal prev_num_progress_lines
            if prev_num_progress_lines:
                if prev_num_progress_lines == 1:
                    sys.stdout.write(f"\r\033[J")
                elif prev_num_progress_lines > 0:
                    sys.stdout.write(f"\r\033[{prev_num_progress_lines - 1}A\033[J")
            prev_num_progress_lines = sum(
                ((len(line) + columns - 1) // columns if line else 1) for line in lines
            )

        sys.stdout.write("\n".join(lines))

        if run == num_runs:
            sys.stdout.write("\n")
        else:
            sys.stdout.flush()

    if progress:
        sys.stdout.write("\0337")
    for i, (command_index, record) in enumerate(runs):
        if progress:
            print_progress(i)

        if args.pre is not None:
            subprocess.check_call(args.pre, shell=True)

        output = subprocess.check_output(
            args.commands[command_index], shell=True, universal_newlines=True
        )
        if record:
            for line in output.splitlines():
                for j, token in enumerate(line.split("\t")):
                    if token:
                        if len(populations) <= j:
                            populations.append(([], []))
                        populations[j][command_index].append(float(token))

        if args.post is not None:
            subprocess.check_call(args.post, shell=True)

    print_progress(num_runs)


if __name__ == "__main__":
    main()
