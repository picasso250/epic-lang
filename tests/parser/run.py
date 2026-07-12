#!/usr/bin/env python3
"""Parser pass/fail tests using the current Epic implementation."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from compiler_runner import compile_fail_contains, compile_tool


PARSER_EXE = ROOT / "build" / "tests" / "parser.exe"


def run(path):
    return subprocess.run([str(PARSER_EXE), str(path)], cwd=ROOT, capture_output=True)



def main():
    compile_tool(
        ROOT / "src" / "parser.ep",
        [ROOT / "src" / "util.ep", ROOT / "src" / "lexer.ep", ROOT / "src" / "parser.ep"],
        PARSER_EXE,
    )
    pass_cases = sorted((ROOT / "tests" / "parser" / "pass").glob("*.ep"))
    for path in pass_cases:
        result = run(path)
        if result.returncode != 0:
            print(f"  FAIL  {path.relative_to(ROOT)}")
            return 1
        print(f"  PASS  {path.relative_to(ROOT)}")

    for path in sorted((ROOT / "tests" / "parser" / "fail").glob("*.ep")):
        expected = compile_fail_contains(path)
        result = run(path)
        output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        if expected is None or result.returncode == 0 or expected not in output:
            print(f"  FAIL  {path.relative_to(ROOT)} expected {expected!r}")
            return 1
        print(f"  PASS  {path.relative_to(ROOT)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
