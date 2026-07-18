#!/usr/bin/env python3
"""Build Epic v3 from v2, then verify two self-hosted generations match."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys

from process_metrics import ProcessMetrics, format_peak_working_set, run_measured


ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
FIXED_POINT = BUILD / "fixed-point"
SEED = BUILD / "epic-v3.exe"
SOURCES = tuple(
    path.relative_to(ROOT).as_posix()
    for path in sorted(
        (ROOT / "src").glob("*.ep"),
        key=lambda path: (path.name != "epic.ep", path.name),
    )
)


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compile_self(compiler: Path, output: Path) -> ProcessMetrics:
    if output.exists():
        output.unlink()
    output_arg = output.relative_to(ROOT)
    metrics = run_measured([str(compiler), "-o", str(output_arg), *SOURCES], cwd=ROOT)
    if not output.is_file():
        raise RuntimeError(f"compiler did not produce {output}")
    return metrics


def main() -> int:
    run([sys.executable, "build_epic.py"])
    FIXED_POINT.mkdir(parents=True, exist_ok=True)

    generation_1 = FIXED_POINT / "generation-1.exe"
    metrics_1 = compile_self(SEED, generation_1)

    generation_2 = FIXED_POINT / "generation-2.exe"
    metrics_2 = compile_self(generation_1, generation_2)

    hash_1 = digest(generation_1)
    hash_2 = digest(generation_2)
    print(
        f"generation 1: {generation_1.stat().st_size} bytes {hash_1} "
        f"{metrics_1.elapsed_seconds:.3f} s, "
        f"peak memory: {format_peak_working_set(metrics_1.peak_working_set_bytes)}"
    )
    print(
        f"generation 2: {generation_2.stat().st_size} bytes {hash_2} "
        f"{metrics_2.elapsed_seconds:.3f} s, "
        f"peak memory: {format_peak_working_set(metrics_2.peak_working_set_bytes)}"
    )
    if generation_1.read_bytes() != generation_2.read_bytes():
        raise RuntimeError("Epic v3 did not reach a byte-identical fixed point")
    print("fixed point: byte-identical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
