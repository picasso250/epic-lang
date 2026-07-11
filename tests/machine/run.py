#!/usr/bin/env python3
"""Machine encoder fixture and deterministic program tests."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from compiler_runner import compile_tool


BUILD = ROOT / "build" / "tests" / "machine"
FIXTURE = ROOT / "tests" / "machine" / "fixture.ep"
DRIVER = ROOT / "tests" / "machine" / "driver.ep"


def main():
    fixture_exe = compile_tool(FIXTURE, [ROOT / "src" / name for name in ("util.ep", "x64.ep", "machine.ep")] + [FIXTURE], BUILD / "fixture.exe")
    result = subprocess.run([str(fixture_exe)], cwd=ROOT, capture_output=True)
    if result.returncode != 0 or not result.stdout.startswith(b"TEXT"):
        print("  FAIL  machine encoder fixture")
        return 1
    print("  PASS  machine encoder fixture")

    sources = [ROOT / "src" / name for name in ("util.ep", "lexer.ep", "parser.ep", "sema.ep", "mir.ep", "ast_to_mir.ep", "x64.ep", "mir_to_x64.ep", "machine.ep")]
    driver_exe = compile_tool(DRIVER, [*sources, DRIVER], BUILD / "driver.exe")
    for path in sorted((ROOT / "examples").glob("*.ep")):
        first = subprocess.run([str(driver_exe), str(path)], cwd=ROOT, capture_output=True)
        second = subprocess.run([str(driver_exe), str(path)], cwd=ROOT, capture_output=True)
        if first.returncode != 0 or first.stdout != second.stdout or not first.stdout:
            print(f"  FAIL  {path.relative_to(ROOT)}")
            return 1
        print(f"  PASS  {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
