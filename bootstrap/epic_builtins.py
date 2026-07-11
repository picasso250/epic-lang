"""Central Python-side inventory of Epic builtin and pseudo-builtin names.

Python sema consumes these sets to reject reserved-name redefinitions. Typing
and MIR lowering remain implemented in ``sema.py`` and ``ast_to_mir.py``;
the self-hosted compiler currently maintains its reservation list separately.
"""

BUILTIN_FUNCTIONS = frozenset({
    "print",
    "println",
    "exit",
    "str",
    "cstr",
    "bytes",
    "len",
    "i64",
    "u64",
    "i32",
    "u32",
    "u8",
    "bool",
    "read_file",
    "write_file",
})

PSEUDO_BUILTINS = frozenset({
    "argv",
})
