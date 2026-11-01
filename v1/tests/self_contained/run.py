#!/usr/bin/env python3
"""Verify the isolated v1 compiler, default outputs, -o, and embedded files."""

import shutil
import subprocess
import tempfile
from pathlib import Path


TESTS = Path(__file__).resolve().parents[1]
ROOT = TESTS.parent

import sys

sys.path.insert(0, str(TESTS))
import ep_runner


PROGRAM = """fun main(): void {
    let first = embed("asset.bin")
    let second = embed("asset.bin")
    first.data[0] = 42
    if second.data[0] == 42 {
        os.ExitProcess(1)
    }
    os.ExitProcess(first.data[0])
}
"""


def compile_program(compiler: Path, isolated: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(compiler), *args],
        cwd=isolated,
        capture_output=True,
        text=True,
        timeout=30,
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as temp:
        isolated = Path(temp)
        compiler = isolated / "epic.exe"
        shutil.copy2(ep_runner.compiler_path(), compiler)

        source_dir = isolated / "src"
        source_dir.mkdir()
        (source_dir / "main.ep").write_text(PROGRAM, encoding="utf-8")
        shutil.copy2(ROOT / "src" / "codegen.ep", source_dir / "asset.bin")

        result = compile_program(compiler, isolated, "src/main.ep")
        if result.returncode != 0:
            print(f"  FAIL  isolated compiler failed:\n{result.stderr[-1000:]}")
            return 1

        executable = isolated / "a.exe"
        assembly = isolated / "a.asm"
        if not executable.is_file() or not assembly.is_file():
            print("  FAIL  default compilation did not produce a.asm and a.exe")
            return 1
        process = subprocess.run([str(executable)], cwd=isolated, timeout=5)
        if process.returncode != 42:
            print(f"  FAIL  embedded byte program returned {process.returncode}, expected 42")
            return 1

        custom = isolated / "custom.exe"
        result = compile_program(compiler, isolated, "-o", str(custom), "src/main.ep")
        if result.returncode != 0 or not custom.is_file():
            print("  FAIL  -o did not produce the requested executable")
            return 1

        result = compile_program(compiler, isolated, "-o")
        if result.returncode == 0:
            print("  FAIL  missing -o path was accepted")
            return 1

    print("  PASS  isolated compiler, a.exe default, -o, and mutable embedded bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
