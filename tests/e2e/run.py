#!/usr/bin/env python3
"""Compile and run the Epic end-to-end tests."""

import subprocess
import sys
from pathlib import Path


TESTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TESTS))
import ep_runner


def main() -> int:
    cases = sorted((Path(__file__).parent / "pass").glob("*.ep"))
    failed = 0
    print(f"Running {len(cases)} end-to-end tests...\n")
    for source in cases:
        try:
            ok, detail = ep_runner.run_case(source)
        except subprocess.TimeoutExpired:
            ok, detail = False, "TIMEOUT"
        except Exception as error:
            ok, detail = False, f"exception: {error}"
        print(f"  {'PASS' if ok else 'FAIL':5}  {source.name:32}  {detail}")
        failed += not ok
    print(f"\n{len(cases) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
