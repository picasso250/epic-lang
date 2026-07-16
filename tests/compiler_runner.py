"""Shared helpers for testing the current self-hosted Epic compiler."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPILER_SOURCES = sorted((ROOT / "src").glob("*.ep"))
DEFAULT_COMPILER = ROOT / "build" / "test-compiler" / "epic.exe"


def _embedded_runtime_paths() -> list[Path]:
    bundle = ROOT / "src" / "runtime_bundle.ep"
    paths = []
    for match in re.finditer(r'\bembed\s+"([^"]+)"', bundle.read_text(encoding="utf-8")):
        paths.append((bundle.parent / match.group(1)).resolve())
    return paths


def _compiler_fingerprint() -> str:
    digest = hashlib.sha256()
    inputs = [
        ROOT / "bootstrap_fixed_point.py",
        ROOT / "build_epic_v0.py",
        ROOT / "build" / "bootstrap-v0" / "epic-v0.exe",
        *COMPILER_SOURCES,
        *_embedded_runtime_paths(),
    ]
    for path in inputs:
        if not path.is_file():
            raise RuntimeError(f"test compiler input is missing: {path}")
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def compiler_path() -> Path:
    configured = os.environ.get("EPIC_TEST_COMPILER")
    if configured:
        compiler = Path(configured).resolve()
        if not compiler.is_file():
            raise RuntimeError(f"configured test compiler does not exist: {compiler}")
        return compiler

    compiler = DEFAULT_COMPILER
    fingerprint = _compiler_fingerprint()
    stamp = compiler.with_suffix(".inputs.sha256")
    if compiler.is_file() and stamp.is_file() and stamp.read_text(encoding="ascii").strip() == fingerprint:
        return compiler
    compiler.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(ROOT / "bootstrap_fixed_point.py"), "-o", str(compiler)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0 or not compiler.is_file():
        raise RuntimeError("failed to build current self-hosted test compiler")
    stamp.write_text(fingerprint + "\n", encoding="ascii", newline="\n")
    return compiler


def compile_fail_contains(path: str | Path) -> str | None:
    text = Path(path).read_text(encoding="utf-8")
    match = re.search(r"#\s*COMPILE_FAIL_CONTAINS:\s*(.*)$", text, re.MULTILINE)
    return match.group(1).strip() if match else None


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

