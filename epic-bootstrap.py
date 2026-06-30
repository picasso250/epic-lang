#!/usr/bin/env python3
"""Run the current Epic fixed-point bootstrap check."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def main() -> int:
    return subprocess.run(
        [sys.executable, "test_bootstrap_fixed_point.py"],
        cwd=ROOT,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
