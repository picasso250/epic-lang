#!/usr/bin/env python3
"""
Build the v1 Epic compiler with a v0 bootstrap compiler, then verify v1-only
builtins against dedicated v1 examples.
"""

import os
import subprocess
import sys

from runtests import parse_annotations


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
V1_BUILD_DIR = os.path.join(SCRIPT_DIR, "build", "v1")
SOURCES = ["epic.ep", "codegen.ep", "parser.ep", "lexer.ep"]
DEFAULT_V0 = os.path.join(SCRIPT_DIR, "build", "fixed-point", "epic-epic.exe")
V0_EPIC = os.environ.get("V0_EPIC", DEFAULT_V0)
V1_EPIC = os.path.join(SCRIPT_DIR, "build", "epic", "epic.ep.exe")


def run_checked(cmd, label):
    result = subprocess.run(
        cmd,
        cwd=SCRIPT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"{label} failed with exit {result.returncode}\n"
            + result.stdout[-2000:]
            + result.stderr[-2000:]
        )
    return result


def ensure_v0_anchor():
    if not os.path.exists(V0_EPIC):
        raise RuntimeError(
            "v0 bootstrap compiler not found. Set V0_EPIC or build "
            + os.path.relpath(DEFAULT_V0, SCRIPT_DIR)
        )


def build_v1_compiler():
    os.makedirs(V1_BUILD_DIR, exist_ok=True)
    run_checked([V0_EPIC, *SOURCES], "v0 -> v1 compiler")
    if not os.path.exists(V1_EPIC):
        raise RuntimeError(f"expected v1 compiler output missing: {V1_EPIC}")


def check_example(rel_path):
    path = os.path.join(SCRIPT_DIR, rel_path)
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    exit_expected, stdout_expected, _, _ = parse_annotations(source)

    run_checked([V1_EPIC, rel_path], f"compile {rel_path}")
    exe_path = os.path.join(SCRIPT_DIR, "build", "epic", rel_path.replace("/", "_") + ".exe")
    result = subprocess.run(
        [exe_path],
        cwd=SCRIPT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if exit_expected is not None and result.returncode != exit_expected:
        raise RuntimeError(
            f"{rel_path} EXIT expected {exit_expected}, got {result.returncode}"
        )
    if stdout_expected is not None and result.stdout.strip() != stdout_expected.strip():
        raise RuntimeError(
            f"{rel_path} STDOUT expected {stdout_expected!r}, got {result.stdout!r}"
        )


def main():
    ensure_v0_anchor()
    build_v1_compiler()
    checks = ["v1_examples/m1_len_cap.ep"]
    failed = 0
    print(f"Checking v1 builtins for {len(checks)} cases...\n")
    for rel_path in checks:
        try:
            check_example(rel_path)
        except Exception as e:
            failed += 1
            print(f"  FAIL   {rel_path}")
            print(f"         {e}")
        else:
            print(f"  PASS   {rel_path}")
    print(f"\n{len(checks) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
