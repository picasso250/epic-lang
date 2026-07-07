#!/usr/bin/env python3
"""
Check that the compiler reaches a bootstrap fixed point.

Stages:
  epic-py: Python compiler builds the Epic compiler.
  epic-epic: epic-py builds the Epic compiler.
  epic-epic-epic: epic-epic builds the Epic compiler again.

The later stages should be byte-identical. If they are not, self-hosting is not
yet a stable bootstrap anchor.
"""

import filecmp
import os
import shutil
import subprocess
import sys
import time


def rel(path):
    return os.path.relpath(path, SCRIPT_DIR).replace(os.sep, "/")


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EPICC = os.path.join(SCRIPT_DIR, "bootstrap", "epic.py")
BUILD_DIR = os.path.join(SCRIPT_DIR, "build")
BOOT_DIR = os.path.join(BUILD_DIR, "fixed-point")
RUNTIME_SOURCES = [
    os.path.join("runtime", "str.ep"),
]
COMPILER_SOURCES = [
    os.path.join("src", "util.ep"),
    os.path.join("src", "lexer.ep"),
    os.path.join("src", "parser.ep"),
    os.path.join("src", "sema.ep"),
    os.path.join("src", "mir.ep"),
    os.path.join("src", "mir_runtime.ep"),
    os.path.join("src", "ast_to_mir.ep"),
    os.path.join("src", "x64.ep"),
    os.path.join("src", "mir_to_x64.ep"),
    os.path.join("src", "x64_runtime.ep"),
    os.path.join("src", "machine.ep"),
    os.path.join("src", "coff.ep"),
    os.path.join("src", "link.ep"),
    os.path.join("src", "epic.ep"),
]
TIMEOUT_SECONDS = int(os.environ.get("BOOTSTRAP_TIMEOUT", "240"))


def run_checked(cmd, label):
    start = time.perf_counter()
    try:
        result = subprocess.run(
            cmd,
            cwd=SCRIPT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"{label} timed out after {TIMEOUT_SECONDS}s\n"
            + (e.stdout or "")[-4000:]
            + (e.stderr or "")[-4000:]
        ) from e
    if result.returncode != 0:
        raise RuntimeError(
            f"{label} failed with exit {result.returncode}\n"
            + "cmd: " + " ".join(cmd) + "\n"
            + f"stdout bytes: {len(result.stdout)} stderr bytes: {len(result.stderr)}\n"
            + "--- stdout tail ---\n"
            + result.stdout[-8000:]
            + "\n--- stderr tail ---\n"
            + result.stderr[-8000:]
        )
    elapsed = time.perf_counter() - start
    for line in result.stdout.splitlines():
        if line.startswith("  timing: "):
            print(f"  {label} {line.strip()}", flush=True)
    print(f"{label}: {elapsed:.2f}s", flush=True)
    return result


def build_with_python(output_path):
    stage0_dir = os.path.join(BOOT_DIR, "stage0")
    run_checked(
        [
            sys.executable,
            EPICC,
            "--main",
            os.path.join("src", "epic.ep"),
            *COMPILER_SOURCES,
            "--out-dir",
            stage0_dir,
            "--linker",
            "py",
        ],
        "python -> epic-py",
    )
    produced = os.path.join(stage0_dir, "src", "epic.exe")
    if not os.path.exists(produced):
        raise RuntimeError(f"expected compiler output missing: {produced}")
    shutil.copyfile(produced, output_path)


def build_with_epic(compiler, output_path, label):
    run_checked(
        [
            compiler,
            *RUNTIME_SOURCES,
            *COMPILER_SOURCES,
            "--main",
            os.path.join("src", "epic.ep"),
            "-o",
            rel(output_path),
        ],
        label,
    )
    if not os.path.exists(output_path):
        raise RuntimeError(f"expected compiler output missing: {output_path}")


def main():
    if os.path.exists(BOOT_DIR):
        shutil.rmtree(BOOT_DIR)
    os.makedirs(BOOT_DIR, exist_ok=True)

    epic_py = os.path.join(BOOT_DIR, "epic-py.exe")
    epic_epic = os.path.join(BOOT_DIR, "epic-epic.exe")
    epic_epic_epic = os.path.join(BOOT_DIR, "epic-epic-epic.exe")
    epic_epic_epic_epic = os.path.join(BOOT_DIR, "epic-epic-epic-epic.exe")

    build_with_python(epic_py)
    build_with_epic(epic_py, epic_epic, "epic-py -> epic-epic")
    build_with_epic(epic_epic, epic_epic_epic, "epic-epic -> epic-epic-epic")
    build_with_epic(epic_epic_epic, epic_epic_epic_epic, "epic-epic-epic -> epic-epic-epic-epic")

    checks = [(epic_epic, epic_epic_epic), (epic_epic_epic, epic_epic_epic_epic)]
    for left, right in checks:
        if not filecmp.cmp(left, right, shallow=False):
            raise RuntimeError(
                "bootstrap output is not byte-identical: "
                + os.path.basename(left)
                + " != "
                + os.path.basename(right)
            )

    print("bootstrap fixed point reached")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
