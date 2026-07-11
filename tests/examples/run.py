#!/usr/bin/env python3
"""Compile and run the public examples with the current Epic compiler."""

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
import ep_runner


EXAMPLES = ROOT / "examples"


def resolve_example(name):
    if name is None:
        return None
    path = Path(name)
    if not path.suffix:
        path = EXAMPLES / f"{name}.ep"
    elif not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if ROOT not in path.parents or path.suffix != ".ep" or not path.is_file():
        raise RuntimeError(f"invalid example: {name}")
    return path


def run_one(path):
    try:
        return ep_runner.run_epic_case(str(path), root_dir=str(ROOT))
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as exc:
        return False, f"exception: {exc}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("example", nargs="?", help="example name or .ep path")
    args = parser.parse_args()
    selected = resolve_example(args.example)
    cases = [selected] if selected else sorted(EXAMPLES.glob("*.ep"))
    failed = 0
    print(f"Running {len(cases)} examples (self-hosted)...\n")
    for path in cases:
        ok, detail = run_one(path)
        print(f"  {'PASS' if ok else 'FAIL':5}  {path.name:24}  {detail}")
        failed += not ok
    print(f"\n{len(cases) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
