#!/usr/bin/env python3
"""
tests/mir/run.py — MVP MIR test runner.
"""

import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    test_file = os.path.join(SCRIPT_DIR, "test_mir.py")
    if not os.path.isfile(test_file):
        print("  FAIL  test_mir.py not found")
        sys.exit(1)

    result = subprocess.run(
        [sys.executable, test_file],
        cwd=SCRIPT_DIR,
    )
    if result.returncode != 0:
        print(f"  FAIL  mir (exit {result.returncode})")
        sys.exit(result.returncode)

    root = Path(SCRIPT_DIR).resolve().parents[1]
    build_dir = root / "build" / "mir-type-decl-bootstrap"
    compile_result = subprocess.run(
        [
            sys.executable,
            str(root / "bootstrap" / "epic.py"),
            "--main",
            "tests/mir/type_decl.ep",
            "src/util.ep",
            "src/mir.ep",
            "src/mir_text.ep",
            "src/backend_abi.ep",
            "tests/mir/type_decl.ep",
            "--out-dir",
            str(build_dir),
        ],
        cwd=root,
    )
    if compile_result.returncode != 0:
        print(f"  FAIL  MIR struct type declaration compile (exit {compile_result.returncode})")
        sys.exit(compile_result.returncode)

    exe = build_dir / "tests" / "mir" / "type_decl.exe"
    run_result = subprocess.run(
        [str(exe)],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="ascii",
        errors="strict",
    )
    if run_result.returncode != 0:
        print(f"  FAIL  MIR canonical text run (exit {run_result.returncode})")
        print(run_result.stdout)
        print(run_result.stderr)
        sys.exit(run_result.returncode)

    expected = """extern void @ExitProcess(i64)

type Data = struct { i8, i64 }

type Zed = struct { ptr }

global @argv: ptr

global @counter: i64 = 42

global @str.0: ptr = bytes "A\\n\\\"\\\\\\x00\\xFF//tail"

define i64 @main() {
entry:
  %1: ptr = gep struct Zed, ptr null, i64 1
  %2: ptr = gep struct Data, ptr null, i64 1
  call void ExitProcess(i64 0)
  ret i64 0
}
"""
    actual = run_result.stdout.replace("\r\n", "\n")
    if actual != expected:
        print("  FAIL  MIR canonical text output mismatch")
        print("--- expected ---")
        print(expected)
        print("--- actual ---")
        print(actual)
        sys.exit(1)

    print("  PASS  MIR canonical text round-trip")

    dump_mir = subprocess.run(
        [
            sys.executable,
            str(root / "bootstrap" / "epic.py"),
            "tests/e2e/pass/v1_bool_int_ops.ep",
            "--dump-mir",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if dump_mir.returncode != 0:
        print("  FAIL  epic.py --dump-mir")
        print(dump_mir.stdout)
        print(dump_mir.stderr)
        sys.exit(dump_mir.returncode)
    if " = sar " not in dump_mir.stdout or " = shr " not in dump_mir.stdout:
        print("  FAIL  epic.py --dump-mir omitted signed/unsigned right shifts")
        print(dump_mir.stdout)
        sys.exit(1)
    print("  PASS  epic.py --dump-mir")

    fail_compile = subprocess.run(
        [
            sys.executable,
            str(root / "bootstrap" / "epic.py"),
            "--main",
            "tests/mir/backend_abi_fail.ep",
            "src/util.ep",
            "src/mir.ep",
            "src/mir_text.ep",
            "src/backend_abi.ep",
            "tests/mir/backend_abi_fail.ep",
            "--out-dir",
            str(build_dir),
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if fail_compile.returncode != 0:
        print("  FAIL  backend ABI negative fixture compile")
        print(fail_compile.stdout)
        print(fail_compile.stderr)
        sys.exit(fail_compile.returncode)

    fail_exe = build_dir / "tests" / "mir" / "backend_abi_fail.exe"
    fail_run = subprocess.run(
        [str(fail_exe)],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="ascii",
        errors="replace",
    )
    fail_output = fail_run.stdout + fail_run.stderr
    if fail_run.returncode == 0 or "unsupported backend extern: ExitProces" not in fail_output:
        print("  FAIL  backend ABI accepted unknown Epic callee")
        print(fail_output)
        sys.exit(1)

    print("  PASS  backend ABI rejects unsupported Epic extern")
    print("  PASS  mir")
    sys.exit(0)


if __name__ == "__main__":
    main()
