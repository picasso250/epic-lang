#!/usr/bin/env python3
"""Build or display the bootstrap profile for one committed dev revision."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROFILE_DIR = ROOT / "build" / "profile"
V0_SEED_DIR = ROOT / "build" / "bootstrap-v0"


def git_revision(ref: str) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"failed to resolve Git revision {ref}\n" + completed.stderr[-4000:])
    return completed.stdout.strip()


def run_checked(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed with exit {completed.returncode}: {subprocess.list2cmdline(command)}\n"
            + completed.stdout[-4000:]
            + completed.stderr[-4000:]
        )
    return completed


def resolve_v0_seed(revision: str) -> Path:
    seed = V0_SEED_DIR / f"epic-v0-{revision}.exe"
    if seed.is_file():
        return seed
    run_checked(
        [sys.executable, str(ROOT / "build_epic_v0.py"), "--ref", revision],
        ROOT,
    )
    if not seed.is_file():
        raise RuntimeError(f"v0 build did not produce seed compiler: {seed}")
    return seed


def remove_worktree(path: Path) -> None:
    completed = subprocess.run(
        ["git", "worktree", "remove", "--force", str(path)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"failed to remove temporary worktree {path}\n" + completed.stderr[-4000:])


def build_profile(dev_revision: str, seed: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="epic-profile-", ignore_cleanup_errors=True) as temp_dir:
        worktree = Path(temp_dir) / "source"
        run_checked(
            ["git", "worktree", "add", "--detach", str(worktree), dev_revision],
            ROOT,
        )
        try:
            fixed_point = worktree / "bootstrap_fixed_point.py"
            if not fixed_point.is_file():
                raise RuntimeError(f"revision {dev_revision} has no bootstrap_fixed_point.py")
            completed = run_checked(
                [sys.executable, str(fixed_point), "--seed", str(seed)],
                worktree,
            )
            return completed.stdout
        finally:
            remove_worktree(worktree)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("revision", help="committed dev revision to profile")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dev_revision = git_revision(args.revision)
    v0_revision = git_revision("v0")
    profile = PROFILE_DIR / f"dev-{dev_revision}-v0-{v0_revision}.txt"

    if not profile.is_file():
        seed = resolve_v0_seed(v0_revision)
        output = build_profile(dev_revision, seed)
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        staged = profile.with_suffix(".txt.staged")
        staged.write_text(output, encoding="utf-8")
        staged.replace(profile)

    print(profile.read_text(encoding="utf-8"), end="")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
