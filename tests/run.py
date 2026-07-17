#!/usr/bin/env python3
"""Build the self-hosted compiler, then run every v1 test suite."""

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPILER = ROOT / "build" / "fixed-point" / "generation-1.exe"
SUITES = ("examples", "e2e")


def main() -> int:
    bootstrap = subprocess.run(
        [sys.executable, str(ROOT / "bootstrap_fixed_point.py")],
        cwd=ROOT,
    )
    if bootstrap.returncode != 0:
        return bootstrap.returncode

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
