"""Backend-owned MIR ABI validation.

Canonical MIR carries target-neutral extern declarations. This module is the
x64-windows-v0 authority for which externs the backend can provide.
"""

from mir import I64, VOID, MirSignature, ptr


class BackendAbiError(RuntimeError):
    pass


WINAPI_ABI = {
    "ExitProcess": MirSignature([I64], VOID),
    "GetStdHandle": MirSignature([I64], I64),
    "GetProcessHeap": MirSignature([], I64),
    "HeapAlloc": MirSignature([I64, I64, I64], ptr()),
    "CreateFileA": MirSignature([I64, I64, I64, I64, I64, I64, I64], I64),
    "GetFileSize": MirSignature([I64, I64], I64),
    "ReadFile": MirSignature([I64, I64, I64, I64, I64], I64),
    "WriteFile": MirSignature([I64, I64, I64, I64, I64], I64),
    "CloseHandle": MirSignature([I64], I64),
    "GetCommandLineA": MirSignature([], ptr()),
}


X64_WINDOWS_V0_ABI = dict(WINAPI_ABI)


def validate_backend_abi(program, abi=None):
    """Validate declared externs against the concrete backend ABI."""

    abi = X64_WINDOWS_V0_ABI if abi is None else abi
    declarations = {}
    for item in program.externs:
        declarations[item.name] = item.signature
    for name, signature in declarations.items():
        if name.startswith("__ep_import$"):
            continue
        provided = abi.get(name)
        if provided is None:
            raise BackendAbiError(f"unsupported backend extern: {name}")
        if provided != signature:
            raise BackendAbiError(
                f"backend extern signature mismatch for {name}: "
                f"declared {signature}, backend provides {provided}"
            )
