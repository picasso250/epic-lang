#!/usr/bin/env python3
"""
tests/mir_codegen/run.py — compare EP MIR codegen against the Python MIR oracle.

First milestone compares user functions only. Python ast_to_mir injects runtime
helpers unconditionally; the EP self-hosted path does not implement helper
injection yet.
"""

import difflib
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))
EPICC = os.path.join(ROOT_DIR, "bootstrap", "epic.py")
BUILD_DIR = os.path.join(ROOT_DIR, "build", "mir-codegen-bootstrap")
MIR_EXE = os.path.join(BUILD_DIR, "src", "mir_codegen.exe")
CASES = [
    os.path.join(SCRIPT_DIR, "pass_m1_exit.ep"),
    os.path.join(SCRIPT_DIR, "pass_m2_return_i64.ep"),
    os.path.join(SCRIPT_DIR, "pass_m3_let_arith.ep"),
    os.path.join(SCRIPT_DIR, "pass_m4_if_else.ep"),
    os.path.join(SCRIPT_DIR, "pass_m5_call_params.ep"),
    os.path.join(SCRIPT_DIR, "pass_m6_assign_while.ep"),
    os.path.join(SCRIPT_DIR, "pass_m7_unary_bool_cmp.ep"),
    os.path.join(SCRIPT_DIR, "pass_m8_break_continue.ep"),
    os.path.join(SCRIPT_DIR, "pass_m9_bit_shift_cmp.ep"),
    os.path.join(SCRIPT_DIR, "pass_m10_struct.ep"),
    os.path.join(SCRIPT_DIR, "pass_m11_struct_param.ep"),
]
sys.path.insert(0, os.path.join(ROOT_DIR, "bootstrap"))
from lexer import lex
from parser import Parser
from sema import analyze_program
from mir_codegen import ast_to_mir


def run_checked(cmd, label):
    result = subprocess.run(
        cmd,
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed:\n" + result.stdout[-3000:] + result.stderr[-3000:])
    return result


def ensure_ep_mir_codegen():
    os.makedirs(BUILD_DIR, exist_ok=True)
    run_checked(
        [
            sys.executable,
            EPICC,
            "--main",
            os.path.join("src", "mir_codegen.ep"),
            os.path.join("src", "util.ep"),
            os.path.join("src", "lexer.ep"),
            os.path.join("src", "parser.ep"),
            os.path.join("src", "sema.ep"),
            os.path.join("src", "mir.ep"),
            os.path.join("src", "mir_codegen.ep"),
            "--out-dir",
            BUILD_DIR,
        ],
        "compile src/mir_codegen.ep",
    )
    if not os.path.isfile(MIR_EXE):
        raise RuntimeError(f"expected mir_codegen.exe at {MIR_EXE}")


def python_user_mir(path):
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    typed = analyze_program(Parser(lex(source)).parse_program())
    program = ast_to_mir(typed)
    return "\n\n".join(fn.text() for fn in program.functions[: len(typed.funcs)]) + "\n"


def ep_user_mir(path):
    result = run_checked([MIR_EXE, path], f"EP MIR codegen {os.path.relpath(path, ROOT_DIR)}")
    return result.stdout


def print_diff(expected, actual):
    for i, line in enumerate(difflib.unified_diff(
        expected.splitlines(),
        actual.splitlines(),
        fromfile="python-oracle",
        tofile="ep-mir-codegen",
        lineterm="",
    )):
        if i >= 120:
            print("  ... diff truncated ...")
            break
        print(line)


def main():
    ensure_ep_mir_codegen()
    failed = 0
    for path in CASES:
        rel = os.path.relpath(path, ROOT_DIR)
        try:
            expected = python_user_mir(path)
            actual = ep_user_mir(path)
        except Exception as exc:
            failed += 1
            print(f"  FAIL  {rel}")
            print(f"        {exc}")
            continue
        if actual == expected:
            print(f"  PASS  {rel}")
        else:
            failed += 1
            print(f"  FAIL  {rel}")
            print_diff(expected, actual)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())


