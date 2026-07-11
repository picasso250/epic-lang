#!/usr/bin/env python3
"""Semantic pass/fail tests using the current Epic implementation."""

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from compiler_runner import compile_tool


SEMA_EXE = ROOT / "build" / "tests" / "sema.exe"


def run(path):
    return subprocess.run([str(SEMA_EXE), str(path)], cwd=ROOT, capture_output=True)


def main():
    compile_tool(
        ROOT / "src" / "sema.ep",
        [ROOT / "src" / name for name in ("util.ep", "lexer.ep", "parser.ep", "sema.ep")],
        SEMA_EXE,
    )
    for path in sorted((ROOT / "tests" / "sema" / "pass").glob("*.ep")):
        result = run(path)
        if result.returncode != 0:
            print(f"  FAIL  {path.relative_to(ROOT)}")
            print((result.stdout + result.stderr).decode("utf-8", errors="replace")[-1000:])
            return 1
        print(f"  PASS  {path.relative_to(ROOT)}")
    for path in sorted((ROOT / "tests" / "sema" / "fail").glob("*.ep")):
        match = re.search(r"#\s*COMPILE_FAIL:\s*(.*)$", path.read_text(encoding="utf-8"), re.MULTILINE)
        expected = match.group(1).strip() if match else None
        result = run(path)
        output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        if expected is None or result.returncode == 0 or expected not in output:
            print(f"  FAIL  {path.relative_to(ROOT)} expected {expected!r}")
            print(output[-1000:])
            return 1
        print(f"  PASS  {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
