#!/usr/bin/env python3
"""Self-hosted COFF object byte oracle tests."""

from __future__ import annotations

import difflib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bootstrap"))

from ast_to_mir import ast_to_mir  # noqa: E402
from coff import build_coff_obj  # noqa: E402
from lexer import lex  # noqa: E402
from machine import MachineObjectBuilder  # noqa: E402
from mir_to_x64 import MirLower  # noqa: E402
from parser import Parser  # noqa: E402
from sema import analyze_program  # noqa: E402
from x64 import LabelRef, Mem, Symbol, X64DataBytes, X64DataZero, X64Extern, X64Label, X64Program  # noqa: E402

EPICC = ROOT / "bootstrap" / "epic.py"
BUILD_DIR = ROOT / "build" / "coff-ep"
DRIVER = ROOT / "tests" / "coff" / "driver.ep"
DRIVER_EXE = BUILD_DIR / "tests" / "coff" / "driver.exe"
EXAMPLES_DIR = ROOT / "examples"
AST_TO_MIR_PASS_DIR = ROOT / "tests" / "ast_to_mir" / "pass"
EXAMPLE_CASES = sorted(EXAMPLES_DIR.glob("*.ep"))
AST_TO_MIR_PASS_CASES = sorted(AST_TO_MIR_PASS_DIR.glob("*.ep"))
USER_CASES = EXAMPLE_CASES + AST_TO_MIR_PASS_CASES
EXPECTED_PASS = {path.relative_to(ROOT).as_posix() for path in USER_CASES}


def byte_dump(values: bytes | bytearray) -> str:
    return "\n".join(str(b) for b in values) + "\n"


def machine_program_with_externs(program: X64Program) -> X64Program:
    labels = {item.symbol_name for item in program.items if isinstance(item, X64Label) and item.symbol_name is not None}
    labels.update(item.label for item in program.items if isinstance(item, (X64DataBytes, X64DataZero)))
    declared = {item.name for item in program.items if isinstance(item, X64Extern)}
    refs: set[str] = set()
    for item in program.items:
        operands = getattr(item, "operands", ())
        for operand in operands:
            if isinstance(operand, Symbol):
                refs.add(operand.name)
            elif isinstance(operand, LabelRef):
                if operand.label.symbol_name is not None:
                    refs.add(operand.label.symbol_name)
            elif isinstance(operand, Mem) and operand.symbol is not None:
                refs.add(operand.symbol)
    wrapped = X64Program()
    for name in sorted(refs - labels - declared):
        wrapped.extern(name)
    wrapped.items.extend(program.items)
    wrapped.labels.extend(program.labels)
    return wrapped


def python_string_globals(program) -> dict[str, tuple[str, str, int]]:
    out: dict[str, tuple[str, str, int]] = {}
    for glob in program.globals:
        if glob.name == "argv":
            continue
        if glob.init is None:
            continue
        out[glob.name] = (glob.name + "_header", glob.name + "_data", len(glob.init))
    return out


def coff_dump_from_x64(program: X64Program) -> str:
    builder = MachineObjectBuilder(machine_program_with_externs(program))
    builder._emit_program()
    builder._emit_needed_runtime_helpers()
    builder._patch_internal_fixups()
    symbols, text_relocs, data_relocs = builder._build_symbols()
    symbol_map = {name: (section, value) for name, section, value in symbols}
    text_reloc_names = [(off, symbols[index][0]) for off, index in text_relocs]
    data_reloc_names = [(off, symbols[index][0]) for off, index in data_relocs]
    return byte_dump(build_coff_obj(builder.text, builder.data, text_reloc_names, data_reloc_names, symbol_map))


def python_user_coff(path: Path) -> str:
    source = path.read_text(encoding="utf-8")
    typed = analyze_program(Parser(lex(source)).parse_program())
    mir = ast_to_mir(typed)
    parts: list[str] = []
    for fn in mir.functions[: len(typed.funcs)]:
        lower = MirLower(mir)
        lower.string_globals = python_string_globals(mir)
        lower.x64.section(".text")
        lower._lower_function(fn)
        parts.append(coff_dump_from_x64(lower.x64))
    return "".join(parts)


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
        if i >= 160:
            print("  ... diff truncated ...")
            break
        print(line)


def compile_driver() -> Path:
    run_checked(
        [
            sys.executable,
            str(EPICC),
            "--main",
            str(DRIVER),
            str(ROOT / "src" / "util.ep"),
            str(ROOT / "src" / "lexer.ep"),
            str(ROOT / "src" / "parser.ep"),
            str(ROOT / "src" / "sema.ep"),
            str(ROOT / "src" / "mir.ep"),
            str(ROOT / "src" / "ast_to_mir.ep"),
            str(ROOT / "src" / "x64.ep"),
            str(ROOT / "src" / "mir_to_x64.ep"),
            str(ROOT / "src" / "machine.ep"),
            str(ROOT / "src" / "coff.ep"),
            str(DRIVER),
            "--out-dir",
            str(BUILD_DIR),
        ],
        "compile tests/coff/driver.ep",
    )
    return DRIVER_EXE


def ep_user_coff(path: Path) -> str:
    return run_checked([str(DRIVER_EXE), str(path)], f"EP COFF {path.relative_to(ROOT)}").stdout


def main() -> int:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    driver_exe = compile_driver()
    if driver_exe != DRIVER_EXE or not DRIVER_EXE.exists():
        raise RuntimeError(f"expected driver exe at {DRIVER_EXE}")

    failed = 0
    passed = 0
    todo = 0
    unexpected_pass = 0
    for path in USER_CASES:
        rel = path.relative_to(ROOT).as_posix()
        should_pass = rel in EXPECTED_PASS
        try:
            expected = python_user_coff(path)
            actual = ep_user_coff(path)
            ok = actual == expected
        except Exception as exc:
            if should_pass:
                failed += 1
                print(f"  FAIL  {rel}")
                print(f"        {exc}")
            else:
                todo += 1
                print(f"  TODO  {rel}")
                lines = str(exc).splitlines()
                print(f"        {lines[-1] if lines else exc}")
            continue
        if ok:
            if should_pass:
                passed += 1
                print(f"  PASS  {rel}")
            else:
                unexpected_pass += 1
                print(f"  XPASS {rel}")
        else:
            if should_pass:
                failed += 1
                print(f"  FAIL  {rel}")
                print_diff(expected, actual)
            else:
                todo += 1
                print(f"  TODO  {rel}")
                print_diff(expected, actual)
    total = len(USER_CASES)
    print(f"\ncoff examples: {passed}/{total} expected-pass, {unexpected_pass} unexpected-pass, {todo} todo, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
