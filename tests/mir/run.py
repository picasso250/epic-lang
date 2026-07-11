#!/usr/bin/env python3
"""Canonical MIR text and backend ABI tests for the Epic implementation."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from compiler_runner import compile_tool


SOURCES = [ROOT / "src" / name for name in ("util.ep", "mir.ep", "mir_text.ep", "backend_abi.ep")]
BUILD = ROOT / "build" / "tests" / "mir"


EXPECTED = """extern void @ExitProcess(i64)

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


def main():
    canonical = compile_tool(ROOT / "tests" / "mir" / "type_decl.ep", [*SOURCES, ROOT / "tests" / "mir" / "type_decl.ep"], BUILD / "type_decl.exe")
    result = subprocess.run([str(canonical)], cwd=ROOT, capture_output=True, text=True, encoding="ascii")
    if result.returncode != 0 or result.stdout.replace("\r\n", "\n") != EXPECTED:
        print("  FAIL  MIR canonical text")
        print(result.stdout)
        return 1
    print("  PASS  MIR canonical text")

    negative = compile_tool(ROOT / "tests" / "mir" / "backend_abi_fail.ep", [*SOURCES, ROOT / "tests" / "mir" / "backend_abi_fail.ep"], BUILD / "backend_abi_fail.exe")
    result = subprocess.run([str(negative)], cwd=ROOT, capture_output=True, text=True, encoding="ascii", errors="replace")
    output = result.stdout + result.stderr
    if result.returncode == 0 or "unsupported backend extern: ExitProces" not in output:
        print("  FAIL  backend ABI negative fixture")
        print(output)
        return 1
    print("  PASS  backend ABI negative fixture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
