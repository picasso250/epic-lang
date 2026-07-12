#!/usr/bin/env python3
"""PE linker executable behavior test."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from compiler_runner import compile_program, compile_tool


def main():
    link = compile_tool(ROOT / "src" / "link.ep", [ROOT / "src" / "util.ep", ROOT / "src" / "link.ep"], ROOT / "build" / "tests" / "link.exe")
    source = ROOT / "examples" / "00_hello_world.ep"
    seed = compile_program(source, ROOT / "build" / "tests" / "link-seed.exe")
    actual = ROOT / "build" / "tests" / "link-actual.exe"
    linked = subprocess.run([str(link), str(seed) + ".obj", "-o", str(actual)], cwd=ROOT, capture_output=True)
    result = subprocess.run([str(actual)], cwd=ROOT, capture_output=True) if linked.returncode == 0 and actual.is_file() else linked
    if result.returncode != 0 or result.stdout.strip() != b"Hello, Epic!":
        print((linked.stdout + linked.stderr + result.stdout + result.stderr).decode("utf-8", errors="replace")[-2000:])
        return 1
    print("  PASS  linked executable behavior")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
