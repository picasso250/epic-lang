#!/usr/bin/env python3
"""Build Epic v1 from sibling generation directories. No Git references."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from build import build_to


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Epic v1 from v0..v1")
    parser.add_argument('-o', '--output', type=Path,
                        help='Copy compiled executable to this path (relative to caller cwd)')
    args = parser.parse_args()
    result = build_to(1)
    if args.output:
        target = args.output.resolve()
        if target != result:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(result, target)
        print(f'Output: {target}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
