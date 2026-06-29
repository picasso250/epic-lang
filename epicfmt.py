#!/usr/bin/env python3
"""Indent-only formatter for Epic source files."""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path


def read_source(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as f:
        return f.read()


def write_source(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(text)


def brace_delta(line: str) -> tuple[int, int]:
    """Return (leading_closing_braces, net_brace_delta) outside literals/comments."""
    i = 0
    n = len(line)
    while i < n and line[i] in " \t":
        i += 1

    leading_closes = 0
    j = i
    while j < n and line[j] == "}":
        leading_closes += 1
        j += 1

    delta = 0
    in_string = False
    in_char = False
    escaped = False

    for ch in line[i:]:
        if escaped:
            escaped = False
            continue
        if ch == "\\" and (in_string or in_char):
            escaped = True
            continue
        if in_string:
            if ch == '"':
                in_string = False
            continue
        if in_char:
            if ch == "'":
                in_char = False
            continue
        if ch == "#":
            break
        if ch == '"':
            in_string = True
            continue
        if ch == "'":
            in_char = True
            continue
        if ch == "{":
            delta += 1
        elif ch == "}":
            delta -= 1

    return leading_closes, delta


def format_text(text: str, indent_width: int = 4) -> str:
    indent = 0
    out: list[str] = []

    for raw_line in text.splitlines(keepends=True):
        if raw_line.endswith("\r\n"):
            line = raw_line[:-2]
            newline = "\r\n"
        elif raw_line.endswith("\n") or raw_line.endswith("\r"):
            line = raw_line[:-1]
            newline = raw_line[-1]
        else:
            line = raw_line
            newline = ""

        content = line.lstrip(" \t")
        if content == "":
            out.append(newline)
            continue

        leading_closes, delta = brace_delta(line)
        line_indent = max(0, indent - leading_closes)
        out.append(" " * (line_indent * indent_width) + content + newline)
        indent = max(0, indent + delta)

    return "".join(out)


def check_file(path: Path, indent_width: int) -> bool:
    original = read_source(path)
    return original == format_text(original, indent_width)


def write_file(path: Path, indent_width: int) -> bool:
    original = read_source(path)
    formatted = format_text(original, indent_width)
    if original == formatted:
        return False
    write_source(path, formatted)
    return True


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Format Epic source indentation without changing other spacing."
    )
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument(
        "-w", "--write", action="store_true", help="rewrite files in place"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit with status 1 and print paths that need formatting",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=4,
        help="spaces per indentation level (default: 4)",
    )
    return parser.parse_args(argv)


def expand_paths(paths: list[Path]) -> list[Path]:
    expanded: list[Path] = []
    for path in paths:
        text = str(path)
        if any(ch in text for ch in "*?["):
            matches = sorted(glob.glob(text))
            if matches:
                expanded.extend(Path(match) for match in matches)
                continue
        expanded.append(path)
    return expanded


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.indent < 1:
        print("epicfmt.py: --indent must be positive", file=sys.stderr)
        return 2
    if args.write and args.check:
        print("epicfmt.py: --write and --check cannot be used together", file=sys.stderr)
        return 2

    files = expand_paths(args.files)

    if not files:
        if args.write or args.check:
            print("epicfmt.py: file arguments are required", file=sys.stderr)
            return 2
        sys.stdout.write(format_text(sys.stdin.read(), args.indent))
        return 0

    if args.check:
        dirty = [path for path in files if not check_file(path, args.indent)]
        for path in dirty:
            print(path)
        return 1 if dirty else 0

    if args.write:
        for path in files:
            write_file(path, args.indent)
        return 0

    for path in files:
        sys.stdout.write(format_text(read_source(path), args.indent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
