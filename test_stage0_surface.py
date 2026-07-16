#!/usr/bin/env python3
"""Intent tests for the frozen Epic v0 declaration surface."""

from lexer import LexError, lex
from parser import ParseError, Parser


def parse(source):
    return Parser(lex(source)).parse_program()


def expect_rejected(source):
    try:
        parse(source)
    except (LexError, ParseError):
        return
    raise AssertionError(f"source unexpectedly accepted:\n{source}")


def main():
    program = parse("type Point {\nx: i64\n}\nfun main(): void {\n}\n")
    assert len(program.structs) == 1
    assert program.structs[0].name == "Point"

    expect_rejected("struct Point {\nx: i64\n}\nfun main(): void {\n}\n")
    expect_rejected("type Expr = Lit | Add\nfun main(): void {\n}\n")
    print("stage-0 surface passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
