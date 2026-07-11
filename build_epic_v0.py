#!/usr/bin/env python3
"""Reproduce a converged Epic compiler from a clean detached worktree."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "build" / "bootstrap-v0"
EXPECTED_HASH = Path("bootstrap/v0/epic-v0.sha256")


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


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_expected_hash(worktree: Path) -> str | None:
    path = worktree / EXPECTED_HASH
    if not path.is_file():
        return None
    fields = path.read_text(encoding="ascii").split()
    digest = fields[0].lower() if fields else ""
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise RuntimeError(f"invalid SHA-256 in {path}: {digest!r}")
    return digest


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


def reproduce(ref: str, output_dir: Path, require_expected: bool) -> None:
    revision = git_revision(ref)
    output_dir = output_dir if output_dir.is_absolute() else ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    staged = output_dir / "epic-v0.exe.staged"
    final = output_dir / "epic-v0.exe"
    staged.unlink(missing_ok=True)

    print(f"reproducing {ref} at {revision}", flush=True)
    with tempfile.TemporaryDirectory(
        prefix="epic-v0-worktree-", ignore_cleanup_errors=True
    ) as temp_dir:
        worktree = Path(temp_dir) / "source"
        run("git", "worktree", "add", "--detach", str(worktree), revision)
        try:
            fixed_point = worktree / "test_bootstrap_fixed_point.py"
            if not fixed_point.is_file():
                raise RuntimeError(f"target revision has no {fixed_point.name}: {revision}")
            run(sys.executable, str(fixed_point), "-o", str(staged), cwd=worktree)
            digest = file_hash(staged)
            expected = read_expected_hash(worktree)
        finally:
            remove_worktree(worktree)

    if expected is None:
        if require_expected:
            raise RuntimeError(f"target revision {revision} has no {EXPECTED_HASH}")
        print(f"SHA-256: {digest} (no committed expectation)", flush=True)
    elif digest != expected:
        raise RuntimeError(f"SHA-256 mismatch: expected {expected}, got {digest}")
    else:
        print(f"SHA-256 verified: {digest}", flush=True)

    staged.replace(final)
    (output_dir / "epic-v0.exe.sha256").write_text(
        f"{digest}  epic-v0.exe\n", encoding="ascii", newline="\n"
    )
    manifest = {
        "artifact": final.name,
        "fixed_point": True,
        "linker": "py",
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "requested_ref": ref,
        "sha256": digest,
        "size": final.stat().st_size,
        "source_revision": revision,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {final}", flush=True)
    print(f"wrote {output_dir / 'epic-v0.exe.sha256'}", flush=True)
    print(f"wrote {output_dir / 'manifest.json'}", flush=True)


def parse_args():
    parser = argparse.ArgumentParser(
        description="reproduce a converged Epic compiler from a clean worktree"
    )
    parser.add_argument("--ref", default="v0", help="git revision (default: v0)")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"artifact directory (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--require-expected",
        action="store_true",
        help="fail if the target revision has no committed expected hash",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    reproduce(args.ref, args.output_dir, args.require_expected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
