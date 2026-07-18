#!/usr/bin/env python3
"""Check RIP-relative memory-immediate relocation addends."""

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPILER = Path(os.environ["EPIC_TEST_COMPILER"])
CASES = [
    ("reloc.ep", "RIP-relative memory-immediate addends"),
    ("structured.ep", "structured IR render/parse/encode intent"),
]


def main() -> int:
    for filename, label in CASES:
        source = ROOT / "tests" / "assembler" / filename
        result = subprocess.run(
            [str(COMPILER), str(source.relative_to(ROOT)), "src/utils.ep", "src/asm.ep"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(f"  FAIL  {label} compile:\n{(result.stdout + result.stderr)[-1000:]}")
            return 1
        stem = filename.removesuffix(".ep")
        executable = ROOT / "build" / "epic" / f"tests_assembler_{stem}.ep.exe"
        run = subprocess.run([str(executable)], cwd=ROOT, timeout=5)
        if run.returncode != 0:
            print(f"  FAIL  {label}, exit {run.returncode}")
            return 1
        print(f"  PASS  {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
