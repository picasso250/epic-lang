#!/usr/bin/env python3
"""Build src/link.ep and use the resulting Epic linker on selected examples."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EPICC = ROOT / "bootstrap" / "epic.py"
LINK_SRC = ROOT / "src" / "link.ep"
LINK_EXE = ROOT / "build" / "src" / "link.exe"
OUT_DIR = ROOT / "build" / "link_ep"

sys.path.insert(0, str(ROOT))
import test_examples_py  # noqa: E402

EXAMPLES = [
    "m1_exit.ep",
    "m2_expr.ep",
    "m10_str.ep",
    "m11_file.ep",
    "m15_system.ep",
    "m25_argv.ep",
    "m26_write_file.ep",
    "m30_str_cat.ep",
    "m32_bytes_extend.ep",
    "v1_byte_io_endian.ep",
    "v2_map_str_i64.ep",
    "v4_str_eq.ep",
    "v5_zero_copy_str_bytes.ep",
]


def run(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)


def compile_linker() -> bool:
    result = run([sys.executable, str(EPICC), str(LINK_SRC), "--linker", "py"])
    if result.returncode != 0:
        print("  FAIL  compile src/link.ep")
        print((result.stdout + result.stderr)[-2000:])
        return False
    if not LINK_EXE.exists():
        print(f"  FAIL  missing linker exe: {LINK_EXE}")
        return False
    print("  PASS  compile src/link.ep")
    return True


def expected_exe_obj(ep_path: Path) -> tuple[Path, Path]:
    rel = ep_path.relative_to(ROOT)
    stem = rel.with_suffix("")
    return ROOT / "build" / stem.with_suffix(".obj"), OUT_DIR / rel.with_suffix(".exe").name


def run_one(name: str) -> bool:
    ep_path = ROOT / "examples" / name
    source = ep_path.read_text(encoding="utf-8")
    exit_expected, stdout_expected, argv, clean_paths, compile_fail, compile_only = test_examples_py.parse_annotations(source)
    if compile_fail is not None or compile_only:
        print(f"  SKIP  {name:24s} unsupported annotation")
        return True

    ok, detail = test_examples_py.run_test(str(ep_path), linker="py")
    if not ok:
        print(f"  FAIL  {name:24s} python compile baseline failed: {detail}")
        return False

    obj_path, exe_path = expected_exe_obj(ep_path)
    if not obj_path.exists():
        print(f"  FAIL  {name:24s} missing obj: {obj_path}")
        return False
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if exe_path.exists():
        exe_path.unlink()

    link_result = run([str(LINK_EXE), str(obj_path), "-o", str(exe_path)], timeout=10)
    if link_result.returncode != 0:
        print(f"  FAIL  {name:24s} link.ep failed")
        print((link_result.stdout + link_result.stderr)[-1000:])
        return False
    if not exe_path.exists():
        print(f"  FAIL  {name:24s} link.ep produced no exe")
        return False

    try:
        test_examples_py.clean_test_paths(clean_paths)
        proc = subprocess.run([str(exe_path), *argv], cwd=ROOT, capture_output=True, timeout=test_examples_py.EXEC_TIMEOUT)
    finally:
        try:
            test_examples_py.clean_test_paths(clean_paths)
        except RuntimeError as exc:
            print(f"  FAIL  {name:24s} clean failed: {exc}")
            return False

    failures: list[str] = []
    if exit_expected is not None and proc.returncode != exit_expected:
        failures.append(f"EXIT expected {exit_expected}, got {proc.returncode}")
    if stdout_expected is not None:
        actual = (proc.stdout or b"").decode("ascii", errors="replace").strip()[: len(stdout_expected) + 100]
        if actual != stdout_expected.strip():
            failures.append(f"STDOUT expected {stdout_expected!r}, got {actual!r}")
    if failures:
        print(f"  FAIL  {name:24s} {'; '.join(failures)}")
        return False

    print(f"  PASS  {name:24s} OK")
    return True


def main() -> None:
    if not compile_linker():
        sys.exit(1)
    failed = 0
    for name in EXAMPLES:
        if not run_one(name):
            failed += 1
    if failed:
        print(f"\nlink_ep: {failed} failed")
        sys.exit(1)
    print(f"\nlink_ep: {len(EXAMPLES)} passed")


if __name__ == "__main__":
    main()
