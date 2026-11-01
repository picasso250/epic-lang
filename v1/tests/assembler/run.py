#!/usr/bin/env python3
"""Check RIP-relative memory-immediate relocation addends."""

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPILER = Path(os.environ["EPIC_TEST_COMPILER"])
SOURCE = ROOT / "tests" / "assembler" / "reloc.ep"


def main() -> int:
    executable = ROOT / "build" / "epic" / "tests_assembler_reloc.ep.exe"
    executable.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            str(COMPILER),
            "-o",
            str(executable),
            str(SOURCE.relative_to(ROOT)),
            "src/asm.ep",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        print(f"  FAIL  compile:\n{(result.stdout + result.stderr)[-1000:]}")
        return 1
    run = subprocess.run([str(executable)], cwd=ROOT, timeout=5)
    if run.returncode != 0:
        print(f"  FAIL  relocation addends, exit {run.returncode}")
        return 1
    print("  PASS  RIP-relative memory-immediate addends")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
