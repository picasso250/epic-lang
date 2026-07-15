#!/usr/bin/env python3
"""Canonical MIR text tests for the Epic implementation."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from compiler_runner import compile_tool


SOURCES = [ROOT / "src" / name for name in ("util.ep", "mir.ep", "mir_text.ep")]
BUILD = ROOT / "build" / "tests" / "mir"


EXPECTED = """declare void @__ep_import$kernel32.dll$ExitProcess(i64)

type Data = struct size 16 align 8 { i8 @0, i16 @2, i32 @4, i64 @8 }

type Zed = struct size 8 align 8 { ptr @0 }

global @argv: ptr

global @counter: i64 = 42

global @str.0: ptr = bytes "A\\n\\\"\\\\\\x00\\xFF//tail"

define i64 @identity(i64 %1) {
entry:
  ret i64 %1
}

define i64 @main() {
entry:
  %1: ptr = gep struct Zed, ptr null, i64 1
  %2: ptr = gep struct Data, ptr null, i64 1
  call void __ep_import$kernel32.dll$ExitProcess(i64 0)
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

    negative = compile_tool(ROOT / "tests" / "mir" / "legacy_extern_fail.ep", [*SOURCES, ROOT / "tests" / "mir" / "legacy_extern_fail.ep"], BUILD / "legacy_extern_fail.exe")
    result = subprocess.run([str(negative)], cwd=ROOT, capture_output=True, text=True, encoding="ascii", errors="replace")
    output = result.stdout + result.stderr
    if result.returncode == 0 or "expected declare, type, global, or define" not in output:
        print("  FAIL  legacy MIR extern negative fixture")
        print(output)
        return 1
    print("  PASS  legacy MIR extern rejected")

    reachability = compile_tool(
        ROOT / "tests" / "mir" / "function_address_reachability.ep",
        [ROOT / "src" / "util.ep", ROOT / "src" / "mir.ep", ROOT / "tests" / "mir" / "function_address_reachability.ep"],
        BUILD / "function_address_reachability.exe",
    )
    result = subprocess.run([str(reachability)], cwd=ROOT, capture_output=True, text=True, encoding="ascii", errors="replace")
    if result.returncode != 0:
        print("  FAIL  MIR function-address reachability")
        print(result.stdout + result.stderr)
        return 1
    print("  PASS  MIR function-address reachability")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
