#!/usr/bin/env python3

import argparse
import ast
import collections
import enum
import io
import linecache
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

SpatchMatch = collections.namedtuple('SpatchMatch', [
    'file', 'current_element', 'line', 'column', 'line_end', 'column_end',
])
GrepLine = collections.namedtuple('GrepLine', [
    'file', 'line', 'contents', 'is_context', 'match_start', 'match_end',
])


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

    if type_spec.type == SpecType.struct:
        type_str = 'struct {}'.format(type_spec.name)
    elif type_spec.type == SpecType.union:
        type_str = 'union {}'.format(type_spec.name)
    elif type_spec.type == SpecType.enum:
        type_str = 'enum {}'.format(type_spec.name)
    elif type_spec.type == SpecType.typedef:
        type_str = type_spec.name

    if isinstance(pattern, Member):
        outfile.write("""\
@rule1@
position p1;
expression E1;
{type} v1;
@@
v1.{member}@E1@p1
@script:python@
p1 << rule1.p1;
@@
print(repr(tuple([p1[0].file, p1[0].current_element, int(p1[0].line),
                  int(p1[0].column), int(p1[0].line_end),
                  int(p1[0].column_end)])))
""".format(type=type_str, member=pattern.name))
        pass
    else:
        assert False, "TODO"


def spatch_matches(file):
    for line in file:
        yield SpatchMatch(*ast.literal_eval(line))


def spatch_matches_to_grep_lines(matches, args):
    def context(file, lines):
        for line in lines:
            contents = linecache.getline(file, line)
            if contents:
                if contents[-1] == '\n':
                    contents = contents[:-1]
                yield GrepLine(file=file, line=line, contents=contents,
                               is_context=True, match_start=None,
                               match_end=None)

    last_file = None
    last_line = None
    for match in matches:
        if match.file != last_file:
            if last_file is not None:
                # Context after from the last match in the previous file.
                yield from context(
                    last_file, range(last_line + 1, last_line + args.after + 1))
            last_line = 0
        else:
            # Context after the previous match
            yield from context(
                match.file, range(last_line + 1, min(last_line + args.after + 1,
                                                     match.line - args.before)))

        # Context before this match
        yield from context(
            match.file, range(max(last_line + 1, match.line - args.before), match.line))

        # The match itself
        for line in range(match.line, match.line_end + 1):
            contents = linecache.getline(match.file, line)
            if contents and contents[-1] == '\n':
                contents = contents[:-1]
            if line == match.line:
                match_start = match.column
            else:
                match_start = 0
            if line == match.line_end:
                match_end = match.column_end
            else:
                match_end = None
            yield GrepLine(file=match.file, line=line, contents=contents,
                           is_context=False, match_start=match_start,
                           match_end=match_end)

        last_file = match.file
        last_line = match.line_end

    if last_file is not None:
        # Context after from the last match in the last file
        yield from context(
            last_file, range(last_line + 1, last_line + args.after + 1))


def output_grep_lines(grep_lines, args):
    if args.color == 'always' or (args.color == 'auto' and sys.stdout.isatty()):
        def color(s, c):
            return '\033[{}m{}\033[0m'.format(c, s)
    else:
        def color(s, c):
            return s

    def color_line_number(s):
        return color(s, args.color_line_number)

    def color_match(s):
        return color(s, args.color_match)

    def color_path(s):
        return color(s, args.color_path)

    if args.group:
        first_file = True
        first_hunk = None

        prev_file = None
        prev_lineno = None

    for line in grep_lines:
        if line.is_context:
            contents = line.contents
        else:
            contents = (line.contents[:line.match_start] +
                        color_match(line.contents[line.match_start:line.match_end]) +
                        line.contents[line.match_end:])
        grep_line = {
            'path': color_path(line.file),
            'line': color_line_number(line.line),
            'contents': contents,
        }

        if args.group:
            if line.file != prev_file:
                if not first_file:
                    print()
                first_file = False
                print(grep_line['path'])
                first_hunk = True
                prev_lineno = None
            if prev_lineno is None or line.line != prev_lineno + 1:
                if not first_hunk:
                    print('--')
                first_hunk = False

            if args.numbers:
                line_number = color(line.line, args.color_line_number)
                if line.is_context:
                    format = '{line}-{contents}'
                else:
                    format = '{line}:{contents}'
            else:
                format = '{contents}'

            prev_file = line.file
            prev_lineno = line.line
        else:
            if args.numbers:
                if line.is_context:
                    format = '{path}-{line}-{contents}'
                else:
                    format = '{path}:{line}:{contents}'
            else:
                if line.is_context:
                    format = '{path}-{contents}'
                else:
                    format = '{path}:{contents}'
        print(format.format(**grep_line))


def main():
    class ContextAction(argparse.Action):
        def __call__(self, parser, namespace, values, option_string):
            setattr(namespace, 'after', values)
            setattr(namespace, 'before', values)

    parser = argparse.ArgumentParser(
        description='Search for semantic PATTERN in each PATH or the current working directory'
    )
    parser.add_argument('pattern', metavar='PATTERN', help='semantic pattern')
    parser.add_argument(
        'path', metavar='PATH', nargs='*',
        help='file or directory to search in')

    parser.add_argument('--nogroup', dest='group', action='store_false')
    parser.add_argument('--nonumbers', dest='numbers', action='store_false',
                        help='disable line numbers')

    parser.add_argument('-C', '--context', type=int, action=ContextAction,
                        help='print context lines before and after match')
    parser.add_argument('-A', '--after', type=int, default=2,
                        help='print context lines after match')
    parser.add_argument('-B', '--before', type=int, default=2,
                        help='print context lines before match')

    parser.add_argument('--color', choices=['never', 'always', 'auto'],
                        default='auto')
    parser.add_argument('--color-line-number', type=str, default='32')
    parser.add_argument('--color-match', type=str, default='103')
    parser.add_argument('--color-path', type=str, default='34')

    args = parser.parse_args()

    pattern = PatternParser(args.pattern).parse()

    with tempfile.NamedTemporaryFile(mode='w', suffix='.cocci') as spatch:
        convert_pattern_to_spatch(pattern, spatch)
        spatch.flush()
        spatch_args = [
            'spatch', '--very-quiet', '--sp-file', spatch.name,
        ]
        if args.path:
            spatch_args.extend(args.path)
        else:
            spatch_args.append('.')
        with subprocess.Popen(spatch_args, stdout=subprocess.PIPE) as spatch_proc, \
                io.TextIOWrapper(spatch_proc.stdout) as f:
            matches = spatch_matches(f)
            grep_lines = spatch_matches_to_grep_lines(matches, args)
            output_grep_lines(grep_lines, args)
        if spatch_proc.returncode != 0:
            raise subprocess.CalledProcessError(spatch_proc.returncode, spatch_proc.args)


if __name__ == '__main__':
    main()
