#!/usr/bin/env python3
"""Build the Epic v1 compiler with the Python v0 stage-0 compiler."""

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


ROOT = Path(__file__).resolve().parent
SRC_DIR = ROOT / "src"
BUILD_DIR = ROOT / "build"
BOOTSTRAP_DIR = BUILD_DIR / "v1-bootstrap"
DEFAULT_OUTPUT = BUILD_DIR / "epic-v1.exe"
SOURCE_NAMES = ("epic.ep", "lexer.ep", "parser.ep", "codegen.ep", "asm.ep", "pe.ep")


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


def v0_seed_commit() -> str:
    """Return the current local v0 stage-0 commit."""
    return git_output("rev-parse", "refs/heads/v0")


def temporary_worktree_path() -> Path:
    temp_root = Path(tempfile.gettempdir()).resolve()
    return temp_root / f"epic-v0-{os.getpid()}-{uuid.uuid4().hex}"


def remove_worktree(path: Path) -> None:
    temp_root = Path(tempfile.gettempdir()).resolve()
    resolved = path.resolve()
    if resolved.parent != temp_root or not resolved.name.startswith("epic-v0-"):
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
    parser = argparse.ArgumentParser(description="Build the Epic v1 compiler")
    parser.add_argument("-o", "--output", type=Path, help="output executable path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output.resolve() if args.output else DEFAULT_OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)

    sources = [SRC_DIR / name for name in SOURCE_NAMES]
    missing = [str(path) for path in sources if not path.is_file()]
    if missing:
        raise RuntimeError(f"missing v1 sources: {', '.join(missing)}")

    nasm = ROOT / "tools" / "nasm.exe"
    if not nasm.is_file():
        raise RuntimeError(f"missing NASM trusted tool: {nasm}")

    seed = v0_seed_commit()
    worktree = temporary_worktree_path()
    start = time.perf_counter()
    try:
        print(f"v0 seed: {seed}", flush=True)
        run(["git", "worktree", "add", "--detach", str(worktree), seed])
        worktree_tools = worktree / "tools"
        worktree_tools.mkdir()
        shutil.copy2(nasm, worktree_tools / "nasm.exe")

        BOOTSTRAP_DIR.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable,
            str(worktree / "epic.py"),
            "--main",
            str(SRC_DIR / "epic.ep"),
            "--linker",
            "py",
            "--out-dir",
            str(BOOTSTRAP_DIR),
            *(str(path) for path in sources),
        ]
        run(command)
        built = BOOTSTRAP_DIR / "epic.exe"
        if not built.is_file():
            raise RuntimeError(f"v0 did not produce the expected compiler: {built}")
        shutil.copy2(built, output)
    finally:
        remove_worktree(worktree)

    elapsed = time.perf_counter() - start
    print(f"built: {output}")
    print(f"size: {output.stat().st_size} bytes")
    print(f"sha256: {sha256(output)}")
    print(f"elapsed: {elapsed:.3f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
