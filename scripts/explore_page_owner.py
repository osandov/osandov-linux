#!/usr/bin/env python3

import argparse
from collections import Counter
import re
import sys


def humanize(n, precision=1):
    n = float(n)
    for unit in ['', 'k', 'M', 'G', 'T', 'P', 'E', 'Z']:
        if abs(n) < 1024:
            break
        n /= 1024
    else:
        unit = 'Y'
    if n.is_integer():
        precision = 0
    return "%.*f%sB" % (precision, n, unit)


def sort_stack_traces(file):
    stack_traces = Counter()
    current_stack_trace = []
    current_size = None
    for line in file:
        if line.startswith('PFN'):
            continue
        match = re.match(r'Page allocated via order (\d+)', line)
        if match:
            if current_stack_trace:
                stack_traces[tuple(reversed(current_stack_trace))] += current_size
                current_stack_trace.clear()
                current_size = None
            current_size = 4096 << int(match.group(1))
        elif line != '\n':
            match = re.match(r'\s*([^+\s]+)', line)
            if match.group(1) != '__set_page_owner':
                current_stack_trace.append(match.group(1))
    if current_stack_trace:
        stack_traces[tuple(reversed(current_stack_trace))] += current_size
        current_stack_trace.clear()
    return stack_traces


def explore(stack_traces, level, name=None):
    callees = Counter()
    for stack_trace, size in stack_traces.items():
        if level < len(stack_trace):
            callees[stack_trace[level]] += size
    total_size = sum(stack_traces.values())
    callee_size = sum(callees.values())
    sorted_callees = callees.most_common()
    while True:
        if name is None:
            assert total_size == callee_size
            print(f'{humanize(total_size)} allocated total')
        else:
            print(f'{humanize(total_size)} allocated from {name}', end='')
            if total_size == callee_size:
                print()
            else:
                assert total_size > callee_size
                print(f' ({humanize(total_size - callee_size)} directly)')
        for i, (func, size) in enumerate(sorted_callees, 1):
            print(f'{i}: {func} allocated {humanize(size)}')

        response = input('> ')
        if not response:
            continue
        elif response in {'exit', 'q', 'quit'}:
            sys.exit()
        elif response == 'up':
            if name is not None:
                return
        try:
            i = int(response)
        except ValueError:
            print('Invalid index', file=sys.stderr)
            continue
        if i < 1 or i > len(sorted_callees):
            print('Out of bounds index', file=sys.stderr)
            continue
        func = sorted_callees[i - 1][0]
        new_stack_traces = Counter({
            stack_trace: size for stack_trace, size in stack_traces.items()
            if level < len(stack_trace) and stack_trace[level] == func
        })
        explore(new_stack_traces, level + 1, func)


def main():
    parser = argparse.ArgumentParser(
        description='explore page owners by callchain')
    parser.add_argument(
        'page_owner', metavar='PAGE_OWNER',
        help='page owner file (i.e., /sys/kernel/debug/page_owner or a saved copy)')
    args = parser.parse_args()

    print('Sorting stack traces...')
    with open(args.page_owner, 'r') as f:
        stack_traces = sort_stack_traces(f)
    explore(stack_traces, level=0)


if __name__ == '__main__':
    main()
