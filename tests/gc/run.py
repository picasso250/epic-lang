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


SOURCE = ROOT / "tests" / "gc" / "stress.ep"
PEAK_LIMIT_MIB = 128


def main() -> int:
    relative = SOURCE.relative_to(ROOT)
    compile_result = subprocess.run(
        [str(ep_runner.compiler_path()), str(relative)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if compile_result.returncode != 0:
        detail = (compile_result.stdout + compile_result.stderr)[-1000:]
        print(f"  FAIL  compile:\n{detail}")
        return 1

    executable = ep_runner.output_path(SOURCE)
    try:
        metrics = run_measured([str(executable)], cwd=ROOT)
    except subprocess.CalledProcessError as error:
        print(f"  FAIL  stress program exited with {error.returncode}")
        return 1

    peak_mib = metrics.peak_working_set_bytes / (1024 * 1024)
    if peak_mib > PEAK_LIMIT_MIB:
        print(
            f"  FAIL  peak memory {format_peak_working_set(metrics.peak_working_set_bytes)} "
            f"> {PEAK_LIMIT_MIB} MiB"
        )
        return 1

    print(
        "  PASS  retained stack/heap graph survived; "
        f"peak memory {format_peak_working_set(metrics.peak_working_set_bytes)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
