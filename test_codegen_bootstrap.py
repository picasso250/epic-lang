#!/usr/bin/env python3
"""
Compile codegen.ep, then use the self-hosted codegen to compile the first
single-file examples slice.
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "bootstrap"))
from runtests import parse_annotations, clean_test_paths


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EPICC = os.path.join(SCRIPT_DIR, "bootstrap", "epic.py")
NASM = os.path.join(SCRIPT_DIR, "tools", "nasm.exe")
LLD_LINK = os.path.join(SCRIPT_DIR, "tools", "lld-link.exe")
SDK_LIB = r"C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\um\x64"
BOOT_DIR = os.path.join(SCRIPT_DIR, "build", "bootstrap-codegen")
CODEGEN_EXE = os.path.join(BOOT_DIR, "src", "codegen.exe")

EXAMPLE_SLICE = [
    name for name in sorted(os.listdir(os.path.join(SCRIPT_DIR, "examples")))
    if name.endswith(".ep")
]


def run_checked(cmd, label):
    result = subprocess.run(
        cmd,
        cwd=SCRIPT_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"{label} failed:\n"
            + result.stdout[-2000:]
            + result.stderr[-2000:]
        )
    return result


def ensure_bootstrap_codegen():
    os.makedirs(BOOT_DIR, exist_ok=True)
    run_checked(
        [
            sys.executable,
            EPICC,
            "--main",
            os.path.join("src", "codegen.ep"),
            os.path.join("src", "lexer.ep"),
            os.path.join("src", "parser.ep"),
            os.path.join("src", "codegen_support.ep"),
            os.path.join("src", "codegen.ep"),
            "--out-dir",
            BOOT_DIR,
        ],
        "compile codegen.ep",
    )


def compile_with_bootstrap_codegen(example_name):
    ep_path = os.path.join("examples", example_name)
    base = os.path.join(BOOT_DIR, os.path.splitext(example_name)[0] + ".epic")
    asm_path = base + ".asm"
    obj_path = base + ".obj"
    exe_path = base + ".exe"

    run_checked([CODEGEN_EXE, ep_path, asm_path], f"bootstrap codegen {example_name}")
    run_checked([NASM, "-f", "win64", asm_path, "-o", obj_path], f"nasm {example_name}")
    run_checked(
        [
            LLD_LINK,
            "/entry:_start",
            "/subsystem:console",
            "/nodefaultlib",
            "/out:" + exe_path,
            obj_path,
            "kernel32.lib",
            "user32.lib",
            "/libpath:" + SDK_LIB,
        ],
        f"link {example_name}",
    )
    return exe_path


def check_example(example_name):
    ep_path = os.path.join(SCRIPT_DIR, "examples", example_name)
    with open(ep_path, "r", encoding="utf-8") as f:
        source = f.read()
    exit_expected, stdout_expected, argv, clean_paths = parse_annotations(source)
    clean_test_paths(clean_paths)
    exe_path = compile_with_bootstrap_codegen(example_name)
    proc = subprocess.run([exe_path, *argv], cwd=SCRIPT_DIR, capture_output=True)
    failures = []
    if exit_expected is not None and proc.returncode != exit_expected:
        failures.append(f"EXIT expected {exit_expected}, got {proc.returncode}")
    if stdout_expected is not None:
        actual = (proc.stdout or b"").decode("ascii", errors="replace").strip()
        if actual != stdout_expected.strip():
            failures.append(f"STDOUT expected {stdout_expected!r}, got {actual!r}")
    clean_test_paths(clean_paths)
    return failures


def main():
    ensure_bootstrap_codegen()
    failed = 0
    print(f"Checking bootstrap codegen for {len(EXAMPLE_SLICE)} examples...\n")
    for name in EXAMPLE_SLICE:
        try:
            failures = check_example(name)
        except Exception as e:
            failures = [str(e)]
        if failures:
            failed += 1
            print(f"  FAIL   {name}")
            for failure in failures:
                print(f"         {failure}")
        else:
            print(f"  PASS   {name}")
    print(f"\n{len(EXAMPLE_SLICE) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
