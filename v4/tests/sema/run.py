#!/usr/bin/env python3
"""Verify semantic-analysis diagnostics."""

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CASES = Path(__file__).resolve().parent / "cases"
COMPILER = Path(os.environ.get("EPIC_TEST_COMPILER", ROOT / "build" / "fixed-point" / "generation-1.exe"))


def expected_error(path: Path) -> str:
    first = path.read_text(encoding="utf-8").splitlines()[0]
    prefix = "# ERROR: "
    if not first.startswith(prefix):
        raise ValueError(f"{path}: missing {prefix!r}")
    return first[len(prefix) :]


def main() -> int:
    failed = []
    for path in sorted(CASES.glob("*.ep")):
        result = subprocess.run(
            [str(COMPILER), str(path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        output = result.stdout + result.stderr
        expected = expected_error(path)
        if result.returncode == 0:
            failed.append(f"{path.name}: unexpectedly compiled")
        elif expected not in output:
            failed.append(f"{path.name}: expected {expected!r}, got {output!r}")
        else:
            print(f"PASS {path.name}")
    if failed:
        for message in failed:
            print(f"FAIL {message}")
        return 1
    print(f"{len(list(CASES.glob('*.ep')))} semantic diagnostics passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
