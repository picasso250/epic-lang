"""MIR reachability pruning."""

from __future__ import annotations


def _function_calls(fn) -> set[str]:
    calls = set()
    for block in fn.blocks:
        for inst in block.instructions:
            if inst.op == "call" and inst.callee:
                calls.add(inst.callee)
    return calls


def prune_unreachable_functions(program) -> None:
    """Remove MIR functions that are not reachable from program/runtime roots."""
    functions = {fn.name: fn for fn in program.functions}
    roots = {"main"}
    reachable = set()
    stack = [name for name in sorted(roots) if name in functions]

    while stack:
        name = stack.pop()
        if name in reachable:
            continue
        reachable.add(name)
        for callee in sorted(_function_calls(functions[name])):
            if callee in functions and callee not in reachable:
                stack.append(callee)

    program.functions[:] = [fn for fn in program.functions if fn.name in reachable]
