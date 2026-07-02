"""Runtime fragments for the structured X64 backend."""

from x64 import I, MS, R, Symbol


FULL_RUNTIME = "full"


def emit_runtime_data(x64, program):
    string_globals = {}
    x64.data_zero("_written", 4)
    x64.data_zero("_heap", 8)
    x64.data_zero("_argv", 8)
    x64.data_zero("_str_i64_buf", 32)
    x64.data_bytes("_newline", [10])
    x64.data_zero("_putc_buf", 1)
    x64.data_bytes("_cstr_panic_prefix", list(b"panic line "))
    x64.data_bytes("_cstr_panic_suffix", list(b": invalid cstr"))
    x64.data_bytes("_bool_true_data", [116, 114, 117, 101, 0])
    x64.data_zero("_bool_true_header", 16)
    x64.data_bytes("_bool_false_data", [102, 97, 108, 115, 101, 0])
    x64.data_zero("_bool_false_header", 16)
    for name, text in {
        "_map_repr_prefix": 'map[str]i64{',
        "_map_repr_close": '}',
        "_map_repr_sep": ', ',
        "_map_repr_colon": ': ',
        "_map_repr_quote": '"',
    }.items():
        x64.data_bytes(f"{name}_data", list(text.encode("ascii")) + [0])
        x64.data_zero(f"{name}_header", 16)
    for glob in program.globals:
        if glob.name == "@argv":
            continue
        data_label = _data_label(glob.name)
        header_label = _header_label(glob.name)
        values = list(glob.init.encode("ascii")) + [0]
        string_globals[glob.name] = (header_label, data_label, len(glob.init))
        x64.data_bytes(data_label, values)
        x64.data_zero(header_label, 16)
    return string_globals


def emit_startup_hook_call(x64):
    x64.inst("sub", R("rsp"), I(32))
    x64.inst("call", Symbol("__epic_runtime_start"))
    x64.inst("add", R("rsp"), I(32))


def append_runtime_helpers(lower, policy=FULL_RUNTIME):
    if policy != FULL_RUNTIME:
        raise RuntimeError(f"unsupported X64 runtime policy: {policy}")
    _emit_runtime_start(lower.x64)
    # The helper bodies still live on MirLower during this first split. The
    # ownership boundary is now explicit, so moving bodies into this module is a
    # mechanical follow-up instead of a semantic change.
    lower._emit_runtime_helpers()


def _emit_runtime_start(x64):
    x64.label("__epic_runtime_start")
    x64.inst("push", R("rbp"))
    x64.inst("mov", R("rbp"), R("rsp"))
    x64.inst("sub", R("rsp"), I(32))
    x64.inst("call", Symbol("GetProcessHeap"))
    x64.inst("add", R("rsp"), I(32))
    x64.inst("mov", MS("_heap"), R("rax"))
    x64.inst("sub", R("rsp"), I(32))
    x64.inst("call", Symbol("argv_init"))
    x64.inst("add", R("rsp"), I(32))
    x64.inst("mov", MS("_argv"), R("rax"))
    x64.inst("pop", R("rbp"))
    x64.inst("ret")


def _data_label(name):
    return name[1:] + "_data" if name.startswith("@") else name + "_data"


def _header_label(name):
    return name[1:] + "_header" if name.startswith("@") else name + "_header"
