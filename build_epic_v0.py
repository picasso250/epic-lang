#!/usr/bin/env python3
"""Reproduce the frozen Epic v0 compiler from a clean detached worktree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = Path("build/bootstrap-v0")
DEFAULT_EXPECTED = Path("bootstrap/v0/epic-v0.sha256")


def run(command: list[str], *, cwd: Path, capture: bool = False) -> subprocess.CompletedProcess[str]:
    print("+ " + subprocess.list2cmdline(command), flush=True)
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=capture,
    )
    if completed.returncode != 0:
        details = ""
        if capture:
            details = "\n--- stdout ---\n" + completed.stdout + "\n--- stderr ---\n" + completed.stderr
        raise RuntimeError(
            f"command failed with exit {completed.returncode}: "
            + subprocess.list2cmdline(command)
            + details
        )
    return completed


def git(*args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd=ROOT, capture=capture)


def resolve_commit(reference: str) -> str:
    result = git("rev-parse", "--verify", f"{reference}^{{commit}}", capture=True)
    return result.stdout.strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_expected_hash(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        value = line.split()[0].lower()
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise RuntimeError(f"invalid SHA-256 in {path}: {value!r}")
        return value
    raise RuntimeError(f"no SHA-256 found in {path}")


def write_text_atomic(path: Path, text: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def remove_worktree_with_retry(worktree: Path, attempts: int = 5) -> RuntimeError | None:
    last_result: subprocess.CompletedProcess[str] | None = None
    for attempt in range(attempts):
        last_result = subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree)],
            cwd=ROOT,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )
        if last_result.returncode == 0:
            return None
        if attempt + 1 < attempts:
            time.sleep(1)
    assert last_result is not None
    return RuntimeError(
        f"failed to remove temporary worktree {worktree}:\n"
        + last_result.stdout
        + last_result.stderr
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref", default="v0", help="Git revision to reproduce (default: v0)")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT),
        help="artifact directory relative to this checkout",
    )
    parser.add_argument(
        "--expected",
        default=str(DEFAULT_EXPECTED),
        help="expected SHA-256 file relative to the target revision",
    )
    parser.add_argument(
        "--require-expected",
        action="store_true",
        help="fail if the target revision has no expected SHA-256 file",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    commit = resolve_commit(args.ref)
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    final_exe = output_dir / "epic-v0.exe"
    staged_exe = output_dir / "epic-v0.exe.staged"
    staged_exe.unlink(missing_ok=True)

    temporary_root = Path(tempfile.mkdtemp(prefix="epic-v0-worktree-"))
    worktree = temporary_root / "source"
    worktree_added = False
    build_error: BaseException | None = None

    print(f"reproducing {args.ref} at {commit}", flush=True)
    try:
        git("worktree", "add", "--detach", str(worktree), commit)
        worktree_added = True

        fixed_point_script = worktree / "test_bootstrap_fixed_point.py"
        if not fixed_point_script.is_file():
            raise RuntimeError(f"target revision lacks {fixed_point_script.name}")

        run(
            [sys.executable, str(fixed_point_script), "-o", str(staged_exe)],
            cwd=worktree,
        )
        if not staged_exe.is_file():
            raise RuntimeError(f"fixed-point build did not export {staged_exe}")

        actual_hash = sha256_file(staged_exe)
        expected_path = worktree / args.expected
        if expected_path.is_file():
            expected_hash = read_expected_hash(expected_path)
            if actual_hash != expected_hash:
                raise RuntimeError(
                    "Epic v0 SHA-256 mismatch:\n"
                    f"  expected: {expected_hash}\n"
                    f"  actual:   {actual_hash}"
                )
            print(f"SHA-256 verified: {actual_hash}", flush=True)
        elif args.require_expected:
            raise RuntimeError(f"expected SHA-256 file is missing: {expected_path}")
        else:
            print(f"SHA-256: {actual_hash} (no committed expectation in target revision)", flush=True)

        os.replace(staged_exe, final_exe)
        write_text_atomic(output_dir / "epic-v0.exe.sha256", f"{actual_hash}  epic-v0.exe\n")
        manifest = {
            "artifact": "epic-v0.exe",
            "fixed_point": True,
            "linker": "py",
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "requested_ref": args.ref,
            "sha256": actual_hash,
            "size": final_exe.stat().st_size,
            "source_revision": commit,
        }
        write_text_atomic(
            output_dir / "manifest.json",
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        )
        print(f"wrote {final_exe}", flush=True)
        print(f"wrote {output_dir / 'epic-v0.exe.sha256'}", flush=True)
        print(f"wrote {output_dir / 'manifest.json'}", flush=True)
        return 0
    except BaseException as exc:
        build_error = exc
        raise
    finally:
        staged_exe.unlink(missing_ok=True)
        cleanup_error: RuntimeError | None = None
        if worktree_added:
            cleanup_error = remove_worktree_with_retry(worktree)
        shutil.rmtree(temporary_root, ignore_errors=True)
        if cleanup_error is not None:
            if build_error is None:
                raise cleanup_error
            print(f"warning: {cleanup_error}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())