#!/usr/bin/env python3
"""AST-to-MIR physical layout contract test."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from compiler_runner import compile_tool


def main():
    case = ROOT / "tests" / "ast_to_mir" / "pass" / "pass_m36_natural_struct_layout.ep"
    sources = [ROOT / "src" / name for name in ("util.ep", "lexer.ep", "parser.ep", "sema.ep", "mir.ep", "ast_to_mir.ep")]
    tool = compile_tool(ROOT / "src" / "ast_to_mir.ep", sources, ROOT / "build" / "tests" / "ast_to_mir.exe")
    result = subprocess.run([str(tool), str(case)], cwd=ROOT, capture_output=True)
    required = (b"type Compact = struct size 32 align 8", b"i8 @0", b"u16 @2", b"i16 @4", b"u32 @8", b"i32 @12", b"i8 @16", b"i64 @24")
    if result.returncode != 0 or any(part not in result.stdout for part in required):
        print((result.stdout + result.stderr).decode("utf-8", errors="replace")[-2000:])
        return 1
    print("  PASS  natural struct layout metadata")

    case = ROOT / "tests" / "ast_to_mir" / "pass" / "function_address.ep"
    result = subprocess.run([str(tool), str(case)], cwd=ROOT, capture_output=True)
    if result.returncode != 0 or b"call void __ep_import$kernel32.dll$ConsumeCallback(ptr callback)" not in result.stdout:
        print((result.stdout + result.stderr).decode("utf-8", errors="replace")[-2000:])
        return 1
    print("  PASS  function address symbol operand")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
