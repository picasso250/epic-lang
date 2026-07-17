#!/usr/bin/env python3
"""Shared runner for annotated Epic programs."""

import os
import re
import shlex
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXEC_TIMEOUT = 1


def compiler_path() -> Path:
    configured = os.environ.get("EPIC_TEST_COMPILER")
    if not configured:
        raise RuntimeError("EPIC_TEST_COMPILER is not set")
    compiler = Path(configured).resolve()
    if not compiler.is_file():
        raise RuntimeError(f"test compiler does not exist: {compiler}")
    return compiler


def parse_annotations(source: str) -> dict:
    annotations = {
        "exit_code": None,
        "stdout": None,
        "argv": [],
        "clean_paths": [],
    }
    stdout_lines = []
    for line in source.splitlines():
        line = line.strip()
        if match := re.match(r"#\s*EXIT:\s*(-?\d+)", line):
            annotations["exit_code"] = int(match.group(1))
        elif match := re.match(r"#\s*STDOUT:\s*(.*)", line):
            stdout_lines.append(match.group(1))
        elif match := re.match(r"#\s*ARGV:\s*(.*)$", line):
            annotations["argv"] = shlex.split(match.group(1) or "")
        elif match := re.match(r"#\s*CLEAN:\s*(.+)$", line):
            annotations["clean_paths"].extend(shlex.split(match.group(1)))
    annotations["stdout"] = "\n".join(stdout_lines) if stdout_lines else None
    return annotations


def clean_test_paths(paths: list[str]) -> None:
    root = ROOT.resolve()
    for relative in paths:
        if os.path.isabs(relative):
            raise RuntimeError(f"# CLEAN path must be relative: {relative}")
        path = (root / relative).resolve()
        if root not in path.parents:
            raise RuntimeError(f"# CLEAN path escapes repo root: {relative}")
        if path.is_dir():
            raise RuntimeError(f"# CLEAN refuses to delete directory: {relative}")
        if path.exists():
            path.unlink()


def output_path(source: Path) -> Path:
    relative = source.resolve().relative_to(ROOT).as_posix()
    safe = relative.replace("/", "_")
    return ROOT / "build" / "epic" / f"{safe}.exe"


def run_case(source: Path) -> tuple[bool, str]:
    annotations = parse_annotations(source.read_text(encoding="utf-8"))
    if annotations["exit_code"] is None and annotations["stdout"] is None:
        return True, "no annotations — skipped"

    clean_test_paths(annotations["clean_paths"])
    relative = source.resolve().relative_to(ROOT)
    result = subprocess.run(
        [str(compiler_path()), str(relative)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=30,
    )
    if result.returncode != 0:
        return False, f"compile failed:\n{result.stderr[:500]}"

    executable = output_path(source)
    if not executable.is_file():
        return False, f"no exe produced: {executable}"
    process = subprocess.run(
        [str(executable), *annotations["argv"]],
        capture_output=True,
        cwd=ROOT,
        timeout=EXEC_TIMEOUT,
    )

    failures = []
    expected_exit = annotations["exit_code"]
    if expected_exit is not None and process.returncode != expected_exit:
        failures.append(f"EXIT: expected {expected_exit}, got {process.returncode}")
    expected_stdout = annotations["stdout"]
    if expected_stdout is not None:
        actual = (process.stdout or b"").decode("ascii", errors="replace").strip()
        if actual != expected_stdout.strip():
            failures.append(f"STDOUT: expected {expected_stdout!r}, got {actual!r}")

    clean_test_paths(annotations["clean_paths"])
    return (False, "; ".join(failures)) if failures else (True, "OK")
