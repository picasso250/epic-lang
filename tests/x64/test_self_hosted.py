#!/usr/bin/env python3
"""Self-hosted X64IR pretty-print oracle tests."""

from __future__ import annotations

import difflib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EPICC = ROOT / "bootstrap" / "epic.py"
BUILD_DIR = ROOT / "build" / "x64"
FIXTURE = ROOT / "tests" / "x64" / "fixture.ep"
FIXTURE_EXE = BUILD_DIR / "tests" / "x64" / "fixture.exe"

EXPECTED = """global _start
extern ExitProcess
section .data
msg: db 65, 0
scratch: times 8 db 0
section .text
_start:
    mov rax, 1
    cmp rax, 1
    jz done
    mov rax, 2
done:
    lea rdx, qword [msg]
    mov rcx, rax
    call ExitProcess
    ret
"""


def run_checked(cmd: list[str], label: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed:\n" + (result.stdout + result.stderr)[-3000:])
    return result


def print_diff(expected: str, actual: str) -> None:
    for i, line in enumerate(difflib.unified_diff(
        expected.splitlines(), actual.splitlines(), fromfile="expected", tofile="actual", lineterm=""
    )):
        if i >= 120:
            print("  ... diff truncated ...")
            break
        print(line)


def main() -> int:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    run_checked(
        [
            sys.executable,
            str(EPICC),
            "--main",
            str(FIXTURE),
            str(ROOT / "src" / "util.ep"),
            str(ROOT / "src" / "x64.ep"),
            str(FIXTURE),
            "--out-dir",
            str(BUILD_DIR),
        ],
        "compile tests/x64/fixture.ep",
    )
    if not FIXTURE_EXE.exists():
        raise RuntimeError(f"expected fixture exe at {FIXTURE_EXE}")

    result = run_checked([str(FIXTURE_EXE)], "run tests/x64/fixture.exe")
    if result.stdout != EXPECTED:
        print("  FAIL  x64 self-hosted pretty print")
        print_diff(EXPECTED, result.stdout)
        return 1
    print("  PASS  x64 self-hosted pretty print")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
