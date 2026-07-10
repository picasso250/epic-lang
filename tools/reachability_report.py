#!/usr/bin/env python3
"""Report source/MIR/X64 call reachability for the self-hosted compiler.

This tool is intentionally read-only. It answers whether emitted helpers and
functions are actually referenced in the current full self-hosted compiler
build before we decide whether lazy runtime injection is worth implementing.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from compiler_sources import SELF_HOST_COMPILER_SOURCES

DEFAULT_COMPILER_SOURCES = SELF_HOST_COMPILER_SOURCES


@dataclass
class Pipeline:
    ast: object
    mir: object
    x64: object
    runtime_mir_helpers: set[str]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def add_import_paths(root: Path) -> None:
    sys.path.insert(0, str(root / "bootstrap"))
    sys.path.insert(0, str(root))


def rel_or_abs(root: Path, value: str) -> str:
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str(root / path)


def load_pipeline(root: Path, sources: list[str], main: str) -> Pipeline:
    add_import_paths(root)
    from epic import _merge_programs  # type: ignore
    from sema import analyze_program  # type: ignore
    from ast_to_mir import ast_to_mir  # type: ignore
    from mir_runtime_helpers import runtime_mir_helper_names  # type: ignore
    from mir_to_x64 import lower_mir_to_x64  # type: ignore

    input_paths = [rel_or_abs(root, source) for source in sources]
    main_path = rel_or_abs(root, main)
    ast = analyze_program(_merge_programs(input_paths, main_path, verbose=False))
    mir = ast_to_mir(ast)
    x64 = lower_mir_to_x64(mir)
    return Pipeline(ast=ast, mir=mir, x64=x64, runtime_mir_helpers=set(runtime_mir_helper_names()))


def walk_ast(node):
    if node is None:
        return
    if isinstance(node, (str, int, bool)):
        return
    if isinstance(node, list):
        for item in node:
            yield from walk_ast(item)
        return
    if hasattr(node, "__dataclass_fields__"):
        yield node
        for name in node.__dataclass_fields__:
            yield from walk_ast(getattr(node, name))


def ast_call_names(ast) -> set[str]:
    from ast_nodes import CallNode, DotCallNode  # type: ignore

    names = set()
    for node in walk_ast(ast):
        if isinstance(node, CallNode):
            if node.namespace == "os":
                names.add(f"os.{node.dll}.{node.name}")
            elif node.namespace:
                names.add(f"{node.namespace}.{node.name}")
            else:
                names.add(node.name)
        elif isinstance(node, DotCallNode):
            receiver_type = getattr(node.object, "resolved_type", None)
            if getattr(receiver_type, "kind", "") == "named":
                names.add(f"{receiver_type.name}__{node.name}")
            names.add(node.name)
    return names


def mir_call_graph(program) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for fn in program.functions:
        callees = set()
        for block in fn.blocks:
            for inst in block.instructions:
                if inst.op == "call" and inst.callee:
                    callees.add(inst.callee)
        graph[fn.name] = callees
    return graph


def reachable(graph: dict[str, set[str]], roots: set[str]) -> set[str]:
    seen = set()
    stack = list(sorted(root for root in roots if root in graph))
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        for callee in sorted(graph.get(name, ())):
            if callee in graph and callee not in seen:
                stack.append(callee)
    return seen


def x64_label_graph(program) -> tuple[set[str], dict[str, set[str]], set[str]]:
    from x64 import LabelRef, Symbol, X64Inst, X64Label, X64Section  # type: ignore

    labels = set()
    graph: dict[str, set[str]] = {}
    direct_calls = set()
    current = None
    last_text_inst = None
    section = None
    for item in program.items:
        if isinstance(item, X64Section):
            section = item.name
            current = None
            last_text_inst = None
            continue
        if section != ".text":
            continue
        if isinstance(item, X64Label):
            if item.symbol_name is not None:
                if current is not None and last_text_inst not in ("jmp", "ret"):
                    graph[current].add(item.symbol_name)
                current = item.symbol_name
                last_text_inst = None
                labels.add(current)
                graph.setdefault(current, set())
            continue
        if current is None or not isinstance(item, X64Inst):
            continue
        last_text_inst = item.op
        for operand in item.operands:
            if item.op == "call" and isinstance(operand, Symbol):
                direct_calls.add(operand.name)
                graph[current].add(operand.name)
            elif isinstance(operand, LabelRef):
                if operand.label.symbol_name is not None:
                    graph[current].add(operand.label.symbol_name)
    return labels, graph, direct_calls


def mir_function_size(fn) -> tuple[int, int]:
    insts = sum(len(block.instructions) for block in fn.blocks)
    return insts, len(fn.blocks)


def print_names(title: str, names: list[str], limit: int) -> None:
    print(f"{title}: {len(names)}")
    for name in names[:limit]:
        print(f"  {name}")
    if len(names) > limit:
        print(f"  ... {len(names) - limit} more")


def print_sized(title: str, items: list[tuple[str, int, int]], limit: int) -> None:
    print(f"{title}: {len(items)}")
    for name, insts, blocks in items[:limit]:
        print(f"  {insts:5d} insts {blocks:4d} blocks {name}")
    if len(items) > limit:
        print(f"  ... {len(items) - limit} more")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report source/MIR/X64 reachability.")
    parser.add_argument("--main", default="src/epic.ep", help="main source path")
    parser.add_argument("--source", dest="sources", action="append", help="source path; repeat to override defaults")
    parser.add_argument("--limit", type=int, default=80, help="max rows per section")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = repo_root()
    sources = args.sources or DEFAULT_COMPILER_SOURCES
    pipeline = load_pipeline(root, sources, args.main)

    source_funcs = {fn.name for fn in pipeline.ast.funcs}
    source_calls = ast_call_names(pipeline.ast)
    print(f"sources={len(sources)} main={args.main}")
    print(f"source funcs={len(source_funcs)} direct call spellings={len(source_calls)}")
    print_names("source funcs with no direct source call spelling", sorted(source_funcs - source_calls - {"main"}), args.limit)
    print()

    graph = mir_call_graph(pipeline.mir)
    mir_defined = set(graph)
    mir_direct_calls = set().union(*graph.values()) if graph else set()
    mir_roots = {"main"}
    if "__ep_global_init" in mir_defined:
        mir_roots.add("__ep_global_init")
    mir_reachable = reachable(graph, mir_roots)
    mir_unused = sorted(mir_defined - mir_reachable)
    mir_by_name = {fn.name: fn for fn in pipeline.mir.functions}
    mir_unused_sized = [
        (name, *mir_function_size(mir_by_name[name]))
        for name in mir_unused
    ]
    mir_unused_sized.sort(key=lambda item: (item[1], item[2], item[0]), reverse=True)
    print(
        "MIR "
        + f"defined={len(mir_defined)} direct_callees={len(mir_direct_calls)} "
        + f"reachable_from_main={len(mir_reachable)}"
    )
    print_names("MIR defined but never directly called", sorted(mir_defined - mir_direct_calls - mir_roots), args.limit)
    print_sized("MIR not reachable from main/__ep_global_init", mir_unused_sized, args.limit)
    unused_runtime = sorted((mir_defined - mir_reachable) & pipeline.runtime_mir_helpers)
    print_names("runtime MIR helpers not reachable from MIR roots", unused_runtime, args.limit)
    print()

    labels, x64_graph, x64_direct_calls = x64_label_graph(pipeline.x64)
    x64_reachable = reachable(x64_graph, {"_start"})
    x64_unreachable_public = sorted(name for name in labels - x64_reachable if "." not in name)
    x64_uncalled_public = sorted(name for name in labels - x64_direct_calls - {"_start"} if "." not in name)
    print(
        "X64 "
        + f"text_labels={len(labels)} direct_call_targets={len(x64_direct_calls)} "
        + f"reachable_from_start={len(x64_reachable)}"
    )
    print_names("X64 public labels never directly called", x64_uncalled_public, args.limit)
    print_names("X64 public labels not reachable from _start", x64_unreachable_public, args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
