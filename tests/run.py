#!/usr/bin/env python3
"""
tests/run.py — MVP top-level test runner.

Iterates through each module subdirectory, calling its run.py.
Any subrunner returning non-zero causes immediate non-zero exit.
"""

import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = Path(SCRIPT_DIR).parent
TEST_COMPILER = ROOT_DIR / "build" / "test-compiler" / "epic.exe"

# Ordered by dependency / logical compilation pipeline.
MODULES = [
    "lexer",
    "parser",
    "sema",
    "mir",
    "ast_to_mir",
    "mir_to_x64",
    "x64",
    "machine",
    "coff",
    "link",
    "gc",
    "e2e",
]


def main():
    TEST_COMPILER.parent.mkdir(parents=True, exist_ok=True)
    bootstrap = subprocess.run(
        [sys.executable, str(ROOT_DIR / "test_bootstrap_fixed_point.py"), "-o", str(TEST_COMPILER)],
        cwd=ROOT_DIR,
    )
    if bootstrap.returncode != 0:
        print("  FAIL  build current self-hosted test compiler")
        sys.exit(bootstrap.returncode)

    env = os.environ.copy()
    env["EPIC_TEST_COMPILER"] = str(TEST_COMPILER)
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
            env=env,
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
