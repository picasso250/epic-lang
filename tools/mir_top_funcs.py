#!/usr/bin/env python3
"""Report the largest MIR functions for the Epic compiler.

This is a quick triage tool for finding generated-code bloat, especially cases
where source-level type/shape information was lost and MIR repeats dispatch.
Run it from the repository root:

    python tools/mir_top_funcs.py --top 40
    python tools/mir_top_funcs.py --json build/mir-stats.json
    python tools/mir_top_funcs.py --compare build/before.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPILER_SOURCES = [
    path.relative_to(ROOT).as_posix()
    for path in sorted((ROOT / "src").glob("*.ep"))
]


@dataclass
class FunctionStats:
    name: str
    instructions: int
    blocks: int
    terminators: int


@dataclass
class MirStats:
    functions: int
    blocks: int
    instructions: int
    terminators: int
    globals: int
    structs: int
    top_functions: list[FunctionStats]


@dataclass
class X64Stats:
    items: int
    instructions: int
    labels: int
    data: int
    asm_lines: int
    asm_bytes: int


@dataclass
class TimingStats:
    parse_merge_seconds: float
    sema_seconds: float
    ast_to_mir_seconds: float
    mir_to_x64_seconds: float | None
    x64_text_seconds: float | None


@dataclass
class Report:
    sources: list[str]
    main: str
    timings: TimingStats
    mir: MirStats
    x64: X64Stats | None


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def add_import_paths(root: Path) -> None:
    sys.path.insert(0, str(root / "bootstrap"))
    sys.path.insert(0, str(root))


def load_pipeline(root: Path):
    add_import_paths(root)
    from epic import _merge_programs  # type: ignore
    from sema import analyze_program  # type: ignore
    from ast_to_mir import ast_to_mir  # type: ignore
    from mir_to_x64 import lower_mir_to_x64, prepare_mir_for_x64  # type: ignore
    from x64 import X64DataBytes, X64DataZero, X64Inst, X64Label  # type: ignore

    return _merge_programs, analyze_program, ast_to_mir, prepare_mir_for_x64, lower_mir_to_x64, X64Inst, X64Label, X64DataBytes, X64DataZero


def rel_or_abs(root: Path, value: str) -> str:
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str(root / path)


def count_mir_function(fn) -> FunctionStats:
    instructions = sum(len(block.instructions) for block in fn.blocks)
    terminators = sum(1 for block in fn.blocks if block.terminator is not None)
    return FunctionStats(
        name=fn.name,
        instructions=instructions,
        blocks=len(fn.blocks),
        terminators=terminators,
    )


def build_report(args: argparse.Namespace) -> Report:
    root = repo_root()
    (
        merge_programs,
        analyze_program,
        ast_to_mir,
        prepare_mir_for_x64,
        lower_mir_to_x64,
        X64Inst,
        X64Label,
        X64DataBytes,
        X64DataZero,
    ) = load_pipeline(root)

    sources = args.sources or DEFAULT_COMPILER_SOURCES
    input_paths = [rel_or_abs(root, source) for source in sources]
    main_path = rel_or_abs(root, args.main)

    t0 = time.perf_counter()
    ast = merge_programs(input_paths, main_path, verbose=False)
    t1 = time.perf_counter()
    ast = analyze_program(ast)
    t2 = time.perf_counter()
    mir = ast_to_mir(ast)
    prepare_mir_for_x64(mir)
    t3 = time.perf_counter()

    functions = [count_mir_function(fn) for fn in mir.functions]
    functions_sorted = sorted(functions, key=lambda item: (item.instructions, item.blocks, item.name), reverse=True)
    top_functions = functions_sorted[: args.top]
    total_blocks = sum(item.blocks for item in functions)
    total_insts = sum(item.instructions for item in functions)
    total_terms = sum(item.terminators for item in functions)
    mir_stats = MirStats(
        functions=len(mir.functions),
        blocks=total_blocks,
        instructions=total_insts,
        terminators=total_terms,
        globals=len(mir.globals),
        structs=len(mir.structs),
        top_functions=top_functions,
    )

    x64_stats = None
    mir_to_x64_seconds = None
    x64_text_seconds = None
    if not args.no_x64:
        t4 = time.perf_counter()
        x64 = lower_mir_to_x64(mir)
        t5 = time.perf_counter()
        asm_text = x64.text()
        t6 = time.perf_counter()
        x64_stats = X64Stats(
            items=len(x64.items),
            instructions=sum(isinstance(item, X64Inst) for item in x64.items),
            labels=sum(isinstance(item, X64Label) for item in x64.items),
            data=sum(isinstance(item, (X64DataBytes, X64DataZero)) for item in x64.items),
            asm_lines=asm_text.count("\n"),
            asm_bytes=len(asm_text.encode("utf-8")),
        )
        mir_to_x64_seconds = t5 - t4
        x64_text_seconds = t6 - t5

    timings = TimingStats(
        parse_merge_seconds=t1 - t0,
        sema_seconds=t2 - t1,
        ast_to_mir_seconds=t3 - t2,
        mir_to_x64_seconds=mir_to_x64_seconds,
        x64_text_seconds=x64_text_seconds,
    )
    return Report(
        sources=sources,
        main=args.main,
        timings=timings,
        mir=mir_stats,
        x64=x64_stats,
    )


def report_to_json(report: Report) -> dict:
    return asdict(report)


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def format_delta(current: int | float | None, previous: int | float | None) -> str:
    if current is None or previous is None:
        return "n/a"
    delta = current - previous
    pct = (delta / previous * 100.0) if previous else 0.0
    if isinstance(current, float) or isinstance(previous, float):
        return f"{delta:+.3f} ({pct:+.1f}%)"
    return f"{delta:+,d} ({pct:+.1f}%)"


def nested_get(data: dict, keys: Iterable[str]):
    cur = data
    for key in keys:
        if cur is None or key not in cur:
            return None
        cur = cur[key]
    return cur


def print_summary(report: Report, args: argparse.Namespace, baseline: dict | None) -> None:
    data = report_to_json(report)
    mir = report.mir
    timings = report.timings

    print(
        "timing "
        + f"parse_merge={timings.parse_merge_seconds:.3f}s "
        + f"sema={timings.sema_seconds:.3f}s "
        + f"ast_to_mir={timings.ast_to_mir_seconds:.3f}s"
    )
    print(
        "MIR "
        + f"funcs={mir.functions} blocks={mir.blocks} insts={mir.instructions} "
        + f"terms={mir.terminators} globals={mir.globals} structs={mir.structs}"
    )

    if baseline:
        print(
            "MIR delta "
            + f"blocks={format_delta(mir.blocks, nested_get(baseline, ['mir', 'blocks']))} "
            + f"insts={format_delta(mir.instructions, nested_get(baseline, ['mir', 'instructions']))}"
        )

    print("top functions:")
    baseline_funcs = {}
    if baseline:
        for item in nested_get(baseline, ["mir", "top_functions"]) or []:
            baseline_funcs[item.get("name", "")] = item
    for fn in mir.top_functions:
        suffix = ""
        if fn.name in baseline_funcs:
            old = baseline_funcs[fn.name]
            suffix = f"  delta insts={format_delta(fn.instructions, old.get('instructions'))} blocks={format_delta(fn.blocks, old.get('blocks'))}"
        print(f"{fn.instructions:6d} insts {fn.blocks:5d} blocks {fn.name}{suffix}")

    if args.select:
        all_functions = {fn["name"]: fn for fn in data["mir"]["top_functions"]}
        # If a selected function is not in top N, rebuild from JSON is not enough. Keep the
        # output honest instead of pretending it was searched globally.
        print("selected functions:")
        for name in args.select:
            item = all_functions.get(name)
            if item is None:
                print(f"  {name}: not in top {args.top}; rerun with a larger --top")
            else:
                print(f"  {name}: {item['instructions']} insts {item['blocks']} blocks")

    if report.x64:
        x64 = report.x64
        print(
            f"x64 lower={timings.mir_to_x64_seconds:.3f}s "
            + f"text={timings.x64_text_seconds:.3f}s "
            + f"items={x64.items} insts={x64.instructions} labels={x64.labels} "
            + f"data={x64.data} asm_lines={x64.asm_lines} asm_bytes={x64.asm_bytes}"
        )
        if baseline:
            print(
                "x64 delta "
                + f"items={format_delta(x64.items, nested_get(baseline, ['x64', 'items']))} "
                + f"insts={format_delta(x64.instructions, nested_get(baseline, ['x64', 'instructions']))} "
                + f"asm_bytes={format_delta(x64.asm_bytes, nested_get(baseline, ['x64', 'asm_bytes']))}"
            )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report the largest MIR functions in the Epic compiler.")
    parser.add_argument("--top", type=int, default=40, help="number of MIR functions to print/save")
    parser.add_argument("--main", default="src/epic.ep", help="main source path")
    parser.add_argument("--source", dest="sources", action="append", help="source path; repeat to override the default compiler source list")
    parser.add_argument("--no-x64", action="store_true", help="skip MIR -> x64 lowering and asm text size")
    parser.add_argument("--json", dest="json_path", help="write full report to this JSON file")
    parser.add_argument("--compare", help="compare totals and top functions against a previous JSON report")
    parser.add_argument("--select", default="", help="comma-separated functions to highlight if they are present in --top")
    args = parser.parse_args(argv)
    if args.top <= 0:
        parser.error("--top must be positive")
    args.select = [item.strip() for item in args.select.split(",") if item.strip()]
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    baseline = load_json(args.compare) if args.compare else None
    report = build_report(args)
    print_summary(report, args, baseline)
    if args.json_path:
        out_path = Path(args.json_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report_to_json(report), f, indent=2, sort_keys=True)
            f.write("\n")
        print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
