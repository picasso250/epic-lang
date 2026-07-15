#!/usr/bin/env python3
"""X64IR canonical pretty-print test for the Epic implementation."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from compiler_runner import compile_tool


FIXTURE = ROOT / "tests" / "x64" / "fixture.ep"
EXE = ROOT / "build" / "tests" / "x64.exe"
EXPECTED = """global _start
extern ExitProcess
section .rdata
ro: db 7
section .data
msg: db 65, 255, 0
scratch: times 8 db 0
section .text
_start:
    mov rax, 1
    cmp rax, 1
    jz .L1
    mov rax, 2
.L1:
    lea rdx, qword [msg]
    mov rcx, rax
    call ExitProcess
    ret
"""


def main():
    compile_tool(FIXTURE, [ROOT / "src" / "util.ep", ROOT / "src" / "x64.ep", FIXTURE], EXE)
    result = subprocess.run([str(EXE)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0 or result.stdout != EXPECTED:
        print("  FAIL  X64IR canonical pretty print")
        print(result.stdout)
        return 1
    print("  PASS  X64IR canonical pretty print")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
