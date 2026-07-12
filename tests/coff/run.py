#!/usr/bin/env python3
"""AMD64 COFF header, section, symbol, and relocation contracts."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from compiler_runner import compile_tool


def main():
    fixture = ROOT / "tests" / "coff" / "fixture.ep"
    sources = [ROOT / "src" / name for name in ("util.ep", "x64.ep", "machine.ep", "coff.ep")]
    exe = compile_tool(fixture, [*sources, fixture], ROOT / "build" / "tests" / "coff.exe")
    result = subprocess.run([str(exe)], cwd=ROOT, capture_output=True)
    if result.returncode != 0:
        print((result.stdout + result.stderr).decode("utf-8", errors="replace")[-2000:])
        return 1
    print("  PASS  COFF format contracts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
