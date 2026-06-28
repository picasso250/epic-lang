"""
Epic v0 compiler CLI.

Usage:
    python epicc.py <file.ep>              # use default lld-link
    python epicc.py <file.ep> --linker py  # use link.py
    python epicc.py --main main.ep main.ep lib.ep
"""

import argparse
import os
import subprocess
import sys

from codegen import Emitter
from ast_nodes import ProgramNode
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
RUNTIME_DIR = os.path.join(SCRIPT_DIR, "runtime")
RUNTIME_ASM_FILES = [
    "str_alloc.asm",
    "itoa.asm",
    "argv.asm",
    "system.asm",
    "read_file.asm",
    "write_file.asm",
    "append_file.asm",
]


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


def _parse_file(input_path):
    print(f"      Reading {input_path}")
    with open(input_path, "r", encoding="utf-8") as f:
        source = f.read()
    tokens = lex(source)
    parser = Parser(tokens)
    return parser.parse_program()


def _emit_runtime_helpers(emitter):
    for name in RUNTIME_ASM_FILES:
        path = os.path.join(RUNTIME_DIR, name)
        with open(path, "r", encoding="utf-8") as f:
            emitter.emit(f.read().rstrip())


def _merge_programs(input_paths, main_path):
    funcs = []
    structs = []
    seen_funcs = {}
    seen_structs = {}
    found_main = False
    main_abs = os.path.abspath(main_path)

    for input_path in input_paths:
        ast = _parse_file(input_path)
        is_main_file = os.path.abspath(input_path) == main_abs

        for struct in ast.structs:
            if struct.name in seen_structs:
                raise RuntimeError(
                    f"Duplicate struct {struct.name}: {input_path} and {seen_structs[struct.name]}"
                )
            seen_structs[struct.name] = input_path
            structs.append(struct)

        for func in ast.funcs:
            if func.name == "main" and not is_main_file:
                continue
            if func.name == "main":
                found_main = True
            if func.name in seen_funcs:
                raise RuntimeError(
                    f"Duplicate function {func.name}: {input_path} and {seen_funcs[func.name]}"
                )
            seen_funcs[func.name] = input_path
            funcs.append(func)

    if not found_main:
        raise RuntimeError(f"Main file has no main function: {main_path}")

    return ProgramNode(funcs=funcs, structs=structs)


def compile_files(input_paths, main_path=None, linker="lld-link", out_dir=BUILD_DIR):
    main_path = main_path or input_paths[0]
    asm_path, obj_path, exe_path = _output_paths(main_path, out_dir)

    print(f"[1/4] Reading {len(input_paths)} file(s)")
    ast = _merge_programs(input_paths, main_path)

    print(f"[2/4] Compiling → {asm_path}")
    emitter = Emitter(asm_path)
    emitter.emit_program(ast)
    _emit_runtime_helpers(emitter)
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
            [LLD_LINK, "/subsystem:console", "/timestamp:0", f"/entry:_start",
             f"/out:{exe_path}", obj_path,
             os.path.join(SDK_LIB, "kernel32.lib"),
             os.path.join(SDK_LIB, "user32.lib")],
            capture_output=True, text=True,
        )
    if result.returncode != 0:
        raise RuntimeError("Link error:\n" + result.stderr[:500])

    size = os.path.getsize(exe_path)
    print(f"  OK: {exe_path} ({size} bytes)")
    return exe_path


def compile_file(input_path, linker="lld-link", out_dir=BUILD_DIR):
    return compile_files([input_path], main_path=input_path, linker=linker, out_dir=out_dir)


# ═══════════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════════

def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="epicc.py",
        description="Epic v0 compiler",
    )
    parser.add_argument("inputs", nargs="+", help="input .ep source files")
    parser.add_argument("--main", help="file whose main function is the program entry")
    parser.add_argument("--linker", choices=["lld-link", "py"], default="lld-link",
                        help="linker to use (default: lld-link)")
    parser.add_argument("--out-dir", default=BUILD_DIR,
                        help="output directory (default: build)")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)

    for input_path in args.inputs:
        if not os.path.exists(input_path):
            print(f"Error: file not found: {input_path}", file=sys.stderr)
            return 1
    if args.main:
        if not os.path.exists(args.main):
            print(f"Error: file not found: {args.main}", file=sys.stderr)
            return 1
    elif len(args.inputs) > 1:
        print("Error: --main is required when compiling multiple files", file=sys.stderr)
        return 1

    try:
        compile_files(
            args.inputs,
            main_path=args.main or args.inputs[0],
            linker=args.linker,
            out_dir=args.out_dir,
        )
    except (LexError, ParseError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
