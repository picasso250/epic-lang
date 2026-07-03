#!/usr/bin/env python3
"""
tests/x64/run.py — MVP X64 backend test runner.
"""

import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    test_file = os.path.join(SCRIPT_DIR, "test_x64_layers.py")
    if not os.path.isfile(test_file):
        print("  FAIL  test_x64_layers.py not found")
        sys.exit(1)

    result = subprocess.run(
        [sys.executable, test_file],
        cwd=SCRIPT_DIR,
    )
    if result.returncode != 0:
        print(f"  FAIL  x64 (exit {result.returncode})")
        sys.exit(result.returncode)

    print("  PASS  x64")
    sys.exit(0)


if __name__ == "__main__":
    main()
