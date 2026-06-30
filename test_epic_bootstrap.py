#!/usr/bin/env python3
"""
Compile epic.ep, then use the self-hosted driver to compile single-file and
multi-file targets.
"""

import os
import subprocess
import sys


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EPICC = os.path.join(SCRIPT_DIR, "bootstrap", "epic.py")
BOOT_DIR = os.path.join(SCRIPT_DIR, "build", "epic-bootstrap")
EPIC_EXE = os.path.join(BOOT_DIR, "src", "epic.exe")


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
            f"{label} failed:\n"
            + result.stdout[-2000:]
            + result.stderr[-2000:]
        )
    return result


def ensure_bootstrap_epic():
    os.makedirs(BOOT_DIR, exist_ok=True)
    run_checked(
        [
            sys.executable,
            EPICC,
            "--main",
            os.path.join("src", "epic.ep"),
            os.path.join("src", "epic.ep"),
            os.path.join("src", "codegen_support.ep"),
            os.path.join("src", "codegen.ep"),
            os.path.join("src", "parser.ep"),
            os.path.join("src", "lexer.ep"),
            "--out-dir",
            BOOT_DIR,
        ],
        "compile epic.ep",
    )


def check_single_file():
    run_checked([EPIC_EXE, "examples/m31_str_tools.ep"], "epic single-file compile")
    exe_path = os.path.join(SCRIPT_DIR, "build", "epic", "examples_m31_str_tools.ep.exe")
    result = run_checked([exe_path], "run single-file output")
    if result.stdout.strip() != "epic_lang":
        raise RuntimeError(f"single-file stdout expected 'epic_lang', got {result.stdout!r}")


def check_multi_file():
    run_checked([EPIC_EXE, os.path.join("src", "parser.ep"), os.path.join("src", "lexer.ep")], "epic multi-file compile")
    exe_path = os.path.join(SCRIPT_DIR, "build", "epic", "parser.ep.exe")
    result = run_checked([exe_path, "examples/m1_exit.ep"], "run multi-file output")
    if "FunDef main : void" not in result.stdout:
        raise RuntimeError("multi-file parser output did not contain expected AST text")


def main():
    ensure_bootstrap_epic()
    checks = [
        ("single-file", check_single_file),
        ("multi-file", check_multi_file),
    ]
    failed = 0
    print(f"Checking bootstrap epic driver for {len(checks)} cases...\n")
    for name, check in checks:
        try:
            check()
        except Exception as e:
            failed += 1
            print(f"  FAIL   {name}")
            print(f"         {e}")
        else:
            print(f"  PASS   {name}")
    print(f"\n{len(checks) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
