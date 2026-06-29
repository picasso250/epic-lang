#!/usr/bin/env python3
"""Formatter for Epic source files."""

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


def split_structural_lines(line: str) -> list[str]:
    """Split after { and before } outside literals/comments."""
    out: list[str] = []
    start = 0
    i = 0
    n = len(line)
    did_split = False
    in_string = False
    in_char = False
    escaped = False

    while i < n:
        ch = line[i]
        if escaped:
            escaped = False
            i += 1
            continue
        if ch == "\\" and (in_string or in_char):
            escaped = True
            i += 1
            continue
        if in_string:
            if ch == '"':
                in_string = False
            i += 1
            continue
        if in_char:
            if ch == "'":
                in_char = False
            i += 1
            continue
        if ch == "#":
            break
        if ch == '"':
            in_string = True
            i += 1
            continue
        if ch == "'":
            in_char = True
            i += 1
            continue
        if ch == "{":
            segment = line[start : i + 1].strip()
            if segment:
                out.append(segment)
            start = i + 1
            did_split = True
        elif ch == "}":
            segment = line[start:i].strip()
            if segment:
                out.append(segment)
            start = i
            did_split = True
        i += 1

    if not did_split:
        return [line.lstrip(" \t")]

    segment = line[start:].strip()
    if segment:
        out.append(segment)
    return out


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

        structural_lines = split_structural_lines(line)
        inserted_newline = newline if newline else "\n"
        for index, structural_line in enumerate(structural_lines):
            line_newline = newline if index == len(structural_lines) - 1 else inserted_newline
            leading_closes, delta = brace_delta(structural_line)
            line_indent = max(0, indent - leading_closes)
            out.append(" " * (line_indent * indent_width) + structural_line + line_newline)
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
        description="Format Epic source indentation and brace line breaks."
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
