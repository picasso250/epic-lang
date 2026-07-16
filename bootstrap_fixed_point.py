#!/usr/bin/env python3
"""Build Epic v1 from v0, then verify two self-hosted generations match."""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
FIXED_POINT = BUILD / "fixed-point"
SEED = BUILD / "epic-v1.exe"
SELF_OUTPUT = BUILD / "epic" / "src_epic.ep.exe"
SOURCES = ("src/epic.ep", "src/lexer.ep", "src/parser.ep", "src/codegen.ep")


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compile_self(compiler: Path) -> None:
    run([str(compiler), *SOURCES])
    if not SELF_OUTPUT.is_file():
        raise RuntimeError(f"compiler did not produce {SELF_OUTPUT}")


def main() -> int:
    run([sys.executable, "build_epic_v1.py"])
    FIXED_POINT.mkdir(parents=True, exist_ok=True)

    compile_self(SEED)
    generation_1 = FIXED_POINT / "generation-1.exe"
    shutil.copy2(SELF_OUTPUT, generation_1)

    compile_self(generation_1)
    generation_2 = FIXED_POINT / "generation-2.exe"
    shutil.copy2(SELF_OUTPUT, generation_2)

    hash_1 = digest(generation_1)
    hash_2 = digest(generation_2)
    print(f"generation 1: {generation_1.stat().st_size} bytes {hash_1}")
    print(f"generation 2: {generation_2.stat().st_size} bytes {hash_2}")
    if generation_1.read_bytes() != generation_2.read_bytes():
        raise RuntimeError("Epic v1 did not reach a byte-identical fixed point")
    print("fixed point: byte-identical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
