#!/usr/bin/env python3
"""Run version-specific regression tests from the monorepo root.

Each vN test suite invokes that generation's local build wrapper; no compiler
stage uses a Git branch or temporary Git worktree. Use --from-version 4 to
validate only the active v4 front line.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-version', type=int, choices=range(5), default=0)
    parser.add_argument('--to-version', type=int, choices=range(5), default=4)
    args = parser.parse_args()
    if args.from_version > args.to_version:
        parser.error('--from-version cannot exceed --to-version')
    failed = []
    for version in range(args.from_version, args.to_version + 1):
        folder = ROOT / f'v{version}'
        script = folder / ('runtests.py' if version == 0 else 'tests/run.py')
        cmd = [sys.executable, str(script)]
        if version == 0:
            cmd += ['--linker', 'py']
        print(f'\n=== EPIC v{version} TESTS ===', flush=True)
        result = subprocess.run(cmd, cwd=folder, check=False)
        if result.returncode:
            failed.append(version)
            print(f'v{version}: FAILED exit={result.returncode}', flush=True)
        else:
            print(f'v{version}: PASS', flush=True)
    if failed:
        print(f'FAILED GENERATIONS: {failed}', flush=True)
        return 1
    print(f'ALL {args.to_version - args.from_version + 1} GENERATIONS PASS', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
