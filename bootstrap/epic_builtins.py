"""Central inventory of Epic builtins.

This module is currently an inventory only. Parser, sema, and codegen still
own behavior until they are migrated in small commits.
"""

BUILTIN_FUNCTIONS = frozenset({
    "print",
    "println",
    "exit",
    "str",
    "cstr",
    "bytes",
    "len",
    "cap",
    "push",
    "extend",
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
