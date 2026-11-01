#!/usr/bin/env python3
"""Verify GC retention and bounded memory under allocation pressure."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import ep_runner
from process_metrics import format_peak_working_set, run_measured


PEAK_LIMIT_MIB = 128


def run_case(name: str) -> bool:
    source = ROOT / "tests" / "gc" / f"{name}.ep"
    relative = source.relative_to(ROOT)
    executable = ep_runner.output_path(source)
    executable.parent.mkdir(parents=True, exist_ok=True)
    compile_result = subprocess.run(
        [str(ep_runner.compiler_path()), "-o", str(executable), str(relative)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if compile_result.returncode != 0:
        detail = (compile_result.stdout + compile_result.stderr)[-1000:]
        print(f"  FAIL  compile:\n{detail}")
        return False

    try:
        metrics = run_measured([str(executable)], cwd=ROOT)
    except subprocess.CalledProcessError as error:
        print(f"  FAIL  GC {name} exited with {error.returncode}")
        return False

    peak_mib = metrics.peak_working_set_bytes / (1024 * 1024)
    if peak_mib > PEAK_LIMIT_MIB:
        print(
            f"  FAIL  peak memory {format_peak_working_set(metrics.peak_working_set_bytes)} "
            f"> {PEAK_LIMIT_MIB} MiB"
        )
        return False

    print(
        f"  PASS  GC {name}; "
        f"peak memory {format_peak_working_set(metrics.peak_working_set_bytes)}"
    )
    return True


def main() -> int:
    ok = run_case("stress")
    ok = run_case("small") and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
