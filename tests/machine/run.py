#!/usr/bin/env python3
"""Machine encoder instruction, symbol, and relocation contracts."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from compiler_runner import compile_tool


def main():
    fixture = ROOT / "tests" / "machine" / "fixture.ep"
    sources = [ROOT / "src" / name for name in ("util.ep", "x64.ep", "machine.ep")]
    exe = compile_tool(fixture, [*sources, fixture], ROOT / "build" / "tests" / "machine.exe")
    result = subprocess.run([str(exe)], cwd=ROOT, capture_output=True)
    if result.returncode != 0:
        print((result.stdout + result.stderr).decode("utf-8", errors="replace")[-2000:])
        return 1

    failures = [
        ("fail_append_i32.ep", "i32 value out of range: 2147483648"),
        ("fail_patch_i32.ep", "i32 patch value out of range: -2147483649"),
    ]
    for name, expected in failures:
        source = ROOT / "tests" / "machine" / name
        failed_exe = compile_tool(
            source,
            [*sources, source],
            ROOT / "build" / "tests" / f"machine-{source.stem}.exe",
        )
        failed = subprocess.run([str(failed_exe)], cwd=ROOT, capture_output=True)
        output = (failed.stdout + failed.stderr).decode("utf-8", errors="replace")
        if failed.returncode == 0 or expected not in output:
            print(output[-2000:])
            return 1

    print("  PASS  machine encoding contracts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
