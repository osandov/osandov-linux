"""
Library for writing Python utilities that can also output their shell script
equivalents in dry-run mode.
"""

import shlex
import subprocess


class Shlib:
    def __init__(self, dry_run=False):
        self._dry_run = dry_run
        if self._dry_run:
            print('#!/bin/sh')
            print('')
            print('set -e')

    def comment(self, comment):
        """
        Output something only if in dry-run mode.
        """
        if self._dry_run:
            print(comment)

    def blank(self):
        """
        Output a blank line only if in dry-run mode.
        """
        if self._dry_run:
            print()

    @staticmethod
    def _to_heredoc(cmd, input, output_path=None):
        shell_cmd = [cmd, ' << "EOF"']
        if output_path is not None:
            shell_cmd.append(' > {}'.format(shlex.quote(output_path)))
        shell_cmd.append('\n')

        lines = input.splitlines(keepends=True)
        for line in input.splitlines(keepends=True):
            if line == 'EOF\n':
                assert False, 'TODO: heredoc containing EOF'
            elif len(line) == 0 or line[-1] != '\n':
                assert False, 'TODO: line not ending in newline'
            else:
                shell_cmd.append(line)
        shell_cmd.append('EOF')
        return ''.join(shell_cmd)

    def call(self, cmd, input=None, shell=False):
        if shell and input is not None:
            raise ValueError('shell cannot be combined with input')
        if input is not None:
            assert len(input) > 0 and input[-1] == '\n'  # Hack for now
        if self._dry_run:
            if not shell:
                cmd = ' '.join(shlex.quote(arg) for arg in cmd)
                if input is not None:
                    cmd = self._to_heredoc(cmd, input)
            print(cmd)
        else:
            subprocess.run(cmd, shell=shell, input=input, check=True,
                           universal_newlines=True)

    def write_file(self, path, contents):
        if self._dry_run:
            print(self._to_heredoc('cat', contents, path))
        else:
            with open(path, 'w') as f:
                f.write(contents)
