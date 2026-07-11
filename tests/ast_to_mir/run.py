#!/usr/bin/env python3
"""AST-to-MIR deterministic output tests for the Epic implementation."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from compiler_runner import compile_tool


TOOL = ROOT / "build" / "tests" / "ast_to_mir.exe"


def main():
    sources = [ROOT / "src" / name for name in ("util.ep", "lexer.ep", "parser.ep", "sema.ep", "mir.ep", "ast_to_mir.ep")]
    compile_tool(ROOT / "src" / "ast_to_mir.ep", sources, TOOL)
    cases = sorted((ROOT / "tests" / "ast_to_mir" / "pass").glob("*.ep")) + sorted((ROOT / "examples").glob("*.ep"))
    for path in cases:
        first = subprocess.run([str(TOOL), str(path)], cwd=ROOT, capture_output=True)
        second = subprocess.run([str(TOOL), str(path)], cwd=ROOT, capture_output=True)
        if first.returncode != 0 or first.stdout != second.stdout or b"define " not in first.stdout:
            print(f"  FAIL  {path.relative_to(ROOT)}")
            print((first.stdout + first.stderr).decode("utf-8", errors="replace")[-1000:])
            return 1
        print(f"  PASS  {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
