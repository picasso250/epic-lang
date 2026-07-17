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

        executable = isolated / "build" / "epic" / "src_main.ep.exe"
        if not executable.is_file():
            print(f"  FAIL  isolated compiler produced no executable: {executable}")
            return 1
        process = subprocess.run([str(executable)], cwd=isolated, timeout=5)
        if process.returncode != 42:
            print(f"  FAIL  embedded byte program returned {process.returncode}, expected 42")
            return 1

    print("  PASS  isolated epic.exe compiled and ran mutable embedded bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
