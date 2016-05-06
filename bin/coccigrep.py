#!/usr/bin/env python3

import argparse
import collections
import enum
import re
import subprocess
import sys
import tempfile

Token = collections.namedtuple('Token', ['type', 'value'])
TokenType = enum.Enum('TokenType', [
    'lparen', 'rparen', 'dot', 'equals',
    'keyword', 'identifier',
])
Keyword = enum.Enum('Keyword', ['struct', 'union', 'enum'])

TypeSpec = collections.namedtuple('TypeSpec', ['type', 'name'])
SpecType = enum.Enum('SpecType', ['struct', 'union', 'enum', 'typedef'])

Member = collections.namedtuple('Member', ['type', 'name'])

Assignment = collections.namedtuple('Assignment', ['member'])

identifier_re = re.compile(r'[A-Z_a-z][0-9A-Z_a-z]*')
whitespace_re = re.compile(r'\s*')


GrepLine = collections.namedtuple('GrepLine', ['file', 'number', 'contents', 'is_context'])


class ParseError(Exception):
    pass


class PatternParser:
    def __init__(self, pattern):
        self._pattern = pattern
        self._pos = 0

    def eof(self):
        return self._pos >= len(self._pattern)

    def parse(self):
        result = self.parse_pattern()
        self.parse_whitespace()
        if not self.eof():
            raise ParseError
        return result

    def parse_pattern(self):
        pos = self._pos
        token = self.parse_token()
        if token.type == TokenType.lparen:
            # type-spec
            type_spec = self.parse_type_spec()
            token = self.parse_token()
            if token.type != TokenType.rparen:
                raise ParseError

            self.parse_whitespace()
            if self.eof():
                return type_spec

            # member
            token = self.parse_token()
            if token.type != TokenType.dot:
                raise ParseError
            identifier = self.parse_identifier()
            member = Member(type=type_spec, name=identifier)

            self.parse_whitespace()
            if self.eof():
                return member

            # assignment
            token = self.parse_token()
            if token.type != TokenType.equals:
                raise ParseError
            return Assignment(member=member)
        else:
            self._pos = pos
            return self.parse_type_spec()

    def parse_identifier(self):
        token = self.parse_token()
        if token.type != TokenType.identifier:
            raise ParseError
        return token.value

    def parse_token(self):
        self.parse_whitespace()
        if self.eof():
            raise ParseError

        if self._pattern[self._pos] == '(':
            self._pos += 1
            return Token(type=TokenType.lparen, value=None)
        elif self._pattern[self._pos] == ')':
            self._pos += 1
            return Token(type=TokenType.rparen, value=None)
        elif self._pattern[self._pos] == '.':
            self._pos += 1
            return Token(type=TokenType.dot, value=None)
        elif self._pattern[self._pos] == '=':
            self._pos += 1
            return Token(type=TokenType.equals, value=None)

        match = identifier_re.match(self._pattern, self._pos)
        if match is None:
            raise ParseError
        self._pos = match.end()
        token = match.group()
        if token == 'struct':
            return Token(type=TokenType.keyword, value=Keyword.struct)
        elif token == 'union':
            return Token(type=TokenType.keyword, value=Keyword.union)
        elif token == 'enum':
            return Token(type=TokenType.keyword, value=Keyword.enum)
        else:
            return Token(type=TokenType.identifier, value=token)

    def parse_type_spec(self):
        """Returns TypeSpec."""
        token = self.parse_token()
        if token.type == TokenType.keyword:
            keyword = token.value
            if keyword in [Keyword.struct, Keyword.union, Keyword.enum]:
                identifier = self.parse_identifier()
                if keyword == Keyword.struct:
                    return TypeSpec(type=SpecType.struct, name=identifier)
                elif keyword == Keyword.union:
                    return TypeSpec(type=SpecType.union, name=identifier)
                elif keyword == Keyword.enum:
                    return TypeSpec(type=SpecType.enum, name=identifier)
            else:
                raise ParseError
        elif token.type == TokenType.identifier:
            return TypeSpec(type=SpecType.typedef, name=token.value)
        else:
            raise ParseError

    def parse_whitespace(self):
        match = whitespace_re.match(self._pattern, self._pos)
        self._pos = match.end()


def convert_pattern_to_spatch(pattern, outfile):
    if isinstance(pattern, Assignment):
        type_spec = pattern.member.type
    elif isinstance(pattern, Member):
        type_spec = pattern.type
    else:
        assert isinstance(pattern, TypeSpec)
        type_spec = pattern

    outfile.write('@@\n')
    if type_spec.type == SpecType.struct:
        outfile.write('struct {} var1;\n'.format(type_spec.name))
    elif type_spec.type == SpecType.union:
        outfile.write('union {} var1;\n'.format(type_spec.name))
    elif type_spec.type == SpecType.enum:
        outfile.write('enum {} var1;\n'.format(type_spec.name))
    elif type_spec.type == SpecType.typedef:
        outfile.write('{} var1;\n'.format(type_spec.name))
    outfile.write('@@\n')

    if isinstance(pattern, TypeSpec):
        outfile.write('* var1\n')
    elif isinstance(pattern, Member):
        outfile.write('* var1.{}\n'.format(pattern.name))
    elif isinstance(pattern, Assignment):
        outfile.write('* var1.{} = ...\n'.format(pattern.member.name))
    else:
        assert False


