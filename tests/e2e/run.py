#!/usr/bin/env python3
"""
tests/e2e/run.py — End-to-end test runner.

Scans tests/e2e/pass/*.ep and tests/e2e/fail/*.ep, using the shared Epic case
runner from tests/ep_runner.py.
"""

import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(SCRIPT_DIR)
ROOT_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, TESTS_DIR)

import ep_runner

PASS_DIR = os.path.join(SCRIPT_DIR, "pass")
FAIL_DIR = os.path.join(SCRIPT_DIR, "fail")


def run_cases(search_dir):
    if not os.path.isdir(search_dir):
        return 0, 0, 0

    passed = failed = skipped = 0
    for ep_name in sorted(os.listdir(search_dir)):
        if not ep_name.endswith(".ep"):
            continue

        ep_path = os.path.join(search_dir, ep_name)
        try:
            ok, detail = ep_runner.run_python_case(ep_path, linker="py", root_dir=ROOT_DIR)
        except subprocess.TimeoutExpired:
            ok, detail = False, "TIMEOUT"
        except Exception as e:
            ok, detail = False, f"exception: {e}"

        status = "PASS" if ok else "FAIL"
        if "skipped" in detail:
            status = "SKIP"
            skipped += 1
        elif ok:
            passed += 1
        else:
            failed += 1

        print(f"  {status:5}  {ep_name:30s}  {detail}")

    return passed, failed, skipped


def main():
    total_passed = total_failed = total_skipped = 0

    print("  e2e/pass:")
    p, f, s = run_cases(PASS_DIR)
    total_passed += p
    total_failed += f
    total_skipped += s

    print("  e2e/fail:")
    p, f, s = run_cases(FAIL_DIR)
    total_passed += p
    total_failed += f
    total_skipped += s

    print(f"\ne2e: {total_passed} passed, {total_failed} failed, {total_skipped} skipped")
    sys.exit(1 if total_failed > 0 else 0)


if __name__ == "__main__":
    main()
