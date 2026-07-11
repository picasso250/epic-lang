#!/usr/bin/env python3
"""COFF writer deterministic output tests for the Epic implementation."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from compiler_runner import compile_tool


DRIVER = ROOT / "tests" / "coff" / "driver.ep"
EXE = ROOT / "build" / "tests" / "coff.exe"


def main():
    sources = [ROOT / "src" / name for name in ("util.ep", "lexer.ep", "parser.ep", "sema.ep", "mir.ep", "ast_to_mir.ep", "x64.ep", "mir_to_x64.ep", "machine.ep", "coff.ep")]
    compile_tool(DRIVER, [*sources, DRIVER], EXE)
    cases = sorted((ROOT / "examples").glob("*.ep")) + sorted((ROOT / "tests" / "ast_to_mir" / "pass").glob("*.ep"))
    for path in cases:
        first = subprocess.run([str(EXE), str(path)], cwd=ROOT, capture_output=True)
        second = subprocess.run([str(EXE), str(path)], cwd=ROOT, capture_output=True)
        if first.returncode != 0 or first.stdout != second.stdout or not first.stdout:
            print(f"  FAIL  {path.relative_to(ROOT)}")
            return 1
        print(f"  PASS  {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
