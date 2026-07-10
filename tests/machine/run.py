#!/usr/bin/env python3
"""Self-hosted machine byte emission oracle tests."""

from __future__ import annotations

import difflib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bootstrap"))

from ast_to_mir import ast_to_mir  # noqa: E402
from lexer import lex  # noqa: E402
from machine import MachineObjectBuilder  # noqa: E402
from mir_to_x64 import MirLower  # noqa: E402
from parser import Parser  # noqa: E402
from sema import analyze_program  # noqa: E402
from x64 import I, MS, R, LabelRef, Mem, Symbol, X64DataBytes, X64DataZero, X64Extern, X64Label, X64Program  # noqa: E402

EPICC = ROOT / "bootstrap" / "epic.py"
BUILD_DIR = ROOT / "build" / "machine-ep"
FIXTURE = ROOT / "tests" / "machine" / "fixture.ep"
DRIVER = ROOT / "tests" / "machine" / "driver.ep"
FIXTURE_EXE = BUILD_DIR / "tests" / "machine" / "fixture.exe"
DRIVER_EXE = BUILD_DIR / "tests" / "machine" / "driver.exe"
EXAMPLES_DIR = ROOT / "examples"
AST_TO_MIR_PASS_DIR = ROOT / "tests" / "ast_to_mir" / "pass"
EXAMPLE_CASES = sorted(EXAMPLES_DIR.glob("*.ep"))
AST_TO_MIR_PASS_CASES = sorted(AST_TO_MIR_PASS_DIR.glob("*.ep"))
USER_CASES = EXAMPLE_CASES + AST_TO_MIR_PASS_CASES
EXPECTED_PASS = {path.relative_to(ROOT).as_posix() for path in USER_CASES}


def build_x64_fixture() -> X64Program:
    program = X64Program()
    program.global_("_start")
    program.extern("ExitProcess")
    program.section(".data")
    program.data_bytes("msg", [65, 0])
    program.data_zero("scratch", 8)
    program.section(".text")
    start = program.new_symbol_label("_start")
    done = program.new_label()
    program.bind_label(start)
    program.inst("mov", R("rax"), I(1))
    program.inst("cmp", R("rax"), I(1))
    program.inst("jz", program.label_ref(done))
    program.inst("mov", R("rax"), I(2))
    program.bind_label(done)
    program.inst("lea", R("rdx"), MS("msg"))
    program.inst("mov", R("rcx"), R("rax"))
    program.inst("call", Symbol("ExitProcess"))
    program.inst("ret")
    return program


def machine_dump(text: bytes | bytearray, data: bytes | bytearray) -> str:
    lines = ["TEXT"]
    lines.extend(str(b) for b in text)
    lines.append("DATA")
    lines.extend(str(b) for b in data)
    return "\n".join(lines) + "\n"


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


def object_dump(program: X64Program) -> str:
    builder = MachineObjectBuilder(machine_program_with_externs(program))
    builder._emit_program()
    builder._patch_internal_fixups()
    return machine_dump(builder.text, builder.data)


def python_fixture_expected() -> str:
    return object_dump(build_x64_fixture())


def python_string_globals(program) -> dict[str, tuple[str, str, int]]:
    out: dict[str, tuple[str, str, int]] = {}
    for glob in program.globals:
        if glob.name == "argv":
            continue
        if glob.init is None:
            continue
        out[glob.name] = (glob.name + "_header", glob.name + "_data", len(glob.init))
    return out


def python_user_machine(path: Path) -> str:
    source = path.read_text(encoding="utf-8")
    typed = analyze_program(Parser(lex(source)).parse_program())
    mir = ast_to_mir(typed)
    parts: list[str] = []
    for fn in mir.functions[: len(typed.funcs)]:
        lower = MirLower(mir)
        lower.string_globals = python_string_globals(mir)
        lower.x64.section(".text")
        lower._lower_function(fn)
        parts.append(object_dump(lower.x64))
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
        if i >= 120:
            print("  ... diff truncated ...")
            break
        print(line)


def compile_ep_tool(main_src: Path, extra_sources: list[Path], label: str) -> Path:
    run_checked(
        [
            sys.executable,
            str(EPICC),
            "--main",
            str(main_src),
            *(str(p) for p in extra_sources),
            str(main_src),
            "--out-dir",
            str(BUILD_DIR),
        ],
        label,
    )
    return BUILD_DIR / main_src.relative_to(ROOT).with_suffix(".exe")


def ep_user_machine(path: Path) -> str:
    return run_checked([str(DRIVER_EXE), str(path)], f"EP machine {path.relative_to(ROOT)}").stdout


def check_text_case(label: str, expected: str, actual: str) -> bool:
    if actual == expected:
        print(f"  PASS  {label}")
        return True
    print(f"  FAIL  {label}")
    print_diff(expected, actual)
    return False


def main() -> int:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    fixture_exe = compile_ep_tool(
        FIXTURE,
        [ROOT / "src" / "util.ep", ROOT / "src" / "x64.ep", ROOT / "src" / "machine.ep"],
        "compile tests/machine/fixture.ep",
    )
    if fixture_exe != FIXTURE_EXE or not FIXTURE_EXE.exists():
        raise RuntimeError(f"expected fixture exe at {FIXTURE_EXE}")
    driver_exe = compile_ep_tool(
        DRIVER,
        [
            ROOT / "src" / "util.ep",
            ROOT / "src" / "lexer.ep",
            ROOT / "src" / "parser.ep",
            ROOT / "src" / "sema.ep",
            ROOT / "src" / "mir.ep",
            ROOT / "src" / "ast_to_mir.ep",
            ROOT / "src" / "x64.ep",
            ROOT / "src" / "mir_to_x64.ep",
            ROOT / "src" / "machine.ep",
        ],
        "compile tests/machine/driver.ep",
    )
    if driver_exe != DRIVER_EXE or not DRIVER_EXE.exists():
        raise RuntimeError(f"expected driver exe at {DRIVER_EXE}")

    failed = 0
    if not check_text_case(
        "machine byte emission fixture",
        python_fixture_expected(),
        run_checked([str(FIXTURE_EXE)], "run tests/machine/fixture.exe").stdout,
    ):
        failed += 1

    passed = 0
    todo = 0
    unexpected_pass = 0
    for path in USER_CASES:
        rel = path.relative_to(ROOT).as_posix()
        should_pass = rel in EXPECTED_PASS
        try:
            expected = python_user_machine(path)
            actual = ep_user_machine(path)
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
    print(f"\nmachine examples: {passed}/{total} expected-pass, {unexpected_pass} unexpected-pass, {todo} todo, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
