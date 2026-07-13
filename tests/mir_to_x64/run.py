#!/usr/bin/env python3
"""Targeted MIR-to-X64 lowering contract tests."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from compiler_runner import compile_tool


def main():
    sources = [ROOT / "src" / name for name in ("util.ep", "mir.ep", "x64.ep", "mir_to_x64.ep")]
    fixtures = [
        ("layout_fixture.ep", "mir_to_x64_layout.exe", "dynamic struct GEP stride"),
        ("immediate_fixture.ep", "mir_to_x64_immediate.exe", "immediate-aware lowering"),
        ("direct_alloca_fixture.ep", "mir_to_x64_direct_alloca.exe", "direct alloca memory lowering"),
        ("rax_residency_fixture.ep", "mir_to_x64_rax_residency.exe", "single-use rax result residency"),
        ("branch_fusion_fixture.ep", "mir_to_x64_branch_fusion.exe", "terminal compare branch fusion"),
        ("function_address_fixture.ep", "mir_to_x64_function_address.exe", "function address and callback ABI lowering"),
    ]
    for fixture_name, exe_name, label in fixtures:
        fixture = ROOT / "tests" / "mir_to_x64" / fixture_name
        fixture_sources = [*sources]
        if fixture_name == "function_address_fixture.ep":
            fixture_sources.append(ROOT / "src" / "machine.ep")
        tool = compile_tool(fixture, [*fixture_sources, fixture], ROOT / "build" / "tests" / exe_name)
        result = subprocess.run([str(tool)], cwd=ROOT, capture_output=True)
        if result.returncode != 0:
            print((result.stdout + result.stderr).decode("utf-8", errors="replace")[-2000:])
            return 1
        print(f"  PASS  {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
