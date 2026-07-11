#!/usr/bin/env python3
"""
tests/sema/run.py — Semantic analysis tests.

Checks Python and self-hosted semantic behavior against the current language.
"""

import difflib
import os
import re
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))
EPICC = os.path.join(ROOT_DIR, "bootstrap", "epic.py")
UTIL_EP = os.path.join(ROOT_DIR, "src", "util.ep")
LEXER_EP = os.path.join(ROOT_DIR, "src", "lexer.ep")
PARSER_EP = os.path.join(ROOT_DIR, "src", "parser.ep")
SEMA_EP = os.path.join(ROOT_DIR, "src", "sema.ep")
SEMA_BUILD_DIR = os.path.join(ROOT_DIR, "build", "sema-bootstrap")
SEMA_EXE = os.path.join(SEMA_BUILD_DIR, "src", "sema.exe")

FAIL_DIR = os.path.join(SCRIPT_DIR, "fail")
PASS_DIR = os.path.join(SCRIPT_DIR, "pass")
ALL_EP = os.path.join(PASS_DIR, "all.ep")

sys.path.insert(0, os.path.join(ROOT_DIR, "bootstrap"))
from lexer import lex
from parser import Parser
from sema import analyze_program, dump_typed_ast_text


def python_sema_dump_source(source):
    ast = Parser(lex(source)).parse_program()
    typed = analyze_program(ast)
    return dump_typed_ast_text(typed)


def python_sema_dump(path):
    with open(path, "r", encoding="utf-8") as f:
        return python_sema_dump_source(f.read())


def print_diff(expected, actual, expected_label, actual_label):
    diff = difflib.unified_diff(
        expected.splitlines(),
        actual.splitlines(),
        fromfile=expected_label,
        tofile=actual_label,
        lineterm="",
    )
    for i, diff_line in enumerate(diff):
        if i >= 120:
            print("  ... diff truncated ...")
            break
        print(diff_line)


def run_cli_dump_typed_ast_test():
    if not os.path.isfile(ALL_EP):
        print(f"  FAIL  missing sema fixture: {ALL_EP}")
        return 0, 1, 0

    expected = python_sema_dump(ALL_EP)
    result = subprocess.run(
        [sys.executable, EPICC, ALL_EP, "--dump-typed-ast"],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    actual = result.stdout
    if result.returncode != 0:
        print("  FAIL  epic.py --dump-typed-ast failed")
        print((result.stdout + result.stderr)[-2000:])
        return 0, 1, 0
    if actual == expected:
        print("  PASS  epic.py --dump-typed-ast matches Python sema")
        return 1, 0, 0

    print("  FAIL  epic.py --dump-typed-ast matches Python sema")
    print_diff(expected, actual, "python/sema/pass/all.ep", "epic.py --dump-typed-ast")
    return 0, 1, 0


def ensure_self_hosted_sema():
    os.makedirs(SEMA_BUILD_DIR, exist_ok=True)
    result = subprocess.run(
        [
            sys.executable,
            EPICC,
            "--main",
            SEMA_EP,
            UTIL_EP,
            LEXER_EP,
            PARSER_EP,
            SEMA_EP,
            "--out-dir",
            SEMA_BUILD_DIR,
        ],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError("failed to compile src/sema.ep:\n" + result.stdout[-2000:] + result.stderr[-2000:])
    if not os.path.isfile(SEMA_EXE):
        raise RuntimeError(f"expected sema.exe at {SEMA_EXE}")


def run_self_hosted_pass_tests():
    ensure_self_hosted_sema()
    expected = python_sema_dump(ALL_EP)
    result = subprocess.run(
        [SEMA_EXE, ALL_EP],
        cwd=ROOT_DIR,
        capture_output=True,
    )
    actual = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")
    if result.returncode != 0:
        print("  FAIL  self-hosted sema pass/all.ep failed")
        print((actual + stderr)[-2000:])
        return 0, 1, 0
    if actual == expected:
        print("  PASS  self-hosted sema pass/all.ep")
        return 1, 0, 0
    print("  FAIL  self-hosted sema pass/all.ep")
    print_diff(expected, actual, "python/sema/pass/all.ep", "self-hosted/sema/pass/all.ep")
    return 0, 1, 0


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


def run_self_hosted_fail_tests():
    if not os.path.isdir(FAIL_DIR):
        return 0, 0, 0

    ensure_self_hosted_sema()

    passed = 0
    failed = 0
    skipped = 0

    for ep_name in sorted(os.listdir(FAIL_DIR)):
        if not ep_name.endswith(".ep"):
            continue

        ep_path = os.path.join(FAIL_DIR, ep_name)

        with open(ep_path, "r", encoding="utf-8") as f:
            source = f.read()

        m = re.search(r'#\s*COMPILE_FAIL:\s*(.*)$', source, re.MULTILINE)
        if not m:
            print(f"  SKIP  self-hosted {ep_name:18s}  no # COMPILE_FAIL annotation")
            skipped += 1
            continue

        expected_text = m.group(1).strip()

        result = subprocess.run(
            [SEMA_EXE, ep_path],
            capture_output=True,
            cwd=ROOT_DIR,
            timeout=30,
        )

        output = (
            result.stdout.decode("utf-8", errors="replace")
            + result.stderr.decode("utf-8", errors="replace")
        )
        if result.returncode == 0:
            print(f"  FAIL  self-hosted {ep_name:18s}  sema succeeded, expected failure")
            failed += 1
            continue

        if expected_text and expected_text not in output:
            print(f"  FAIL  self-hosted {ep_name:18s}  expected {expected_text!r} not in:\n{output[:500]}")
            failed += 1
            continue

        passed += 1
        print(f"  PASS  self-hosted {ep_name:18s}")

    return passed, failed, skipped


def main():
    total_passed = 0
    total_failed = 0
    total_skipped = 0

    p, f, s = run_cli_dump_typed_ast_test()
    total_passed += p
    total_failed += f
    total_skipped += s

    p, f, s = run_self_hosted_pass_tests()
    total_passed += p
    total_failed += f
    total_skipped += s

    p, f, s = run_fail_tests()
    total_passed += p
    total_failed += f
    total_skipped += s

    p, f, s = run_self_hosted_fail_tests()
    total_passed += p
    total_failed += f
    total_skipped += s

    print(f"\nsema: {total_passed} passed, {total_failed} failed, {total_skipped} skipped")
    return 1 if total_failed > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
