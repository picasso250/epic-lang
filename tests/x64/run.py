#!/usr/bin/env python3
"""X64 backend test runner."""

import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

TEST_FILES = [
    ("test_x64_layers.py", "x64 layers"),
    ("test_self_hosted.py", "x64 self-hosted"),
]


def main():
    for filename, label in TEST_FILES:
        test_file = os.path.join(SCRIPT_DIR, filename)
        if not os.path.isfile(test_file):
            print(f"  FAIL  {filename} not found")
            sys.exit(1)

        result = subprocess.run(
            [sys.executable, test_file],
            cwd=SCRIPT_DIR,
        )
        if result.returncode != 0:
            print(f"  FAIL  {label} (exit {result.returncode})")
            sys.exit(result.returncode)

    print("  PASS  x64")
    sys.exit(0)


if __name__ == "__main__":
    main()
