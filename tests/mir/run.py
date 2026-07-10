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
            "src/mir_runtime.ep",
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
    run_result = subprocess.run([str(exe)], cwd=root)
    if run_result.returncode != 0:
        print(f"  FAIL  MIR struct type declaration run (exit {run_result.returncode})")
        sys.exit(run_result.returncode)

    print("  PASS  mir")
    sys.exit(0)


if __name__ == "__main__":
    main()
