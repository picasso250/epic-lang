#!/usr/bin/env python3
"""Build the current v0 compiler from a clean detached worktree."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "build" / "bootstrap-v0"


def run(*args: str, cwd: Path = ROOT, capture: bool = False, check: bool = True):
    print("+", " ".join(args), flush=True)
    return subprocess.run(
        args,
        cwd=cwd,
        check=check,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=capture,
    )


def git_revision(ref: str) -> str:
    return run(
        "git", "rev-parse", "--verify", f"{ref}^{{commit}}", capture=True
    ).stdout.strip()


def remove_worktree(path: Path) -> None:
    for attempt in range(5):
        result = run(
            "git",
            "worktree",
            "remove",
            "--force",
            str(path),
            capture=True,
            check=False,
        )
        if result.returncode == 0:
            return
        if attempt < 4:
            time.sleep(1)
    raise RuntimeError(
        f"failed to remove temporary worktree {path}:\n"
        + result.stdout
        + result.stderr
    )


def build(ref: str, output_dir: Path) -> None:
    revision = git_revision(ref)
    output_dir = output_dir if output_dir.is_absolute() else ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    final = output_dir / f"epic-v0-{revision}.exe"
    staged = output_dir / f"{final.name}.staged"
    staged.unlink(missing_ok=True)

    print(f"reproducing {ref} at {revision}", flush=True)
    with tempfile.TemporaryDirectory(
        prefix="epic-v0-worktree-", ignore_cleanup_errors=True
    ) as temp_dir:
        worktree = Path(temp_dir) / "source"
        run("git", "worktree", "add", "--detach", str(worktree), revision)
        try:
            fixed_point = worktree / "bootstrap_fixed_point.py"
            if not fixed_point.is_file():
                raise RuntimeError(f"target revision has no {fixed_point.name}: {revision}")
            run(sys.executable, str(fixed_point), "-o", str(staged), cwd=worktree)
        finally:
            remove_worktree(worktree)

    staged.replace(final)
    print(f"wrote {final}", flush=True)


def parse_args():
    parser = argparse.ArgumentParser(
        description="build the current v0 compiler from a clean worktree"
    )
    parser.add_argument("--ref", default="v0", help="git revision (default: v0)")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"artifact directory (default: {DEFAULT_OUTPUT})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    build(args.ref, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
