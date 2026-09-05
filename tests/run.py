#!/usr/bin/env python3
"""Build the v2 compiler with v1, then run every v2 test suite."""

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPILER = ROOT / "build" / "epic-v2.exe"
SUITES = ("self_contained", "examples", "e2e", "sema", "gc")


def main() -> int:
    build = subprocess.run(
        [sys.executable, str(ROOT / "build_epic.py")],
        cwd=ROOT,
    )
    if build.returncode != 0:
        return build.returncode

    env = os.environ.copy()
    env["EPIC_TEST_COMPILER"] = str(COMPILER)
    failed = []
    for suite in SUITES:
        print(f"\n--- {suite} ---", flush=True)
        result = subprocess.run(
            [sys.executable, str(ROOT / "tests" / suite / "run.py")],
            cwd=ROOT,
            env=env,
        )
        if result.returncode != 0:
            failed.append(suite)

    if failed:
        print(f"\nFailed suites: {', '.join(failed)}")
        return 1
    print(f"\nAll {len(SUITES)} suites passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
