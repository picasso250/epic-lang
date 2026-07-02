"""
Epic reference compiler CLI.

Usage:
    python bootstrap/epic.py <file.ep>
    python bootstrap/epic.py <file.ep> --linker lld-link
    python bootstrap/epic.py --main src/epic.ep src/epic.ep src/parser.ep
"""

import argparse
import importlib.util
import os
import subprocess
import sys
import time

from codegen import Emitter
from machine import write_machine_obj
from mir_codegen import ast_to_mir
from mir_lower import lower_mir_to_x64
from ast_nodes import ProgramNode
from lexer import LexError, lex
from parser import ParseError, Parser

# ── paths ────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
TOOLS_DIR = os.path.join(ROOT_DIR, "tools")
NASM = os.path.join(TOOLS_DIR, "nasm.exe")
LLD_LINK = os.path.join(TOOLS_DIR, "lld-link.exe")
LINK_PY = os.path.join(ROOT_DIR, "link.py")
SDK_LIB = r"C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\um\x64"
BUILD_DIR = os.path.join(ROOT_DIR, "build")
RUNTIME_DIR = os.path.join(ROOT_DIR, "runtime")
RUNTIME_ASM_FILES = [
    "str_alloc.asm",
    "str_repr.asm",
    "bytes.asm",
    "str_cat.asm",
    "str_slice.asm",
    "str_replace_char.asm",
    "str_starts_with.asm",
    "str_find.asm",
    "str_trim.asm",
    "extend_i8.asm",
    "itoa.asm",
    "argv.asm",
    "system.asm",
    "read_file.asm",
    "write_file.asm",
]


def _now():
    return time.perf_counter()


def _print_timing(label, start):
    print(f"  timing: {label}: {_now() - start:.3f}s", flush=True)


def _link_with_python(obj_path, exe_path):
    spec = importlib.util.spec_from_file_location("epic_link", LINK_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.link(obj_path, exe_path)


# ═══════════════════════════════════════════════════════════════════════════
#  Driver
# ═══════════════════════════════════════════════════════════════════════════

def _output_paths(input_path, out_dir):
    abs_input = os.path.abspath(input_path)
    try:
        rel = os.path.relpath(abs_input, ROOT_DIR)
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
    types = []
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

        for typ in getattr(ast, "types", []):
            if typ.name in seen_structs:
                raise RuntimeError(
                    f"Duplicate type {typ.name}: {input_path} and {seen_structs[typ.name]}"
                )
            seen_structs[typ.name] = input_path
            types.append(typ)

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

    return ProgramNode(funcs=funcs, structs=structs, types=types)


def compile_files(input_paths, main_path=None, linker="py", out_dir=BUILD_DIR, backend="machine"):
    total_start = _now()
    main_path = main_path or input_paths[0]
    asm_path, obj_path, exe_path = _output_paths(main_path, out_dir)

    print(f"[1/4] Reading {len(input_paths)} file(s)")
    stage_start = _now()
    ast = _merge_programs(input_paths, main_path)
    _print_timing("read+lex+parse+merge", stage_start)

    print(f"[2/4] Compiling → {asm_path}")
    stage_start = _now()
    if backend == "machine":
        mir_program = ast_to_mir(ast)
        machine_program = lower_mir_to_x64(mir_program)
        with open(asm_path, "w", encoding="utf-8", newline="\n") as out:
            out.write(machine_program.text())
    else:
        emitter = Emitter(asm_path)
        emitter.emit_program(ast)
        _emit_runtime_helpers(emitter)
        emitter.close()
    _print_timing("emit machine" if backend == "machine" else "emit asm", stage_start)

    print(f"[3/4] Assembling → {obj_path}")
    stage_start = _now()
    if backend == "machine":
        write_machine_obj(machine_program, obj_path)
    else:
        result = subprocess.run(
            [NASM, "-f", "win64", asm_path, "-o", obj_path],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError("NASM error:\n" + result.stderr[:500])
    _print_timing("assemble", stage_start)

    print(f"[4/4] Linking (via {linker}) → {exe_path}")
    stage_start = _now()
    if linker == "py":
        _link_with_python(obj_path, exe_path)
        result = subprocess.CompletedProcess([LINK_PY, obj_path, "-o", exe_path], 0, "", "")
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
    _print_timing("link", stage_start)

    size = os.path.getsize(exe_path)
    print(f"  OK: {exe_path} ({size} bytes)")
    _print_timing("total", total_start)
    return exe_path


def compile_file(input_path, linker="py", out_dir=BUILD_DIR, backend="machine"):
    return compile_files([input_path], main_path=input_path, linker=linker, out_dir=out_dir, backend=backend)


# ═══════════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════════

def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="epic.py",
        description="Epic reference compiler",
    )
    parser.add_argument("inputs", nargs="+", help="input .ep source files")
    parser.add_argument("--main", help="file whose main function is the program entry")
    parser.add_argument("--linker", choices=["lld-link", "py"], default="py",
                        help="linker to use (default: py)")
    parser.add_argument("--out-dir", default=BUILD_DIR,
                        help="output directory (default: build)")
    parser.add_argument("--backend", choices=["asm", "machine"], default="machine",
                        help="object backend to use (default: machine)")
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
            backend=args.backend,
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
