"""Shared helpers for testing the current self-hosted Epic compiler."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPILER = ROOT / "build" / "test-compiler" / "epic.exe"


def compiler_path() -> Path:
    configured = os.environ.get("EPIC_TEST_COMPILER")
    compiler = Path(configured).resolve() if configured else DEFAULT_COMPILER
    if compiler.is_file():
        return compiler
    compiler.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(ROOT / "test_bootstrap_fixed_point.py"), "-o", str(compiler)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0 or not compiler.is_file():
        raise RuntimeError("failed to build current self-hosted test compiler")
    return compiler


def relative(path: str | Path) -> str:
    return os.path.relpath(Path(path).resolve(), ROOT).replace(os.sep, "/")


def compile_tool(main: str | Path, sources: list[str | Path], output: str | Path, timeout=60):
    compiler = compiler_path()
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [str(compiler)]
    command.extend(relative(path) for path in sources)
    command.extend(["--main", relative(main), "-o", relative(output)])
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stdout + result.stderr)[-4000:])
    if not output.is_file():
        raise RuntimeError(f"compiler did not produce {output}")
    return output


def compile_program(source: str | Path, output: str | Path, timeout=30):
    return compile_tool(source, [source], output, timeout=timeout)

