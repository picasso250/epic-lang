#!/usr/bin/env python3
"""
tests/x64/run.py — MVP X64 backend test runner.

Currently wraps the legacy test_x64_layers.py from the repo root.
"""

import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))  # repo root


def main():
    legacy = os.path.join(ROOT_DIR, "test_x64_layers.py")
    if not os.path.isfile(legacy):
        print("  SKIP  legacy test_x64_layers.py not found")
        return

    result = subprocess.run(
        [sys.executable, legacy],
        cwd=ROOT_DIR,
    )
    if result.returncode != 0:
        print(f"  FAIL  test_x64_layers.py (exit {result.returncode})")
        sys.exit(result.returncode)

    print("  PASS  x64")
    sys.exit(0)


if __name__ == "__main__":
    main()
