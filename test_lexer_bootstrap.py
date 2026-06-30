#!/usr/bin/env python3
"""
Compare the self-hosted lexer against the Python lexer on lexer.ep and examples/*.ep.
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "bootstrap"))
from lexer import lex


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EPICC = os.path.join(SCRIPT_DIR, "bootstrap", "epic.py")
LEXER_EP = os.path.join(SCRIPT_DIR, "src", "lexer.ep")
LEXER_EXE = os.path.join(SCRIPT_DIR, "build", "src", "lexer.exe")
EXAMPLES_DIR = os.path.join(SCRIPT_DIR, "examples")


def python_lexer_dump(path):
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    lines = []
    for kind, value, line in lex(source):
        lines.append(f"{kind} {value} {line}")
    return "\n".join(lines) + ("\n" if lines else "")


def bootstrap_lexer_dump(path):
    result = subprocess.run(
        [LEXER_EXE, path],
        cwd=SCRIPT_DIR,
        capture_output=True,
    )
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"lexer.exe failed for {path}:\n{stdout}\n{stderr}")
    return stdout


def ensure_bootstrap_lexer():
    result = subprocess.run(
        [sys.executable, EPICC, LEXER_EP],
        cwd=SCRIPT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout + result.stderr)


def lexer_test_paths():
    paths = [LEXER_EP]
    for name in sorted(os.listdir(EXAMPLES_DIR)):
        if name.endswith(".ep"):
            paths.append(os.path.join(EXAMPLES_DIR, name))
    return paths


def main():
    ensure_bootstrap_lexer()
    paths = lexer_test_paths()
    passed = 0
    failed = 0

    print(f"Comparing lexer dumps for {len(paths)} files...\n")
    for path in paths:
        rel = os.path.relpath(path, SCRIPT_DIR)
        expected = python_lexer_dump(path)
        actual = bootstrap_lexer_dump(path)
        if actual == expected:
            print(f"  PASS   {rel}")
            passed += 1
            continue
        print(f"  FAIL   {rel}")
        failed += 1
        exp_lines = expected.splitlines()
        act_lines = actual.splitlines()
        limit = min(len(exp_lines), len(act_lines))
        for i in range(limit):
            if exp_lines[i] != act_lines[i]:
                print(f"  line {i + 1}")
                print(f"  expected: {exp_lines[i]!r}")
                print(f"  actual:   {act_lines[i]!r}")
                break
        else:
            print(f"  expected {len(exp_lines)} lines, got {len(act_lines)}")
    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
