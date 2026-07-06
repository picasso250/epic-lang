#!/usr/bin/env python3
"""Self-hosted MIR-to-X64 lowering oracle tests."""

from __future__ import annotations

import difflib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EPICC = ROOT / "bootstrap" / "epic.py"
BUILD_DIR = ROOT / "build" / "mir-to-x64-ep"
FIXTURE = ROOT / "tests" / "mir_to_x64_ep" / "fixture.ep"
FIXTURE_EXE = BUILD_DIR / "tests" / "mir_to_x64_ep" / "fixture.exe"

EXPECTED = """section .text
add1:
    push rbp
    mov rbp, rsp
    sub rsp, 112
    mov qword [rbp-8], rcx
add1.entry:
    mov rax, qword [rbp-8]
    mov rcx, 1
    add rax, rcx
    mov qword [rbp-16], rax
    mov rax, qword [rbp-16]
    jmp add1.__return
add1.__return:
    add rsp, 112
    pop rbp
    ret
section .text
arith_mix:
    push rbp
    mov rbp, rsp
    sub rsp, 128
    mov qword [rbp-8], rcx
arith_mix.entry:
    mov rax, qword [rbp-8]
    mov rcx, 2
    sub rax, rcx
    mov qword [rbp-16], rax
    mov rax, qword [rbp-16]
    mov rcx, 3
    imul rax, rcx
    mov qword [rbp-24], rax
    mov rax, qword [rbp-24]
    mov rcx, 7
    and rax, rcx
    mov qword [rbp-32], rax
    mov rax, qword [rbp-32]
    jmp arith_mix.__return
arith_mix.__return:
    add rsp, 128
    pop rbp
    ret
section .text
max2:
    push rbp
    mov rbp, rsp
    sub rsp, 128
    mov qword [rbp-8], rcx
    mov qword [rbp-16], rdx
max2.entry:
    mov rax, qword [rbp-8]
    mov rcx, qword [rbp-16]
    cmp rax, rcx
    setg al
    movzx eax, al
    mov qword [rbp-24], rax
    mov rax, qword [rbp-24]
    test rax, rax
    jnz max2.then
    jmp max2.else
max2.then:
    mov rax, qword [rbp-8]
    jmp max2.__return
max2.else:
    mov rax, qword [rbp-16]
    jmp max2.__return
max2.__return:
    add rsp, 128
    pop rbp
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
            str(ROOT / "src" / "mir.ep"),
            str(ROOT / "src" / "x64.ep"),
            str(ROOT / "src" / "mir_to_x64.ep"),
            str(FIXTURE),
            "--out-dir",
            str(BUILD_DIR),
        ],
        "compile tests/mir_to_x64_ep/fixture.ep",
    )
    if not FIXTURE_EXE.exists():
        raise RuntimeError(f"expected fixture exe at {FIXTURE_EXE}")

    result = run_checked([str(FIXTURE_EXE)], "run tests/mir_to_x64_ep/fixture.exe")
    if result.stdout != EXPECTED:
        print("  FAIL  mir_to_x64_ep integer ops and branches")
        print_diff(EXPECTED, result.stdout)
        return 1
    print("  PASS  mir_to_x64_ep integer ops and branches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
