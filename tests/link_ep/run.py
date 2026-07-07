#!/usr/bin/env python3
"""Self-hosted PE linker byte oracle tests."""

from __future__ import annotations

import contextlib
import difflib
import io
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bootstrap"))

from epic import compile_files  # noqa: E402

EPICC = ROOT / "bootstrap" / "epic.py"
LINK_SRC = ROOT / "src" / "link.ep"
LINK_EXE = ROOT / "build" / "src" / "link.exe"
OUT_DIR = ROOT / "build" / "link_ep"
PY_OUT_DIR = OUT_DIR / "py"
EP_OUT_DIR = OUT_DIR / "ep"
EXAMPLES_DIR = ROOT / "examples"
AST_TO_MIR_PASS_DIR = ROOT / "tests" / "ast_to_mir" / "pass"
EXAMPLE_CASES = sorted(EXAMPLES_DIR.glob("*.ep"))
AST_TO_MIR_PASS_CASES = sorted(AST_TO_MIR_PASS_DIR.glob("*.ep"))
USER_CASES = EXAMPLE_CASES + AST_TO_MIR_PASS_CASES
EXPECTED_PASS = {path.relative_to(ROOT).as_posix() for path in USER_CASES}


def run(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")


def compile_linker() -> bool:
    result = run([sys.executable, str(EPICC), str(LINK_SRC), "--linker", "py"], timeout=60)
    if result.returncode != 0:
        print("  FAIL  compile src/link.ep")
        print((result.stdout + result.stderr)[-3000:])
        return False
    if not LINK_EXE.exists():
        print(f"  FAIL  missing linker exe: {LINK_EXE}")
        return False
    print("  PASS  compile src/link.ep")
    return True


def output_paths_for(source: Path, out_dir: Path) -> tuple[Path, Path, Path]:
    rel = source.relative_to(ROOT)
    stem = rel.with_suffix("")
    asm = out_dir / stem.with_suffix(".asm")
    obj = out_dir / stem.with_suffix(".obj")
    exe = out_dir / stem.with_suffix(".exe")
    return asm, obj, exe


def compile_reference(source: Path) -> tuple[Path, Path]:
    _, obj, exe = output_paths_for(source, PY_OUT_DIR)
    obj.parent.mkdir(parents=True, exist_ok=True)
    exe.parent.mkdir(parents=True, exist_ok=True)
    for path in (obj, exe):
        if path.exists():
            path.unlink()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        compile_files([str(source)], main_path=str(source), linker="py", out_dir=str(PY_OUT_DIR))
    if not obj.exists() or not exe.exists():
        raise RuntimeError(f"reference compile did not produce expected obj/exe for {source}")
    return obj, exe


def print_byte_diff(expected: bytes, actual: bytes) -> None:
    expected_lines = [str(b) for b in expected]
    actual_lines = [str(b) for b in actual]
    for i, line in enumerate(difflib.unified_diff(expected_lines, actual_lines, fromfile="expected", tofile="actual", lineterm="")):
        if i >= 120:
            print("  ... diff truncated ...")
            break
        print(line)


def run_one(source: Path) -> bool:
    rel = source.relative_to(ROOT).as_posix()
    obj, expected_exe = compile_reference(source)
    actual_exe = EP_OUT_DIR / source.relative_to(ROOT).with_suffix(".exe")
    actual_exe.parent.mkdir(parents=True, exist_ok=True)
    if actual_exe.exists():
        actual_exe.unlink()
    link_result = run([str(LINK_EXE), str(obj), "-o", str(actual_exe)], timeout=15)
    if link_result.returncode != 0:
        print(f"  FAIL  {rel}")
        print((link_result.stdout + link_result.stderr)[-2000:])
        return False
    if not actual_exe.exists():
        print(f"  FAIL  {rel} link.ep produced no exe")
        return False
    expected = expected_exe.read_bytes()
    actual = actual_exe.read_bytes()
    if expected != actual:
        print(f"  FAIL  {rel}")
        print_byte_diff(expected, actual)
        return False
    print(f"  PASS  {rel}")
    return True


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PY_OUT_DIR.mkdir(parents=True, exist_ok=True)
    EP_OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not compile_linker():
        sys.exit(1)
    failed = 0
    passed = 0
    for source in USER_CASES:
        rel = source.relative_to(ROOT).as_posix()
        should_pass = rel in EXPECTED_PASS
        try:
            ok = run_one(source)
        except Exception as exc:
            ok = False
            print(f"  FAIL  {rel}")
            print(f"        {exc}")
        if ok:
            passed += 1
        elif should_pass:
            failed += 1
    total = len(USER_CASES)
    print(f"\nlink_ep examples: {passed}/{total} expected-pass, {failed} failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
