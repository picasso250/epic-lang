#!/usr/bin/env python3
"""Build the Epic v3 compiler with an exact local v2 compiler."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

from process_metrics import format_peak_working_set, run_measured


ROOT = Path(__file__).resolve().parent
BUILD_DIR = ROOT / "build"
DEFAULT_OUTPUT = BUILD_DIR / "epic-v3.exe"
SELF_OUTPUT = BUILD_DIR / "epic" / "src_epic.ep.exe"
SOURCE_PATHS = (
    "src/epic.ep",
    "src/lexer.ep",
    "src/parser.ep",
    "src/sema.ep",
    "src/codegen.ep",
    "src/asm.ep",
    "src/pe.ep",
)


def run(command: list[str], *, cwd: Path = ROOT) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def git_output(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def v2_seed_commit() -> str:
    return git_output("rev-parse", "refs/heads/v2")


def temporary_worktree_path() -> Path:
    temp_root = Path(tempfile.gettempdir()).resolve()
    return temp_root / f"epic-v2-{os.getpid()}-{uuid.uuid4().hex}"


def remove_worktree(path: Path) -> None:
    temp_root = Path(tempfile.gettempdir()).resolve()
    resolved = path.resolve()
    if resolved.parent != temp_root or not resolved.name.startswith("epic-v2-"):
        raise RuntimeError(f"refusing to remove unexpected worktree path: {resolved}")
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(resolved)],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if resolved.exists():
        shutil.rmtree(resolved)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Epic v3 compiler")
    parser.add_argument("-o", "--output", type=Path, help="output executable path")
    return parser.parse_args()


def ensure_v2_seed(seed: str) -> Path:
    artifact = BUILD_DIR / f"epic-v2-{seed}.exe"
    if artifact.is_file():
        print(f"v2 seed: {seed} (cached)", flush=True)
        return artifact

    nasm = ROOT / "tools" / "nasm.exe"
    if not nasm.is_file():
        raise RuntimeError(f"missing NASM trusted tool: {nasm}")

    worktree = temporary_worktree_path()
    try:
        print(f"v2 seed: {seed} (building)", flush=True)
        run(["git", "worktree", "add", "--detach", str(worktree), seed])
        worktree_tools = worktree / "tools"
        worktree_tools.mkdir()
        shutil.copy2(nasm, worktree_tools / "nasm.exe")
        artifact.parent.mkdir(parents=True, exist_ok=True)
        run(
            [sys.executable, str(worktree / "build_epic.py"), "-o", str(artifact)],
            cwd=worktree,
        )
    finally:
        remove_worktree(worktree)

    if not artifact.is_file():
        raise RuntimeError(f"v2 did not produce the expected compiler: {artifact}")
    return artifact


def main() -> int:
    args = parse_args()
    output = args.output.resolve() if args.output else DEFAULT_OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)

    missing = [str(ROOT / path) for path in SOURCE_PATHS if not (ROOT / path).is_file()]
    if missing:
        raise RuntimeError(f"missing v3 sources: {', '.join(missing)}")

    start = time.perf_counter()
    seed = v2_seed_commit()
    compiler = ensure_v2_seed(seed)
    compile_metrics = run_measured([str(compiler), *SOURCE_PATHS], cwd=ROOT)
    if not SELF_OUTPUT.is_file():
        raise RuntimeError(f"v2 did not produce the expected v3 compiler: {SELF_OUTPUT}")
    if SELF_OUTPUT.resolve() != output.resolve():
        shutil.copy2(SELF_OUTPUT, output)

    elapsed = time.perf_counter() - start
    print(f"built: {output}")
    print(f"size: {output.stat().st_size} bytes")
    print(f"sha256: {sha256(output)}")
    print(
        f"compiler: {compile_metrics.elapsed_seconds:.3f} s, "
        f"peak memory: {format_peak_working_set(compile_metrics.peak_working_set_bytes)}"
    )
    print(f"elapsed: {elapsed:.3f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
