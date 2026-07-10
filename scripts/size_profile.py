#!/usr/bin/env python3
"""Report approximate text-size contribution per Epic compiler function.

This is a developer profiling tool. It uses the Python bootstrap compiler to
build MIR/X64/MachineObject for the self-hosted compiler, then attributes text
bytes to function-entry label ranges.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "bootstrap"
sys.path.insert(0, str(BOOTSTRAP))

import epic  # noqa: E402
import machine  # noqa: E402
from machine import MachineObjectBuilder  # noqa: E402
from mir_to_x64 import MirLower, prepare_mir_for_x64  # noqa: E402


RUNTIME_SOURCES = [Path("runtime") / "str.ep"]
COMPILER_SOURCES = [
    Path("src") / "util.ep",
    Path("src") / "lexer.ep",
    Path("src") / "parser.ep",
    Path("src") / "sema.ep",
    Path("src") / "mir.ep",
    Path("src") / "mir_text.ep",
    Path("src") / "mir_runtime.ep",
    Path("src") / "backend_abi.ep",
    Path("src") / "ast_to_mir.ep",
    Path("src") / "x64.ep",
    Path("src") / "mir_to_x64.ep",
    Path("src") / "x64_runtime.ep",
    Path("src") / "machine.ep",
    Path("src") / "coff.ep",
    Path("src") / "link.ep",
    Path("src") / "epic.ep",
]


def rel(path: Path) -> str:
    return str(path).replace(os.sep, "/")


def mir_inst_count(fn) -> int:
    return sum(len(block.instructions) + 1 for block in fn.blocks)


def build_profile_rows():
    sources = [rel(p) for p in RUNTIME_SOURCES + COMPILER_SOURCES]
    main_path = rel(Path("src") / "epic.ep")
    ast = epic._merge_programs(sources, main_path, verbose=False, include_runtime=False)
    ast = epic.analyze_program(ast)
    program = epic.ast_to_mir(ast)
    prepare_mir_for_x64(program)

    lower = MirLower(program)
    lower._prepare_program()
    for fn in program.functions:
        lower._lower_function(fn)

    # The profiler intentionally omits appended x64 runtime helpers. The MIR
    # functions can still branch/call runtime helper labels, so bypass Python
    # X64 validation and let MachineObjectBuilder keep unresolved names as
    # relocations. This does not affect text byte counts.
    machine.validate_x64_program = lambda _program: None
    builder = MachineObjectBuilder(lower.x64)
    builder._emit_program()
    builder._patch_internal_fixups()

    label_offsets = dict(builder.text_labels)
    entries = []
    for fn in program.functions:
        label = "_start" if fn.name == "main" else fn.name
        offset = label_offsets.get(label)
        if offset is not None:
            entries.append((offset, fn.name, mir_inst_count(fn)))
    entries.sort()

    rows = []
    for index, (offset, name, inst_count) in enumerate(entries):
        end = entries[index + 1][0] if index + 1 < len(entries) else len(builder.text)
        rows.append(
            {
                "text_bytes": end - offset,
                "offset": offset,
                "end": end,
                "mir_insts": inst_count,
                "name": name,
            }
        )
    rows.sort(key=lambda row: row["text_bytes"], reverse=True)
    return rows, len(builder.text)


def main(argv: list[str]) -> int:
    limit = 50
    if len(argv) > 1:
        limit = int(argv[1])

    rows, total_text = build_profile_rows()
    top_sum = sum(row["text_bytes"] for row in rows[:limit])
    print(f"MIR function text bytes total: {total_text:,}")
    print(f"functions: {len(rows)}")
    print(f"top {limit} sum: {top_sum:,} bytes ({top_sum / total_text:.1%})")
    print()
    print("rank  text_bytes  pct_total  mir_inst  function")
    for rank, row in enumerate(rows[:limit], 1):
        pct = row["text_bytes"] / total_text if total_text else 0
        print(
            f"{rank:>4}  {row['text_bytes']:>10,}  {pct:>8.2%}  "
            f"{row['mir_insts']:>8}  {row['name']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
