"""Central inventory of Epic builtins.

This module is currently an inventory only. Parser, sema, and codegen still
own behavior until they are migrated in small commits.
"""

BUILTIN_FUNCTIONS = frozenset({
    "print",
    "println",
    "print_debug",
    "exit",
    "system",

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

    "map_has",
    "map_del",
})

PSEUDO_BUILTINS = frozenset({
    "argv",
})

OS_BUILTIN_NAMESPACES = frozenset({
    "os.kernel32",
})
