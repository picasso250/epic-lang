#!/usr/bin/env python3
"""Targeted MIR-to-X64 lowering contract tests."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from compiler_runner import compile_tool


def main():
    fixture = ROOT / "tests" / "mir_to_x64" / "layout_fixture.ep"
    sources = [ROOT / "src" / name for name in ("util.ep", "mir.ep", "x64.ep", "mir_to_x64.ep")]
    tool = compile_tool(fixture, [*sources, fixture], ROOT / "build" / "tests" / "mir_to_x64_layout.exe")
    result = subprocess.run([str(tool)], cwd=ROOT, capture_output=True)
    if result.returncode != 0:
        print((result.stdout + result.stderr).decode("utf-8", errors="replace")[-2000:])
        return 1
    print("  PASS  dynamic struct GEP stride")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
