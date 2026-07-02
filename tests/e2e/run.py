#!/usr/bin/env python3
"""
tests/e2e/run.py — End-to-end MVP test runner.

Scans tests/e2e/pass/*.ep and tests/e2e/fail/*.ep, reusing the run_test
function from test_examples_py.py.

tests/e2e/pass/*.ep:
  Expected to compile successfully (and optionally run, checking # EXIT / # STDOUT).

tests/e2e/fail/*.ep:
  Two categories:
  1. # COMPILE_FAIL: expected text — compile must fail with matching text.
  2. # EXIT: non-zero / # STDOUT: ... — run-time failure scenarios.
"""

import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))  # repo root (up from tests/e2e/ -> tests/ -> repo)

# Import run_test from the legacy test_examples_py
sys.path.insert(0, ROOT_DIR)
import test_examples_py

PASS_DIR = os.path.join(SCRIPT_DIR, "pass")
FAIL_DIR = os.path.join(SCRIPT_DIR, "fail")


def run_cases(search_dir, label):
    if not os.path.isdir(search_dir):
        return 0, 0, 0

    passed = 0
    failed = 0
    skipped = 0

    for ep_name in sorted(os.listdir(search_dir)):
        if not ep_name.endswith(".ep"):
            continue

        ep_path = os.path.join(search_dir, ep_name)

        try:
            ok, detail = test_examples_py.run_test(ep_path, linker="py")
        except subprocess.TimeoutExpired:
            ok, detail = False, "TIMEOUT (compile >30s)"
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
    total_passed = 0
    total_failed = 0
    total_skipped = 0

    print("  e2e/pass:")
    p, f, s = run_cases(PASS_DIR, "pass")
    total_passed += p
    total_failed += f
    total_skipped += s

    print("  e2e/fail:")
    p, f, s = run_cases(FAIL_DIR, "fail")
    total_passed += p
    total_failed += f
    total_skipped += s

    print(f"\ne2e: {total_passed} passed, {total_failed} failed, {total_skipped} skipped")
    sys.exit(1 if total_failed > 0 else 0)


if __name__ == "__main__":
    main()
