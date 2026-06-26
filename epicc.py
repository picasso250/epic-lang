"""
Epic v0 compiler CLI.

Usage:
    python epicc.py <file.ep>
"""

import argparse
import os
import subprocess
import sys

from codegen import Emitter
from helpers_asm import STR_ALLOC_HELPER, ITOA_HELPER, SYSTEM_HELPER, LISTDIR_HELPER
from lexer import LexError, lex
from parser import ParseError, Parser

# ── paths ────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.join(SCRIPT_DIR, "tools")
NASM = os.path.join(TOOLS_DIR, "nasm.exe")
LLD_LINK = os.path.join(TOOLS_DIR, "lld-link.exe")
LINK_PY = os.path.join(SCRIPT_DIR, "link.py")
SDK_LIB = r"C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\um\x64"


# ═══════════════════════════════════════════════════════════════════════════
#  Driver
# ═══════════════════════════════════════════════════════════════════════════

def compile_file(input_path):
    base = os.path.splitext(os.path.basename(input_path))[0]
    asm_path = base + ".asm"
    obj_path = base + ".obj"
    exe_path = base + ".exe"

    print(f"[1/4] Reading {input_path}")
    with open(input_path, "r", encoding="utf-8") as f:
        source = f.read()

    print(f"[2/4] Compiling → {asm_path}")
    tokens = lex(source)
    parser = Parser(tokens)
    ast = parser.parse_program()

    emitter = Emitter(asm_path)
    emitter.emit_program(ast)
    emitter.emit(STR_ALLOC_HELPER)
    emitter.emit(ITOA_HELPER)
    emitter.emit(SYSTEM_HELPER)
    emitter.emit(LISTDIR_HELPER)
    emitter.close()

    print(f"[3/4] Assembling → {obj_path}")
    result = subprocess.run(
        [NASM, "-f", "win64", asm_path, "-o", obj_path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("NASM error:\n" + result.stderr[:500])

    print(f"[4/4] Linking → {exe_path}")
    result = subprocess.run(
        [sys.executable, LINK_PY, obj_path, "-o", exe_path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("Link error:\n" + result.stderr[:500])

    size = os.path.getsize(exe_path)
    print(f"  OK: {exe_path} ({size} bytes)")


# ═══════════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════════

def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="epicc.py",
        description="Epic v0 compiler",
    )
    parser.add_argument("input", help="input .ep source file")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if not os.path.exists(args.input):
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        return 1

    try:
        compile_file(args.input)
    except (LexError, ParseError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
