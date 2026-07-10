#!/usr/bin/env python3
"""
tests/ast_to_mir/run.py — compare EP AST-to-MIR against the Python MIR oracle.

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
AST_TO_MIR_EXE = os.path.join(BUILD_DIR, "src", "ast_to_mir.exe")
EXAMPLES_DIR = os.path.join(ROOT_DIR, "examples")
PASS_DIR = os.path.join(SCRIPT_DIR, "pass")
CASES = [
    os.path.join(PASS_DIR, name)
    for name in sorted(os.listdir(PASS_DIR))
    if name.endswith(".ep")
]
EXAMPLE_CASES = [
    os.path.join(EXAMPLES_DIR, name)
    for name in sorted(os.listdir(EXAMPLES_DIR))
    if name.endswith(".ep")
]
sys.path.insert(0, os.path.join(ROOT_DIR, "bootstrap"))
from lexer import lex
from parser import Parser
from sema import analyze_program
from ast_to_mir import ast_to_mir
from mir import MirProgram
from mir_runtime_helpers import IMPLEMENTED_MIR_HELPERS


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


def ensure_ep_ast_to_mir():
    os.makedirs(BUILD_DIR, exist_ok=True)
    run_checked(
        [
            sys.executable,
            EPICC,
            "--main",
            os.path.join("src", "ast_to_mir.ep"),
            os.path.join("src", "util.ep"),
            os.path.join("src", "lexer.ep"),
            os.path.join("src", "parser.ep"),
            os.path.join("src", "sema.ep"),
            os.path.join("src", "mir.ep"),
            os.path.join("src", "ast_to_mir.ep"),
            "--out-dir",
            BUILD_DIR,
        ],
        "compile src/ast_to_mir.ep",
    )
    if not os.path.isfile(AST_TO_MIR_EXE):
        raise RuntimeError(f"expected ast_to_mir.exe at {AST_TO_MIR_EXE}")


def python_user_mir(path):
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    typed = analyze_program(Parser(lex(source)).parse_program())
    lowered = ast_to_mir(typed)
    helper_names = set(IMPLEMENTED_MIR_HELPERS)
    frontend = MirProgram(
        globals=[
            glob
            for glob in lowered.globals
            if glob.name != "argv" and not glob.name.startswith("str.runtime.")
        ],
        functions=[fn for fn in lowered.functions if fn.name not in helper_names],
        structs=lowered.structs,
    )
    return frontend.text() + "\n"


def ep_user_mir(path):
    result = run_checked([AST_TO_MIR_EXE, path], f"EP AST-to-MIR {os.path.relpath(path, ROOT_DIR)}")
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
    ensure_ep_ast_to_mir()
    failed = 0
    for path in CASES + EXAMPLE_CASES:
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


