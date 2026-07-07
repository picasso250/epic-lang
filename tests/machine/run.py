#!/usr/bin/env python3
"""Self-hosted machine byte emission oracle tests."""

from __future__ import annotations

import difflib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bootstrap"))

from machine import MachineObjectBuilder  # noqa: E402
from x64 import I, MS, R, LabelRef, Symbol, X64Program  # noqa: E402

EPICC = ROOT / "bootstrap" / "epic.py"
BUILD_DIR = ROOT / "build" / "machine-ep"
FIXTURE = ROOT / "tests" / "machine" / "fixture.ep"
FIXTURE_EXE = BUILD_DIR / "tests" / "machine" / "fixture.exe"


def build_x64_fixture() -> X64Program:
    program = X64Program()
    program.global_("_start")
    program.extern("ExitProcess")
    program.section(".data")
    program.data_bytes("msg", [65, 0])
    program.data_zero("scratch", 8)
    program.section(".text")
    program.label("_start")
    program.inst("mov", R("rax"), I(1))
    program.inst("cmp", R("rax"), I(1))
    program.inst("jz", LabelRef("done"))
    program.inst("mov", R("rax"), I(2))
    program.label("done")
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


def python_expected() -> str:
    builder = MachineObjectBuilder(build_x64_fixture())
    builder._emit_program()
    builder._patch_internal_fixups()
    return machine_dump(builder.text, builder.data)


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


def main() -> int:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    run_checked(
        [
            sys.executable,
            str(EPICC),
            "--main",
            str(FIXTURE),
            str(ROOT / "src" / "util.ep"),
            str(ROOT / "src" / "x64.ep"),
            str(ROOT / "src" / "machine.ep"),
            str(FIXTURE),
            "--out-dir",
            str(BUILD_DIR),
        ],
        "compile tests/machine/fixture.ep",
    )
    if not FIXTURE_EXE.exists():
        raise RuntimeError(f"expected fixture exe at {FIXTURE_EXE}")

    expected = python_expected()
    actual = run_checked([str(FIXTURE_EXE)], "run tests/machine/fixture.exe").stdout
    if actual != expected:
        print("  FAIL  machine byte emission fixture")
        print_diff(expected, actual)
        return 1
    print("  PASS  machine byte emission fixture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
