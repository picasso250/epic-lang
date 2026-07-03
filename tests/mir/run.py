#!/usr/bin/env python3
"""
tests/mir/run.py — MVP MIR test runner.
"""

import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    test_file = os.path.join(SCRIPT_DIR, "test_mir.py")
    if not os.path.isfile(test_file):
        print("  SKIP  test_mir.py not found")
        return

    result = subprocess.run(
        [sys.executable, test_file],
        cwd=SCRIPT_DIR,
    )
    if result.returncode != 0:
        print(f"  FAIL  mir (exit {result.returncode})")
        sys.exit(result.returncode)

    print("  PASS  mir")
    sys.exit(0)


if __name__ == "__main__":
    main()
