#!/usr/bin/env python3
"""
tests/lexer/run.py — Formal lexer test runner.

Default mode: golden (frozen) check of Python lexer against token_list.txt,
then self-hosted comparison.

Self-hosted comparison builds src/lexer.ep, then compares its output with the
Python lexer oracle on src/lexer.ep, all.ep, and examples/*.ep.

Skip self-hosted comparison:
  python tests/lexer/run.py --no-self-hosted

Regenerate token_list.txt from Python lexer oracle:
  python tests/lexer/run.py --regen

Golden spec:
  tests/lexer/pass/all.ep     — comprehensive lexer fixture (all token kinds)
  tests/lexer/pass/token_list.txt — oracle dump from bootstrap/lexer.py
"""

import argparse
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))  # repo root

# Import Python lexer oracle
sys.path.insert(0, os.path.join(ROOT_DIR, "bootstrap"))
from lexer import dump_tokens, lex

ALL_EP = os.path.join(SCRIPT_DIR, "pass", "all.ep")
TOKEN_LIST = os.path.join(SCRIPT_DIR, "pass", "token_list.txt")


def python_lexer_dump(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    return dump_tokens(lex(source))


def read_golden() -> str:
    with open(TOKEN_LIST, "r", encoding="utf-8") as f:
        return f.read()


def check_golden() -> bool:
    """Check that Python lexer output matches token_list.txt."""
    if not os.path.isfile(ALL_EP):
        print(f"  FAIL  missing golden fixture: {ALL_EP}")
        return False
    if not os.path.isfile(TOKEN_LIST):
        print(f"  FAIL  missing golden: {TOKEN_LIST}")
        return False

    expected = read_golden()
    actual = python_lexer_dump(ALL_EP)

    if actual == expected:
        print(f"  PASS  tokens/all.ep matches token_list.txt")
        return True
    else:
        # Show diff
        exp_lines = expected.splitlines()
        act_lines = actual.splitlines()
        mismatch = False
        for i in range(min(len(exp_lines), len(act_lines))):
            if exp_lines[i] != act_lines[i]:
                print(f"  FAIL  line {i+1}")
                print(f"    expected: {exp_lines[i]!r}")
                print(f"    actual:   {act_lines[i]!r}")
                mismatch = True
                break
        if not mismatch:
            print(f"  FAIL  expected {len(exp_lines)} lines, got {len(act_lines)}")
        return False


def ensure_bootstrap_lexer() -> str:
    """Build src/lexer.ep -> build/src/lexer.exe via bootstrap/epic.py."""
    lexer_ep = os.path.join(ROOT_DIR, "src", "lexer.ep")
    epicc = os.path.join(ROOT_DIR, "bootstrap", "epic.py")
    result = subprocess.run(
        [sys.executable, epicc, lexer_ep],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout + result.stderr)

    lexer_exe = os.path.join(ROOT_DIR, "build", "src", "lexer.exe")
    if not os.path.isfile(lexer_exe):
        raise RuntimeError(f"expected lexer.exe at {lexer_exe}")
    return lexer_exe


def check_self_hosted_lexer(lexer_exe: str, path: str, label: str) -> bool:
    """Compare Python lexer dump vs self-hosted lexer.exe dump for one file."""
    expected = python_lexer_dump(path)

    result = subprocess.run(
        [lexer_exe, path],
        cwd=ROOT_DIR,
        capture_output=True,
    )
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")
    if result.returncode != 0:
        print(f"  FAIL  {label}  lexer.exe failed:\n{stdout}{stderr}")
        return False

    if stdout == expected:
        print(f"  PASS  {label}")
        return True
    else:
        exp_lines = expected.splitlines()
        act_lines = stdout.splitlines()
        mismatch = False
        for i in range(min(len(exp_lines), len(act_lines))):
            if exp_lines[i] != act_lines[i]:
                print(f"  FAIL  {label}  line {i+1}")
                print(f"    expected: {exp_lines[i]!r}")
                print(f"    actual:   {act_lines[i]!r}")
                mismatch = True
                break
        if not mismatch:
            print(f"  FAIL  {label}  expected {len(exp_lines)} lines, got {len(act_lines)}")
        return False


def regen_golden():
    """Regenerate token_list.txt from Python lexer oracle."""
    if not os.path.isfile(ALL_EP):
        print(f"FAIL: {ALL_EP} not found")
        sys.exit(1)

    output = python_lexer_dump(ALL_EP)
    with open(TOKEN_LIST, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"Regenerated {TOKEN_LIST} ({len(output.splitlines())} lines)")
    print("Please review with: git diff tests/lexer/pass/token_list.txt")
    print("Do not commit without review.")


def main():
    parser = argparse.ArgumentParser(description="Epic lexer test runner")
    parser.add_argument("--regen", action="store_true",
                        help="Regenerate golden token_list.txt from Python lexer")
    parser.add_argument("--no-self-hosted", action="store_true",
                        help="Skip self-hosted lexer.exe comparison")
    args = parser.parse_args()

    if args.regen:
        regen_golden()
        sys.exit(0)

    # --- Normal mode: frozen golden check ---
    print("--- golden check ---")
    golden_ok = check_golden()
    if not golden_ok:
        sys.exit(1)

    # --- Self-hosted lexer comparison ---
    if not args.no_self_hosted:
        print("--- self-hosted lexer comparison ---")
        try:
            lexer_exe = ensure_bootstrap_lexer()
        except (RuntimeError, subprocess.TimeoutExpired) as e:
            print(f"  FAIL  self-hosted lexer build: {e}")
            sys.exit(1)

        lexer_ep = os.path.join(ROOT_DIR, "src", "lexer.ep")
        all_ok = check_self_hosted_lexer(
            lexer_exe, lexer_ep, "src/lexer.ep"
        )

        all_ok = check_self_hosted_lexer(
            lexer_exe, ALL_EP, "all.ep"
        ) and all_ok

        # Compare on all examples/*.ep
        examples_dir = os.path.join(ROOT_DIR, "examples")
        if os.path.isdir(examples_dir):
            for name in sorted(os.listdir(examples_dir)):
                if not name.endswith(".ep"):
                    continue
                ep_path = os.path.join(examples_dir, name)
                ok = check_self_hosted_lexer(lexer_exe, ep_path, name)
                if not ok:
                    all_ok = False

        if not all_ok:
            sys.exit(1)

    print("\n  PASS  lexer")
    sys.exit(0)


if __name__ == "__main__":
    main()
