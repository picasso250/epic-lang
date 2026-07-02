"""
Python-only tests for the stable lexer dump format (line<TAB>kind<TAB>escaped_value).

Run: python -m pytest test_lexer_dump_format.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "bootstrap"))
from lexer import dump_tokens, lex, escape_dump_value


def test_escape_newline():
    assert escape_dump_value("\n") == "\\n"


def test_escape_tab():
    assert escape_dump_value("\t") == "\\t"


def test_escape_backslash():
    assert escape_dump_value("\\") == "\\\\"


def test_escape_carriage_return():
    assert escape_dump_value("\r") == "\\r"


def test_escape_nul():
    assert escape_dump_value("\0") == "\\0"


def test_escape_printable_ascii_left_as_is():
    assert escape_dump_value("abc123") == "abc123"


def test_escape_nonprintable_byte():
    assert escape_dump_value("\x01") == "\\x01"
    assert escape_dump_value("\x7f") == "\\x7f"


def test_escape_int():
    assert escape_dump_value(42) == "42"


def test_basic_dump_format():
    assert dump_tokens(lex("fun main(): i64\n")) == (
        "1\tFUN\tfun\n"
        "1\tID\tmain\n"
        "1\tLPAREN\t(\n"
        "1\tRPAREN\t)\n"
        "1\tCOLON\t:\n"
        "1\tID\ti64\n"
        "1\tNEWLINE\t\\n\n"
    )


def test_string_dump_escapes():
    assert dump_tokens(lex('"a\\n\\t\\\\b"')) == (
        "1\tSTRING\ta\\n\\t\\\\b\n"
    )


def test_fstring_dump_linearized():
    assert dump_tokens(lex('f"hello {name}!"')) == (
        "1\tFSTRING_BEGIN\t\n"
        "1\tFSTRING_TEXT\thello \n"
        "1\tFSTRING_EXPR\tname\n"
        "1\tFSTRING_TEXT\t!\n"
        "1\tFSTRING_END\t\n"
    )


def test_char_dump():
    assert dump_tokens(lex("'a'\n")) == (
        "1\tCHAR\t97\n"
        "1\tNEWLINE\t\\n\n"
    )


def test_number_dump():
    assert dump_tokens(lex("42\n")) == (
        "1\tNUMBER\t42\n"
        "1\tNEWLINE\t\\n\n"
    )
