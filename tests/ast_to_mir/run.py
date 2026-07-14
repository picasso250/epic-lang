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

    case = ROOT / "tests" / "ast_to_mir" / "pass" / "shift_count_checks.ep"
    result = subprocess.run([str(tool), str(case)], cwd=ROOT, capture_output=True)
    output = result.stdout.decode("utf-8", errors="replace")
    if result.returncode != 0:
        print((result.stdout + result.stderr).decode("utf-8", errors="replace")[-2000:])
        return 1
    try:
        literal_start = output.index("define i64 @literal_shift(")
        converted_start = output.index("define i64 @converted_shift(")
        dynamic_start = output.index("define i64 @dynamic_shift(")
        main_start = output.index("define void @main(")
    except ValueError:
        print(output[-3000:])
        return 1
    literal_body = output[literal_start:converted_start]
    converted_body = output[converted_start:dynamic_start]
    dynamic_body = output[dynamic_start:main_start]
    if (
        " = shr " not in literal_body
        or "shift.fail" in literal_body
        or "shift.fail" not in converted_body
        or "shift.fail" not in dynamic_body
    ):
        print(output[-3000:])
        return 1
    print("  PASS  shift count static/dynamic checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
