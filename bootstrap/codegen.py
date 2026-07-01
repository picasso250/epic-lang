"""
Epic v0 - Emitter: AST dataclass nodes -> NASM x64 assembly
"""

from ast_nodes import *
from codegen_asm import AsmEmitterMixin
from codegen_expr import ExprEmitterMixin
from codegen_stmt import StmtEmitterMixin
from codegen_strings import StringEmitterMixin
from codegen_types import TypeEmitterMixin
from mir_asm import MirAsmProgram


# Emitter facade. Most behavior lives in focused mixins to keep the
# reference compiler readable while preserving the public import surface.
class Emitter(AsmEmitterMixin, TypeEmitterMixin, StringEmitterMixin, ExprEmitterMixin, StmtEmitterMixin):
    def __init__(self, out_path):
        self.out_path = out_path
        self.asm_program = MirAsmProgram()
        self.out = None
        self.include_main_heap_init = True
        self.include_main_argv_init = True
        self.builtins = {"putc", "putstr", "print", "println",
                         "itoa", "system",
                         "str", "str_new", "bytes", "read_file", "write_file",
                         "str_slice", "str_starts_with", "str_find", "str_trim",
                         "str_replace_char", "len", "cap", "push", "extend",
                         "map_has"}
        self.winapi = {
            "Sleep", "GetTickCount64", "GetLastError", "SetLastError",
            "GetStdHandle", "CloseHandle", "lstrlenA", "lstrcmpA",
            "MessageBoxA", "Beep", "GetCurrentProcess",
            "GetCurrentProcessId", "GetCurrentThreadId", "ExitProcess",
            "GetFileAttributesA", "CreateFileA", "ReadFile", "WriteFile",
        }
        self.local_offset = {}  # var name → stack offset relative to rbp
        self.local_count = 0
        self.local_types = {}
        self.label_counter = 0
        self.current_fn = ""
        self.alloc_size = 0     # bytes allocated after push rbp / mov rbp, rsp
        self.strings = {}       # literal text → label name
        self.string_counter = 0
        self.local_bytes = 0    # track variable allocation in pre-scan
        self.structs = {}       # name → {fields: [{name, type, offset}], size}
        self.adts = {}
        self.funcs = {}         # name → {ret_type, params}
        self.globals = {"argv": {"type": "&_arr_str", "label": "_argv"}}
        self.loop_stack = []

    def emit_program(self, ast):
        self.emit("global _start")
        self.emit("extern ExitProcess")
        self.emit("extern GetStdHandle")
        self.emit("extern WriteFile")
        self.emit("extern CreateFileA")
        self.emit("extern ReadFile")
        self.emit("extern SetFilePointer")
        self.emit("extern CloseHandle")
        self.emit("extern GetFileSize")
        self.emit("extern lstrcmpA")
        self.emit("extern lstrcpyA")
        self.emit("extern lstrlenA")
        self.emit("extern CreateProcessA")
        self.emit("extern WaitForSingleObject")
        self.emit("extern GetExitCodeProcess")
        self.emit("extern GetCommandLineA")
        self.emit("extern HeapAlloc")
        self.emit("extern GetProcessHeap")
        for name in sorted(self.winapi):
            if name not in {
                "ExitProcess", "GetStdHandle", "CloseHandle",
                "lstrcmpA", "lstrlenA", "CreateFileA", "ReadFile",
                "WriteFile",
            }:
                self.emit(f"extern {name}")
        self.emit("default rel")
        self.emit("")

        # Compute struct layouts first
        self._compute_struct_layouts(ast)
        self.funcs = {
            fn.name: {"ret_type": self._internal_type(fn.ret_type), "params": fn.params}
            for fn in ast.funcs
        }

        # Collect strings from AST
        self.strings = {}
        self.string_counter = 0
        self._collect_repr_static_strings()
        for func in ast.funcs:
            self._collect_strings_from_block(func.body)

        self.emit("section .data")
        self.emit("    _buf times 32 db 0")
        self.emit("    _buf_end db 0")
        self.emit("    _written dd 0")
        self.emit("    _heap dq 0")
        self.emit("    _argv dq 0")
        # Emit string literals as comma-separated bytes (avoids NASM escaping)
        for label, text in sorted(self.strings.items(), key=lambda x: x[0]):
            bytes_str = ", ".join(str(b) for b in text.encode("ascii"))
            if bytes_str:
                self.emit(f"{label}: db {bytes_str}, 0")
            else:
                self.emit(f"{label}: db 0")
        self.emit("")
        self.emit("section .text")
        self.emit("")

        for func in ast.funcs:
            self.emit_fn_def(func)

        self.emit_label("_epic_trap")
        self.emit_inst("mov ecx, 1")
        self.emit_call_inst("ExitProcess")

    def emit_fn_def(self, fn):
        self.local_offset = {}
        self.local_types = {}
        self.local_bytes = 0
        name = fn.name
        self.current_fn = name
        self.current_ep_label = f"{name}_ep"
        params = fn.params
        body = fn.body
        if len(params) > 4:
            raise RuntimeError(f"Function {name} has >4 parameters (not supported)")

        # Pre-scan parameters FIRST so local_bytes includes them
        for p in params:
            self.get_var_slot(p.name, self._internal_type(p.type))

        # Pre-scan: allocate stack slots for let declarations
        self._pre_scan_block(body)

        # Pre-scan: count max temp slots needed
        max_temps = self._pre_scan_temps(body)
        temp_bytes = max(max_temps + 1, 1024) * 8

        # Entry label: main → _start
        label = "_start" if name == "main" else name
        self.emit_label(label)

        # Prologue: dynamic frame, 16-byte aligned (include 32-byte shadow + compiler temps)
        self._temp_count = 0
        self._temp_base = self.local_bytes  # temps start below user vars
        self.alloc_size = ((self.local_bytes + temp_bytes + 32 + 15) // 16) * 16
        self.emit_inst("push rbp")
        self.emit_mov("rbp", "rsp")
        self.emit_inst(f"sub rsp, {self.alloc_size}")

        # Heap init for main
        if name == "main" and self.include_main_heap_init:
            self.emit_call_inst("GetProcessHeap")
            self.emit_mov("[_heap]", "rax")
        if name == "main" and self.include_main_argv_init:
            self.emit_call_inst("_argv_init")
            self.emit_mov("[_argv]", "rax")

        # Map params from registers to local slots
        param_regs = ["rcx", "rdx", "r8", "r9"]
        param_low = ["cl", "dl", "r8b", "r9b"]  # low-byte names
        for i, p in enumerate(params):
            slot = self.get_var_slot(p.name)
            ptype = self._internal_type(p.type)
            self.local_types[p.name] = ptype
            if ptype == "i8":
                self.emit_stack_store(slot, param_low[i])
            else:
                self.emit_stack_store(slot, param_regs[i])

        # Body
        self.emit_block(body)

        if name == "main":
            self.emit_mov("ecx", "0")
            self.emit_call_inst("ExitProcess")
        else:
            self.emit_label(self.current_ep_label)
            self.emit_mov("rsp", "rbp")
            self.emit_inst("pop rbp")
            self.emit_inst("ret")

        self.emit("")
