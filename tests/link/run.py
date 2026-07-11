#!/usr/bin/env python3
"""PE linker byte-identity tests using Epic-produced COFF objects."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from compiler_runner import compile_program, compile_tool


LINK_EXE = ROOT / "build" / "tests" / "link.exe"
OUT = ROOT / "build" / "tests" / "link"


def main():
    compile_tool(ROOT / "src" / "link.ep", [ROOT / "src" / "util.ep", ROOT / "src" / "link.ep"], LINK_EXE)
    for path in sorted((ROOT / "examples").glob("*.ep")):
        expected = OUT / f"{path.stem}.expected.exe"
        actual = OUT / f"{path.stem}.actual.exe"
        compile_program(path, expected)
        obj = Path(str(expected) + ".obj")
        result = subprocess.run([str(LINK_EXE), str(obj), "-o", str(actual)], cwd=ROOT, capture_output=True)
        if result.returncode != 0 or not actual.is_file() or actual.read_bytes() != expected.read_bytes():
            print(f"  FAIL  {path.relative_to(ROOT)}")
            print((result.stdout + result.stderr).decode("utf-8", errors="replace")[-1000:])
            return 1
        print(f"  PASS  {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
