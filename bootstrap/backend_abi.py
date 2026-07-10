"""Backend-owned MIR ABI validation.

Canonical MIR does not carry import/declare directives. This module is the
x64-windows-v0 authority for external call names and signatures.
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
    "CreateProcessA": MirSignature([], I64),
    "WaitForSingleObject": MirSignature([I64, I64], I64),
    "GetExitCodeProcess": MirSignature([I64, I64], I64),
    "GetCommandLineA": MirSignature([], I64),
    "MessageBoxA": MirSignature([I64, I64, I64, I64], I64),
}

RUNTIME_ABI = {
    "__ep_cstr": MirSignature([ptr(), I64], I64),
    "__ep_write_file": MirSignature([ptr(), ptr(), I64], I64),
    "__ep_read_file": MirSignature([ptr(), I64], ptr()),
    "__ep_system_cmd": MirSignature([ptr(), I64], I64),
    "__ep_print_str": MirSignature([ptr()], VOID),
    "__ep_print_newline": MirSignature([], VOID),
    "__epx_alloc": MirSignature([I64], ptr()),
}

X64_WINDOWS_V0_ABI = {**WINAPI_ABI, **RUNTIME_ABI}


def validate_backend_abi(program, abi=None):
    """Validate every MIR call against module functions or the backend ABI."""

    abi = X64_WINDOWS_V0_ABI if abi is None else abi
    internal = {fn.name: fn.signature for fn in program.functions}
    for fn in program.functions:
        for block in fn.blocks:
            for inst in block.instructions:
                if inst.op != "call":
                    continue
                signature = internal.get(inst.callee)
                if signature is None:
                    signature = abi.get(inst.callee)
                if signature is None:
                    raise BackendAbiError(
                        f"{fn.name}.{block.name}: unknown backend symbol: {inst.callee}"
                    )
                if inst.type != signature.ret:
                    raise BackendAbiError(
                        f"{fn.name}.{block.name}: backend call return type mismatch for "
                        f"{inst.callee}: expected {signature.ret}, got {inst.type}"
                    )
                actual_params = [operand.type for operand in inst.operands]
                if actual_params != signature.params:
                    expected = ", ".join(str(item) for item in signature.params)
                    actual = ", ".join(str(item) for item in actual_params)
                    raise BackendAbiError(
                        f"{fn.name}.{block.name}: backend call argument mismatch for "
                        f"{inst.callee}: expected ({expected}), got ({actual})"
                    )