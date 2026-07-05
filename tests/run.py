#!/usr/bin/env python3
"""
tests/run.py — MVP top-level test runner.

Iterates through each module subdirectory, calling its run.py.
Any subrunner returning non-zero causes immediate non-zero exit.
"""

import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Ordered by dependency / logical compilation pipeline.
MODULES = [
    "lexer",
    "parser",
    "sema",
    "mir",
    "mir_codegen",
    "mir_lower",
    "x64",
    "machine",
    "coff",
    "link_ep",
    "e2e",
]


def main():
    failed_modules = []

    for mod in MODULES:
        runner = os.path.join(SCRIPT_DIR, mod, "run.py")
        if not os.path.isfile(runner):
            print(f"  SKIP  {mod:15s}  no run.py yet")
            continue

        print(f"\n--- {mod} ---")
        result = subprocess.run(
            [sys.executable, runner],
            cwd=SCRIPT_DIR,
        )
        if result.returncode == 0:
            print(f"  PASS  {mod}")
        else:
            print(f"  FAIL  {mod}  (exit {result.returncode})")
            failed_modules.append(mod)

    if failed_modules:
        print(f"\nFailed modules: {', '.join(failed_modules)}")
        sys.exit(1)
    else:
        print(f"\nAll {len(MODULES)} modules PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
