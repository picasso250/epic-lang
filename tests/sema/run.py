#!/usr/bin/env python3
"""
tests/sema/run.py — Semantic analysis MVP test runner.

Scans tests/sema/fail/*.ep for # COMPILE_FAIL: annotations and verifies
the Python reference compiler (bootstrap/epic.py) rejects them with the
expected error text.

tests/sema/pass/*.ep is reserved for future use.
"""

import os
import re
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))  # repo root (up from tests/sema/ -> tests/ -> repo)
EPICC = os.path.join(ROOT_DIR, "bootstrap", "epic.py")

FAIL_DIR = os.path.join(SCRIPT_DIR, "fail")
PASS_DIR = os.path.join(SCRIPT_DIR, "pass")


def run_fail_tests():
    if not os.path.isdir(FAIL_DIR):
        return 0, 0, 0

    passed = 0
    failed = 0
    skipped = 0

    for ep_name in sorted(os.listdir(FAIL_DIR)):
        if not ep_name.endswith(".ep"):
            continue

        ep_path = os.path.join(FAIL_DIR, ep_name)

        with open(ep_path, "r", encoding="utf-8") as f:
            source = f.read()

        # Parse # COMPILE_FAIL: annotation
        m = re.search(r'#\s*COMPILE_FAIL:\s*(.*)$', source, re.MULTILINE)
        if not m:
            print(f"  SKIP  {ep_name:30s}  no # COMPILE_FAIL annotation")
            skipped += 1
            continue

        expected_text = m.group(1).strip()

        result = subprocess.run(
            [sys.executable, EPICC, ep_path],
            capture_output=True,
            text=True,
            cwd=ROOT_DIR,
            timeout=30,
        )

        output = result.stdout + result.stderr
        if result.returncode == 0:
            print(f"  FAIL  {ep_name:30s}  compile succeeded, expected failure")
            failed += 1
            continue

        if expected_text and expected_text not in output:
            print(f"  FAIL  {ep_name:30s}  expected {expected_text!r} not in:\n{output[:500]}")
            failed += 1
            continue

        passed += 1
        print(f"  PASS  {ep_name:30s}")

    return passed, failed, skipped


def run_pass_tests():
    """Placeholder for future sema/pass/ tests."""
    return 0, 0, 0


def main():
    total_passed = 0
    total_failed = 0
    total_skipped = 0

    p, f, s = run_fail_tests()
    total_passed += p
    total_failed += f
    total_skipped += s

    p, f, s = run_pass_tests()
    total_passed += p
    total_failed += f
    total_skipped += s

    print(f"\nsema: {total_passed} passed, {total_failed} failed, {total_skipped} skipped")
    sys.exit(1 if total_failed > 0 else 0)


if __name__ == "__main__":
    main()
