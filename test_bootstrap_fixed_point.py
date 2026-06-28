#!/usr/bin/env python3
"""
Check that the compiler reaches a bootstrap fixed point.

Stages:
  v00: Python compiler builds the Epic compiler.
  v0:  v00 builds the Epic compiler.
  v0_: v0 builds the Epic compiler again.

The later stages should be byte-identical. If they are not, self-hosting is not
yet a stable bootstrap anchor.
"""

import filecmp
import os
import shutil
import subprocess
import sys


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EPICC = os.path.join(SCRIPT_DIR, "epic.py")
BUILD_DIR = os.path.join(SCRIPT_DIR, "build")
BOOT_DIR = os.path.join(BUILD_DIR, "fixed-point")
SELF_OUT = os.path.join(BUILD_DIR, "epic", "epic.ep.exe")
SOURCES = ["epic.ep", "codegen.ep", "parser.ep", "lexer.ep"]
TIMEOUT_SECONDS = int(os.environ.get("BOOTSTRAP_TIMEOUT", "3"))


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

    v00 = os.path.join(BOOT_DIR, "v00.exe")
    v0 = os.path.join(BOOT_DIR, "v0.exe")
    v0_next = os.path.join(BOOT_DIR, "v0_.exe")
    v0_next2 = os.path.join(BOOT_DIR, "v0__.exe")

    run_checked(
        [
            sys.executable,
            EPICC,
            "--main",
            "epic.ep",
            *SOURCES,
            "--out-dir",
            BOOT_DIR,
        ],
        "python -> v00",
    )
    shutil.copyfile(os.path.join(BOOT_DIR, "epic.exe"), v00)

    run_checked([v00, *SOURCES], "v00 -> v0")
    copy_self_out("v0.exe")

    run_checked([v0, *SOURCES], "v0 -> v0_")
    copy_self_out("v0_.exe")

    run_checked([v0_next, *SOURCES], "v0_ -> v0__")
    copy_self_out("v0__.exe")

    checks = [(v0, v0_next), (v0_next, v0_next2)]
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
