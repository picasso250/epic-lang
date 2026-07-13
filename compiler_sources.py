"""Canonical source order for building the self-hosted Epic compiler."""

SELF_HOST_COMPILER_SOURCES = [
    "src/util.ep",
    "src/lexer.ep",
    "src/parser.ep",
    "src/sema.ep",
    "src/mir.ep",
    "src/mir_text.ep",
    "src/runtime_bundle.ep",
    "src/mir_runtime.ep",
    "src/ast_to_mir.ep",
    "src/x64.ep",
    "src/mir_to_x64.ep",
    "src/machine.ep",
    "src/coff.ep",
    "src/link.ep",
    "src/epic.ep",
]
