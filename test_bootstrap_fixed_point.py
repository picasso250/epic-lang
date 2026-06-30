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


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EPICC = os.path.join(SCRIPT_DIR, "bootstrap", "epic.py")
BUILD_DIR = os.path.join(SCRIPT_DIR, "build")
BOOT_DIR = os.path.join(BUILD_DIR, "fixed-point")
SELF_OUT = os.path.join(BUILD_DIR, "epic", "src_epic.ep.exe")
SOURCES = [
    os.path.join("src", "epic.ep"),
    os.path.join("src", "codegen_support.ep"),
    os.path.join("src", "codegen.ep"),
    os.path.join("src", "parser.ep"),
    os.path.join("src", "lexer.ep"),
]
TIMEOUT_SECONDS = int(os.environ.get("BOOTSTRAP_TIMEOUT", "60"))


def run_checked(cmd, label):
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
            + result.stdout[-4000:]
            + result.stderr[-4000:]
        )
    return result


def copy_self_out(name):
    dst = os.path.join(BOOT_DIR, name)
    if not os.path.exists(SELF_OUT):
        raise RuntimeError(f"expected compiler output missing: {SELF_OUT}")
    shutil.copyfile(SELF_OUT, dst)
    return dst


def main():
    os.makedirs(BOOT_DIR, exist_ok=True)
    os.makedirs(os.path.join(BUILD_DIR, "epic"), exist_ok=True)

    epic_py = os.path.join(BOOT_DIR, "epic-py.exe")
    epic_epic = os.path.join(BOOT_DIR, "epic-epic.exe")
    epic_epic_epic = os.path.join(BOOT_DIR, "epic-epic-epic.exe")
    epic_epic_epic_epic = os.path.join(BOOT_DIR, "epic-epic-epic-epic.exe")

    run_checked(
        [
            sys.executable,
            EPICC,
            "--main",
            os.path.join("src", "epic.ep"),
            *SOURCES,
            "--out-dir",
            BOOT_DIR,
        ],
        "python -> epic-py",
    )
    shutil.copyfile(os.path.join(BOOT_DIR, "src", "epic.exe"), epic_py)

    run_checked([epic_py, *SOURCES], "epic-py -> epic-epic")
    copy_self_out("epic-epic.exe")

    run_checked([epic_epic, *SOURCES], "epic-epic -> epic-epic-epic")
    copy_self_out("epic-epic-epic.exe")

    run_checked([epic_epic_epic, *SOURCES], "epic-epic-epic -> epic-epic-epic-epic")
    copy_self_out("epic-epic-epic-epic.exe")

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
