#!/usr/bin/env python3
"""
Python-only tests for the stable lexer dump format:
line<TAB>kind<TAB>len<TAB>source_spelling.
"""

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))
sys.path.insert(0, os.path.join(ROOT_DIR, "bootstrap"))
from lexer import dump_tokens, lex


def test_basic_dump_format():
    assert dump_tokens(lex("fun main(): i64\n")) == (
        "1\tFUN\t3\tfun\n"
        "1\tID\t4\tmain\n"
        "1\tLPAREN\t1\t(\n"
        "1\tRPAREN\t1\t)\n"
        "1\tCOLON\t1\t:\n"
        "1\tID\t3\ti64\n"
        "1\tNEWLINE\t2\t\\n\n"
    )


def test_string_value_is_decoded_but_dump_uses_source_spelling():
    tokens = lex('"hello\\nworld"')
    assert tokens[0][1] == "hello\nworld"
    assert tokens[0][3] == "hello\\nworld"
    assert dump_tokens(tokens) == "1\tSTRING\t12\thello\\nworld\n"


def test_string_dump_preserves_tabs_as_source_spelling():
    assert dump_tokens(lex('"a\\t\\\\b"')) == "1\tSTRING\t6\ta\\t\\\\b\n"


def test_fstring_dump_linearized_from_source_spelling():
    tokens = lex('f"a\\n{ name }!"')
    assert tokens[0][1][0] == ("text", "a\n", "a\\n")
    assert tokens[0][1][1] == ("expr", "name", "name")
    assert dump_tokens(tokens) == (
        "1\tFSTRING_BEGIN\t0\t\n"
        "1\tFSTRING_TEXT\t3\ta\\n\n"
        "1\tFSTRING_EXPR\t4\tname\n"
        "1\tFSTRING_TEXT\t1\t!\n"
        "1\tFSTRING_END\t0\t\n"
    )


def test_char_dump_uses_decimal_byte_value():
    assert dump_tokens(lex("'\\n'\n")) == (
        "1\tCHAR\t2\t10\n"
        "1\tNEWLINE\t2\t\\n\n"
    )


def test_number_dump_uses_source_digits():
    assert dump_tokens(lex("42\n")) == (
        "1\tNUMBER\t2\t42\n"
        "1\tNEWLINE\t2\t\\n\n"
    )


def main():
    test_basic_dump_format()
    test_string_value_is_decoded_but_dump_uses_source_spelling()
    test_string_dump_preserves_tabs_as_source_spelling()
    test_fstring_dump_linearized_from_source_spelling()
    test_char_dump_uses_decimal_byte_value()
    test_number_dump_uses_source_digits()
    print("  PASS  lexer dump format")


if __name__ == "__main__":
    main()
