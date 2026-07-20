#!/usr/bin/env python3
"""Intent tests for the frozen Epic v0 declaration surface."""

from pathlib import Path
import tempfile

from ast_nodes import EmbedNode
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

    parse("fun choose(x: i64): i64 {\nfor x {\nret x\n}\nret 0\n}\n")
    expect_rejected("fun main(): void {\nreturn\n}\n")
    expect_rejected("fun main(): void {\nwhile 1 {\n}\n}\n")

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = root / "main.ep"
        resource = root / "asset.bin"
        resource.write_bytes(b"A\x00B")
        program = Parser(
            lex('fun main(): void {\nlet data = embed("asset.bin")\n}\n'),
            str(source),
        ).parse_program()
        embedded = program.funcs[0].body.stmts[0].value
        assert isinstance(embedded, EmbedNode)
        assert embedded.data == b"A\x00B"
        try:
            Parser(
                lex('fun main(): void {\nlet data = embed("missing.bin")\n}\n'),
                str(source),
            ).parse_program()
        except ParseError as error:
            assert "embed file not found: missing.bin" in str(error)
        else:
            raise AssertionError("missing embed file unexpectedly accepted")
    print("stage-0 surface passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
