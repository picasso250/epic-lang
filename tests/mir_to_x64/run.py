#!/usr/bin/env python3
"""MIR-to-X64 deterministic output tests for the Epic implementation."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from compiler_runner import compile_tool


DRIVER = ROOT / "tests" / "mir_to_x64" / "driver.ep"
TOOL = ROOT / "build" / "tests" / "mir_to_x64.exe"


def main():
    sources = [ROOT / "src" / name for name in ("util.ep", "lexer.ep", "parser.ep", "sema.ep", "mir.ep", "ast_to_mir.ep", "x64.ep", "mir_to_x64.ep")]
    compile_tool(DRIVER, [*sources, DRIVER], TOOL)
    fixture = ROOT / "tests" / "mir_to_x64" / "layout_fixture.ep"
    fixture_tool = ROOT / "build" / "tests" / "mir_to_x64_layout.exe"
    compile_tool(fixture, [ROOT / "src" / name for name in ("util.ep", "mir.ep", "x64.ep", "mir_to_x64.ep")] + [fixture], fixture_tool)
    fixture_result = subprocess.run([str(fixture_tool)], cwd=ROOT, capture_output=True, text=True, encoding="ascii")
    required = ("mov r11, rax", "mov rcx, 12", "imul rax, rcx", "add rax, r11")
    if fixture_result.returncode != 0 or any(text not in fixture_result.stdout for text in required):
        print("  FAIL  explicit struct stride lowering")
        print(fixture_result.stdout + fixture_result.stderr)
        return 1
    print("  PASS  explicit struct stride lowering")

    cases = sorted((ROOT / "examples").glob("*.ep")) + sorted((ROOT / "tests" / "ast_to_mir" / "pass").glob("*.ep"))
    for path in cases:
        first = subprocess.run([str(TOOL), str(path)], cwd=ROOT, capture_output=True)
        second = subprocess.run([str(TOOL), str(path)], cwd=ROOT, capture_output=True)
        if first.returncode != 0 or first.stdout != second.stdout or b"section .text" not in first.stdout:
            print(f"  FAIL  {path.relative_to(ROOT)}")
            print((first.stdout + first.stderr).decode("utf-8", errors="replace")[-1000:])
            return 1
        print(f"  PASS  {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
