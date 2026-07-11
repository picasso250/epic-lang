#!/usr/bin/env python3
"""Self-hosted MIR-to-X64 lowering oracle tests."""

from __future__ import annotations

import difflib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bootstrap"))
from ast_to_mir import ast_to_mir  # noqa: E402
from lexer import lex  # noqa: E402
from mir_to_x64 import MirLower  # noqa: E402
from parser import Parser  # noqa: E402
from sema import analyze_program  # noqa: E402
EPICC = ROOT / "bootstrap" / "epic.py"
BUILD_DIR = ROOT / "build" / "mir-to-x64"
DRIVER = ROOT / "tests" / "mir_to_x64" / "driver.ep"
DRIVER_EXE = BUILD_DIR / "tests" / "mir_to_x64" / "driver.exe"
EXAMPLES_DIR = ROOT / "examples"
AST_TO_MIR_PASS_DIR = ROOT / "tests" / "ast_to_mir" / "pass"
EXAMPLE_CASES = sorted(EXAMPLES_DIR.glob("*.ep"))
AST_TO_MIR_PASS_CASES = sorted(AST_TO_MIR_PASS_DIR.glob("*.ep"))
USER_CASES = EXAMPLE_CASES + AST_TO_MIR_PASS_CASES

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


def python_string_globals(program) -> dict[str, tuple[str, str, int]]:
    out: dict[str, tuple[str, str, int]] = {}
    for glob in program.globals:
        if glob.init is None:
            continue
        out[glob.name] = (glob.name + "_header", glob.name + "_data", len(glob.init))
    return out


def print_diff(expected: str, actual: str) -> None:
    for i, line in enumerate(difflib.unified_diff(
        expected.splitlines(), actual.splitlines(), fromfile="expected", tofile="actual", lineterm=""
    )):
        if i >= 120:
            print("  ... diff truncated ...")
            break
        print(line)


def compile_ep_tool(main_src: Path, label: str) -> Path:
    run_checked(
        [
            sys.executable,
            str(EPICC),
            "--main",
            str(main_src),
            str(ROOT / "src" / "util.ep"),
            str(ROOT / "src" / "lexer.ep"),
            str(ROOT / "src" / "parser.ep"),
            str(ROOT / "src" / "sema.ep"),
            str(ROOT / "src" / "mir.ep"),
            str(ROOT / "src" / "ast_to_mir.ep"),
            str(ROOT / "src" / "x64.ep"),
            str(ROOT / "src" / "mir_to_x64.ep"),
            str(main_src),
            "--out-dir",
            str(BUILD_DIR),
        ],
        label,
    )
    return BUILD_DIR / main_src.relative_to(ROOT).with_suffix(".exe")


def python_user_x64(path: Path) -> str:
    source = path.read_text(encoding="utf-8")
    typed = analyze_program(Parser(lex(source)).parse_program())
    program = ast_to_mir(typed)
    parts: list[str] = []
    for fn in program.functions[: len(typed.funcs)]:
        lower = MirLower(program)
        lower.string_globals = python_string_globals(program)
        lower.x64.section(".text")
        lower._lower_function(fn)
        parts.append(lower.x64.text())
    return "".join(parts)


def ep_user_x64(path: Path) -> str:
    result = run_checked([str(DRIVER_EXE), str(path)], f"EP MIR-to-X64 {path.relative_to(ROOT)}")
    return result.stdout


def check_text_case(label: str, expected: str, actual: str) -> bool:
    if actual == expected:
        print(f"  PASS  {label}")
        return True
    print(f"  FAIL  {label}")
    print_diff(expected, actual)
    return False


def main() -> int:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    driver_exe = compile_ep_tool(DRIVER, "compile tests/mir_to_x64/driver.ep")
    if driver_exe != DRIVER_EXE or not DRIVER_EXE.exists():
        raise RuntimeError(f"expected driver exe at {DRIVER_EXE}")

    failed = 0
    for path in USER_CASES:
        rel = str(path.relative_to(ROOT))
        try:
            expected = python_user_x64(path)
            actual = ep_user_x64(path)
        except Exception as exc:
            failed += 1
            print(f"  FAIL  {rel}")
            print(f"        {exc}")
            continue
        if not check_text_case(rel, expected, actual):
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
