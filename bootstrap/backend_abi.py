"""Backend-owned MIR ABI validation.

Canonical MIR carries target-neutral extern declarations. This module is the
x64-windows-v0 authority for which externs the backend can provide.
"""

from mir import I64, VOID, MirSignature, ptr


class BackendAbiError(RuntimeError):
    pass


WINAPI_ABI = {
    "ExitProcess": MirSignature([I64], VOID),
    "Sleep": MirSignature([I64], VOID),
    "GetTickCount64": MirSignature([], I64),
    "lstrlenA": MirSignature([I64], I64),
    "lstrcmpA": MirSignature([I64, I64], I64),
    "GetStdHandle": MirSignature([I64], I64),
    "GetProcessHeap": MirSignature([], I64),
    "HeapAlloc": MirSignature([I64, I64, I64], I64),
    "CreateFileA": MirSignature([I64, I64, I64, I64, I64, I64, I64], I64),
    "GetFileSize": MirSignature([I64, I64], I64),
    "ReadFile": MirSignature([I64, I64, I64, I64, I64], I64),
    "WriteFile": MirSignature([I64, I64, I64, I64, I64], I64),
    "CloseHandle": MirSignature([I64], I64),
    "GetCommandLineA": MirSignature([], I64),
    "MessageBoxA": MirSignature([I64, I64, I64, I64], I64),
}

RUNTIME_ABI = {
    "__ep_cstr": MirSignature([ptr(), I64], I64),
    "__ep_write_file": MirSignature([ptr(), ptr(), I64], I64),
    "__ep_read_file": MirSignature([ptr(), I64], ptr()),
    "__ep_print_str": MirSignature([ptr()], VOID),
    "__ep_print_newline": MirSignature([], VOID),
    "__epx_alloc": MirSignature([I64], ptr()),
}

X64_WINDOWS_V0_ABI = {**WINAPI_ABI, **RUNTIME_ABI}


def validate_backend_abi(program, abi=None):
    """Validate declared externs against the concrete backend ABI."""

    abi = X64_WINDOWS_V0_ABI if abi is None else abi
    declarations = {}
    for item in program.externs:
        declarations[item.name] = item.signature
    for name, signature in declarations.items():
        provided = abi.get(name)
        if provided is None:
            raise BackendAbiError(f"unsupported backend extern: {name}")
        if provided != signature:
            raise BackendAbiError(
                f"backend extern signature mismatch for {name}: "
                f"declared {signature}, backend provides {provided}"
            )
