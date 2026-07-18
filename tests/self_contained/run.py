#!/usr/bin/env python3
"""Verify that the compiler carries its runtime and resolves embed per source file."""

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


def main() -> int:
    with tempfile.TemporaryDirectory() as temp:
        isolated = Path(temp)
        compiler = isolated / "epic.exe"
        shutil.copy2(ep_runner.compiler_path(), compiler)

        source_dir = isolated / "src"
        source_dir.mkdir()
        (source_dir / "main.ep").write_text(PROGRAM, encoding="utf-8")
        shutil.copy2(ROOT / "src" / "codegen.ep", source_dir / "asset.bin")

        result = subprocess.run(
            [str(compiler), "src/main.ep"],
            cwd=isolated,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(f"  FAIL  isolated compiler failed:\n{result.stderr[-1000:]}")
            return 1

        executable = isolated / "a.exe"
        if not executable.is_file():
            print(f"  FAIL  isolated compiler produced no default a.exe: {executable}")
            return 1
        assembly = isolated / "a.asm"
        if assembly.exists():
            print(f"  FAIL  default compilation unexpectedly produced assembly: {assembly}")
            return 1
        process = subprocess.run([str(executable)], cwd=isolated, timeout=5)
        if process.returncode != 42:
            print(f"  FAIL  embedded byte program returned {process.returncode}, expected 42")
            return 1

        result = subprocess.run(
            [str(compiler), "src/main.ep", "-S"],
            cwd=isolated,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 or not assembly.is_file():
            print("  FAIL  default -S did not produce a.asm")
            return 1
        if not assembly.read_bytes().startswith(b"global _start"):
            print("  FAIL  default a.asm is not Epic assembly")
            return 1

        emitted = isolated / "emitted.asm"
        result = subprocess.run(
            [str(compiler), "src/main.ep", "-S", "-o", str(emitted)],
            cwd=isolated,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 or not emitted.is_file():
            print("  FAIL  -S did not produce the requested assembly file")
            return 1
        if not emitted.read_bytes().startswith(b"global _start"):
            print("  FAIL  -S output is not Epic assembly")
            return 1

        custom = isolated / "custom.exe"
        result = subprocess.run(
            [str(compiler), "-o", str(custom), "src/main.ep"],
            cwd=isolated,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 or not custom.is_file():
            print("  FAIL  -o did not produce the requested executable")
            return 1
        process = subprocess.run([str(custom)], cwd=isolated, timeout=5)
        if process.returncode != 42:
            print(f"  FAIL  custom executable returned {process.returncode}, expected 42")
            return 1

        missing_executable = isolated / "missing" / "failed.exe"
        result = subprocess.run(
            [str(compiler), "-o", str(missing_executable), "src/main.ep"],
            cwd=isolated,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 or "failed to write output file" not in result.stdout:
            print("  FAIL  executable write failure was reported as success")
            return 1

        missing_assembly = isolated / "missing" / "failed.asm"
        result = subprocess.run(
            [str(compiler), "src/main.ep", "-S", "-o", str(missing_assembly)],
            cwd=isolated,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 or "failed to write output file" not in result.stdout:
            print("  FAIL  assembly write failure was reported as success")
            return 1

    print("  PASS  isolated compiler, in-memory pipeline, -S, -o, and write failures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
