#!/usr/bin/env python3
"""Lexer golden and line-ending tests using the current Epic implementation."""

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from compiler_runner import compile_tool


FIXTURE = ROOT / "tests" / "lexer" / "pass" / "all.ep"
GOLDEN = ROOT / "tests" / "lexer" / "pass" / "token_list.txt"
LEXER_EXE = ROOT / "build" / "tests" / "lexer.exe"


def run_dump(path):
    result = subprocess.run([str(LEXER_EXE), str(path)], cwd=ROOT, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError((result.stdout + result.stderr).decode("utf-8", errors="replace")[-2000:])
    return result.stdout.decode("utf-8", errors="strict")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regen", action="store_true")
    args = parser.parse_args()
    compile_tool(ROOT / "src" / "lexer.ep", [ROOT / "src" / "util.ep", ROOT / "src" / "lexer.ep"], LEXER_EXE)
    actual = run_dump(FIXTURE)
    if args.regen:
        GOLDEN.write_text(actual, encoding="utf-8", newline="\n")
        print(f"regenerated {GOLDEN.relative_to(ROOT)}")
        return 0
    if actual != GOLDEN.read_text(encoding="utf-8"):
        print("  FAIL  lexer token golden mismatch")
        return 1
    print("  PASS  lexer token golden")

    build = ROOT / "build" / "tests"
    lf = build / "lexer_lf.ep"
    crlf = build / "lexer_crlf.ep"
    source = "fun main(): void {\n    println(\"ok\")\n}\n"
    lf.write_bytes(source.encode())
    crlf.write_bytes(source.replace("\n", "\r\n").encode())
    if run_dump(lf) != run_dump(crlf):
        print("  FAIL  lexer LF/CRLF equivalence")
        return 1
    print("  PASS  lexer LF/CRLF equivalence")
    for path in sorted((ROOT / "examples").glob("*.ep")):
        run_dump(path)
    print("  PASS  lexer examples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
