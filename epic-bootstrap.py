#!/usr/bin/env python3
"""Build the cross-version Epic compiler anchors from the repository root."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
TOOLS = ROOT / "tools"
V0 = ROOT / "v0"
V1 = ROOT / "v1"
V0_FIXED = V0 / "build" / "fixed-point" / "epic-epic-epic.exe"
ROOT_V0 = BUILD / "v0.exe"
ROOT_V1 = BUILD / "v1.exe"
V1_OUT = V1 / "build" / "epic" / "epic.ep.exe"
V1_SOURCES = ["epic.ep", "codegen_support.ep", "codegen.ep", "parser.ep", "lexer.ep"]


def run_checked(cmd: list[str], cwd: Path, label: str) -> None:
    print(f"==> {label}", flush=True)
    result = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed with exit {result.returncode}")


def sync_tools(version_dir: Path) -> None:
    if not TOOLS.exists():
        return
    dst = version_dir / "tools"
    dst.mkdir(exist_ok=True)
    for name in ("nasm.exe", "lld-link.exe"):
        src = TOOLS / name
        if src.exists():
            shutil.copy2(src, dst / name)


def main() -> int:
    BUILD.mkdir(exist_ok=True)
    sync_tools(V0)
    sync_tools(V1)

    run_checked([sys.executable, "test_bootstrap_fixed_point.py"], V0, "v0 fixed point")
    if not V0_FIXED.exists():
        raise RuntimeError(f"expected v0 fixed-point compiler missing: {V0_FIXED}")
    shutil.copy2(V0_FIXED, ROOT_V0)
    print(f"copied {ROOT_V0}", flush=True)

    run_checked([str(ROOT_V0), *V1_SOURCES], V1, "v0 -> v1")
    if not V1_OUT.exists():
        raise RuntimeError(f"expected v1 compiler missing: {V1_OUT}")
    shutil.copy2(V1_OUT, ROOT_V1)
    print(f"copied {ROOT_V1}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
