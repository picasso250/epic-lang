#!/usr/bin/env python3
"""Parser pass/fail tests using the current Epic implementation."""

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from compiler_runner import compile_tool


PARSER_EXE = ROOT / "build" / "tests" / "parser.exe"


def run(path):
    return subprocess.run([str(PARSER_EXE), str(path)], cwd=ROOT, capture_output=True)


def expected_failure(path):
    match = re.search(r"#\s*COMPILE_FAIL:\s*(.*)$", path.read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1).strip() if match else None


def main():
    compile_tool(
        ROOT / "src" / "parser.ep",
        [ROOT / "src" / "util.ep", ROOT / "src" / "lexer.ep", ROOT / "src" / "parser.ep"],
        PARSER_EXE,
    )
    pass_cases = sorted((ROOT / "examples").glob("*.ep")) + sorted((ROOT / "tests" / "parser" / "pass").glob("*.ep"))
    pass_cases += [ROOT / "src" / "lexer.ep", ROOT / "src" / "parser.ep"]
    for path in pass_cases:
        result = run(path)
        if result.returncode != 0:
            print(f"  FAIL  {path.relative_to(ROOT)}")
            return 1
        print(f"  PASS  {path.relative_to(ROOT)}")

    for path in sorted((ROOT / "tests" / "parser" / "fail").glob("*.ep")):
        expected = expected_failure(path)
        result = run(path)
        output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        if expected is None or result.returncode == 0 or expected not in output:
            print(f"  FAIL  {path.relative_to(ROOT)} expected {expected!r}")
            return 1
        print(f"  PASS  {path.relative_to(ROOT)}")

    build = ROOT / "build" / "tests"
    lf = build / "parser_lf.ep"
    crlf = build / "parser_crlf.ep"
    source = "fun main(): void {\n    if true { exit(0) }\n}\n"
    lf.write_bytes(source.encode())
    crlf.write_bytes(source.replace("\n", "\r\n").encode())
    if run(lf).stdout != run(crlf).stdout:
        print("  FAIL  parser LF/CRLF equivalence")
        return 1
    print("  PASS  parser LF/CRLF equivalence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