def diff_to_grep_lines(difffile):
    # TODO: handle paths with spaces
    fromfile_re = re.compile(r'--- (\S+)')
    tofile_re = re.compile(r'\+\+\+ (\S+)')
    hunkheader_re = re.compile(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@.*')
    hunk_re = re.compile(r'([ +-])(.*)')

    state = 'none'
    file = None
    start = None
    lineno = None
    for line in difffile:
        line = line.decode('utf-8')
        if line and line[-1] == '\n':
            line = line[:-1]
        if state == 'none':
            assert line.startswith('diff')
            state = 'fromfile'
        elif state == 'fromfile':
            match = fromfile_re.fullmatch(line)
            file = match.group(1)
            state = 'tofile'
        elif state == 'tofile':
            match = tofile_re.fullmatch(line)
            assert match is not None
            state = 'hunk'
        elif state == 'hunk':
            if line.startswith('diff'):
                state = 'fromfile'
                file = None
                start = None
                lineno = None
                continue

            match = hunkheader_re.fullmatch(line)
            if match:
                # We don't have to worry about the from-file vs. to-file line
                # numbers because all matches are always "-" lines.
                start = int(match.group(1))
                lineno = start
                continue

            match = hunk_re.fullmatch(line)
            if match.group(1) == ' ':
                yield GrepLine(file=file, number=lineno,
                               contents=match.group(2), is_context=True)
            elif match.group(1) == '-':
                yield GrepLine(file=file, number=lineno,
                               contents=match.group(2), is_context=False)
            else:
                assert False
            lineno += 1
        else:
            assert False


def output_grep_lines(grep_lines, args):
    if args.color == 'always' or (args.color == 'auto' and sys.stdout.isatty()):
        def color(s, c):
            return '\033[{}m{}\033[0m'.format(c, s)
    else:
        def color(s, c):
            return s

    if args.group:
        first_file = True
        first_hunk = None

        prev_file = None
        prev_lineno = None

    for line in grep_lines:
        grep_line = {
            'path': color(line.file, args.color_path),
            'number': color(line.number, args.color_line_number),
            'contents': line.contents,
        }

        if args.group:
            if line.file != prev_file:
                if not first_file:
                    print()
                first_file = False
                print(grep_line['path'])
                first_hunk = True
                prev_lineno = None
            if prev_lineno is None or line.number != prev_lineno + 1:
                if not first_hunk:
                    print('--')
                first_hunk = False

            if args.numbers:
                line_number = color(line.number, args.color_line_number)
                if line.is_context:
                    format = '{number}-{contents}'
                else:
                    format = '{number}:{contents}'
            else:
                format = '{contents}'

            prev_file = line.file
            prev_lineno = line.number
        else:
            if args.numbers:
                if line.is_context:
                    format = '{path}-{number}-{contents}'
                else:
                    format = '{path}:{number}:{contents}'
            else:
                if line.is_context:
                    format = '{path}-{contents}'
                else:
                    format = '{path}:{contents}'
        print(format.format(**grep_line))


def main():
    parser = argparse.ArgumentParser(
        description='Search for semantic PATTERN in each PATH or the current working directory'
    )
    parser.add_argument('pattern', metavar='PATTERN', help='semantic pattern')
    parser.add_argument(
        'path', metavar='PATH', nargs='*',
        help='file or directory to search in')

    parser.add_argument('--color', choices=['never', 'always', 'auto'],
                        default='auto')
    parser.add_argument('--nogroup', dest='group', action='store_false')
    parser.add_argument('--nonumbers', dest='numbers', action='store_false',
                        help='disable line numbers')

    parser.add_argument('-C', '--context', type=int, default=2)

    parser.add_argument('--color-path', type=str, default='34')
    parser.add_argument('--color-line-number', type=str, default='32')

    args = parser.parse_args()

    pattern = PatternParser(args.pattern).parse()

    with tempfile.NamedTemporaryFile(mode='w', suffix='.cocci') as spatch:
        convert_pattern_to_spatch(pattern, spatch)
        spatch.flush()
        spatch_args = [
            'spatch', '--very-quiet', '--sp-file', spatch.name,
            '-U', str(args.context),
        ]
        if args.path:
            spatch_args.extend(args.path)
        else:
            spatch_args.append('.')
        spatch_cmd = subprocess.Popen(spatch_args, stdout=subprocess.PIPE)
        grep_lines = diff_to_grep_lines(spatch_cmd.stdout)
        output_grep_lines(grep_lines, args)
        if spatch_cmd.wait() != 0:
            raise subprocess.CalledProcessError(cmd.returncode, cmd.args)


if __name__ == '__main__':
    main()
