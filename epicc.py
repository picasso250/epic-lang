"""
Epic v0 compiler CLI.

Usage:
    python epicc.py <file.ep>              # use default lld-link
    python epicc.py <file.ep> --linker py  # use link.py
"""

import argparse
import os
import subprocess
import sys

from codegen import Emitter
from helpers_asm import STR_ALLOC_HELPER, ITOA_HELPER, SYSTEM_HELPER, LISTDIR_HELPER, READ_FILE_HELPER
from lexer import LexError, lex
from parser import ParseError, Parser

# ── paths ────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.join(SCRIPT_DIR, "tools")
NASM = os.path.join(TOOLS_DIR, "nasm.exe")
LLD_LINK = os.path.join(TOOLS_DIR, "lld-link.exe")
LINK_PY = os.path.join(SCRIPT_DIR, "link.py")
SDK_LIB = r"C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\um\x64"
BUILD_DIR = os.path.join(SCRIPT_DIR, "build")


# ═══════════════════════════════════════════════════════════════════════════
#  Driver
# ═══════════════════════════════════════════════════════════════════════════

def _output_paths(input_path, out_dir):
    abs_input = os.path.abspath(input_path)
    try:
        rel = os.path.relpath(abs_input, SCRIPT_DIR)
        if rel.startswith(".."):
            rel = os.path.basename(abs_input)
    except ValueError:
        rel = os.path.basename(abs_input)
    rel_base = os.path.splitext(rel)[0]
    out_base = os.path.join(out_dir, rel_base)
    os.makedirs(os.path.dirname(out_base), exist_ok=True)
    return out_base + ".asm", out_base + ".obj", out_base + ".exe"


def compile_file(input_path, linker="lld-link", out_dir=BUILD_DIR):
    asm_path, obj_path, exe_path = _output_paths(input_path, out_dir)

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
    emitter.emit(READ_FILE_HELPER)
    emitter.close()

    print(f"[3/4] Assembling → {obj_path}")
    result = subprocess.run(
        [NASM, "-f", "win64", asm_path, "-o", obj_path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("NASM error:\n" + result.stderr[:500])

    print(f"[4/4] Linking (via {linker}) → {exe_path}")
    if linker == "py":
        result = subprocess.run(
            [sys.executable, LINK_PY, obj_path, "-o", exe_path],
            capture_output=True, text=True,
        )
    else:
        result = subprocess.run(
            [LLD_LINK, "/subsystem:console", f"/entry:_start",
             f"/out:{exe_path}", obj_path,
             os.path.join(SDK_LIB, "kernel32.lib")],
            capture_output=True, text=True,
        )
    if result.returncode != 0:
        raise RuntimeError("Link error:\n" + result.stderr[:500])

    size = os.path.getsize(exe_path)
    print(f"  OK: {exe_path} ({size} bytes)")
    return exe_path


# ═══════════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════════

def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="epicc.py",
        description="Epic v0 compiler",
    )
    parser.add_argument("input", help="input .ep source file")
    parser.add_argument("--linker", choices=["lld-link", "py"], default="lld-link",
                        help="linker to use (default: lld-link)")
    parser.add_argument("--out-dir", default=BUILD_DIR,
                        help="output directory (default: build)")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if not os.path.exists(args.input):
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        return 1

    try:
        compile_file(args.input, linker=args.linker, out_dir=args.out_dir)
    except (LexError, ParseError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
