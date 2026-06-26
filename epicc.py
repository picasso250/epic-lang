"""
Epic v0 compiler CLI.

Usage:
    python epicc.py <file.ep>
"""

import argparse
import os
import sys

from codegen import compile_file
from lexer import LexError
from parser import ParseError


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="epicc.py",
        description="Epic v0 compiler",
    )
    parser.add_argument("input", help="input .ep source file")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if not os.path.exists(args.input):
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        return 1

    try:
        compile_file(args.input)
    except (LexError, ParseError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
