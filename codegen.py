"""
Epic v0 — Emitter: AST dataclass nodes → NASM x64 assembly
"""

import dataclasses

from ast_nodes import *


# ═══════════════════════════════════════════════════════════════════════════
#  Emitter (AST → NASM assembly)
# ═══════════════════════════════════════════════════════════════════════════

class Emitter:
    def __init__(self, out_path):
        self.out = open(out_path, "w")
        self.builtins = {"putc", "putstr",
                         "itoa", "system",
                         "str_new", "read_file", "write_file",
                         "append_file", "push"}
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
        self.funcs = {}         # name → {ret_type, params}
        self.globals = {"argv": {"type": "&_arr_str", "label": "_argv"}}

    def emit(self, s):
        self.out.write(s + "\n")

    def emit_label(self, name):
        self.emit(f"{name}:")

    def emit_inst(self, op):
        self.emit(f"    {op}")

    def emit_mov(self, dst, src):
        self.emit_inst(f"mov {dst}, {src}")

    def emit_lea(self, dst, src):
        self.emit_inst(f"lea {dst}, {src}")

    def emit_call_inst(self, target):
        self.emit_inst(f"call {target}")

    def emit_jmp(self, label):
        self.emit_inst(f"jmp {label}")

    def rbp_slot(self, slot):
        return f"[rbp{slot:+d}]"

    def emit_stack_store(self, slot, src):
        self.emit_mov(self.rbp_slot(slot), src)

    def emit_stack_load(self, dst, slot):
        self.emit_mov(dst, self.rbp_slot(slot))

    def fresh_label(self):
        self.label_counter += 1
        return f"L{self.label_counter}"

    def close(self):
        self.out.close()

    # ── program header ──────────────────────────────────────────────────

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

    def _collect_strings_from_block(self, block):
        """Recursively collect strings from AST."""
        for stmt in block.stmts:
            if isinstance(stmt, IfNode):
                self._collect_strings_from_block(stmt.then_block)
                if stmt.else_block:
                    self._collect_strings_from_block(stmt.else_block)
            elif isinstance(stmt, WhileNode):
                self._collect_strings_from_block(stmt.body)
            self._collect_strings(stmt)

    def _collect_strings(self, node):
        """Recursively find string literals and register them."""
        if isinstance(node, StringNode):
            self.get_string_label(node.value)
        if isinstance(node, ASTNode):
            for f in dataclasses.fields(node):
                self._collect_strings(getattr(node, f.name))
        elif isinstance(node, list):
            for item in node:
                self._collect_strings(item)

    def get_string_label(self, text):
        # Check if text already has a label
        for lbl, txt in self.strings.items():
            if txt == text:
                return lbl
        # New string
        self.string_counter += 1
        label = f"_str_{self.string_counter}"
        self.strings[label] = text
        return label

    # ── function definition ────────────────────────────────────────────

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
        temp_bytes = max(max_temps + 1, 3) * 8  # at least 3 temps (24 bytes)

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
        if name == "main":
            self.emit_call_inst("GetProcessHeap")
            self.emit_mov("[_heap]", "rax")
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

    # ── ABI helpers ───────────────────────────────────────────────────

    def _call_prep(self, stack_args=0):
        """Emit sub rsp for extra stack params beyond the 4 register params.
        The frame already has 32 bytes shadow space; extra bytes are for
        params 5+ at [rsp+32], [rsp+40], etc.  Alignment: rsp ≡ 8 mod 16."""
        extra_bytes = stack_args * 8
        if extra_bytes == 0:
            return 0
        frame = ((extra_bytes + 15) // 16) * 16
        self.emit(f"    sub rsp, {frame}")
        return frame

    def _call_cleanup(self, stack_args=0):
        extra_bytes = stack_args * 8
        if extra_bytes == 0:
            return
        frame = ((extra_bytes + 15) // 16) * 16
        self.emit(f"    add rsp, {frame}")

    def _spill_args(self, args):
        slots = []
        for arg in args:
            self.emit_expr(arg)
            slot = self._alloc_temp()
            self.emit_stack_store(slot, "rax")
            slots.append(slot)
        return slots

    def _load_spilled_args(self, slots):
        param_regs = ["rcx", "rdx", "r8", "r9"]
        for i, slot in enumerate(slots):
            self.emit_stack_load(param_regs[i], slot)

    def _call_with_shadow(self, target):
        self.emit("    sub rsp, 32")
        self.emit_call_inst(target)
        self.emit("    add rsp, 32")

    def _syscall_symbol(self, name, namespace=""):
        if namespace == "sys":
            symbol = name
        elif name.startswith("sys."):
            symbol = name[4:]
        else:
            return None
        if symbol not in self.winapi:
            full_name = f"{namespace}.{name}" if namespace else name
            raise RuntimeError(f"Unsupported sys call: {full_name}")
        return symbol

    def _emit_syscall(self, symbol, args):
        param_regs = ["rcx", "rdx", "r8", "r9"]
        slots = []
        for arg in args:
            arg_type = self._expr_type(arg)
            self.emit_expr(arg)
            if arg_type == "&str":
                self.emit_mov("rax", "[rax]")
            slot = self._alloc_temp()
            self.emit_stack_store(slot, "rax")
            slots.append(slot)
        stack_args = max(0, len(slots) - 4)
        extra_bytes = stack_args * 8
        extra_frame = ((extra_bytes + 15) // 16) * 16
        frame = 32 + extra_frame
        for i, slot in enumerate(slots[:4]):
            self.emit_stack_load(param_regs[i], slot)
        self.emit(f"    sub rsp, {frame}")
        for i, slot in enumerate(slots[4:]):
            self.emit_stack_load("rax", slot)
            self.emit_mov(f"[rsp+{32 + i * 8}]", "rax")
        self.emit_call_inst(symbol)
        self.emit(f"    add rsp, {frame}")

    def get_var_slot(self, name, typ=None):
        if name not in self.local_offset:
            size = self._type_size(typ) if typ else 8
            # 8-byte align
            if self.local_bytes % 8 != 0:
                self.local_bytes += 8 - (self.local_bytes % 8)
            self.local_bytes += size
            self.local_offset[name] = -self.local_bytes
        return self.local_offset[name]

    def _alloc_temp(self):
        """Allocate a compiler temporary frame slot, return rbp-relative offset."""
        nr = self._temp_count
        self._temp_count += 1
        return -(self._temp_base + (nr + 1) * 8)

    def _type_size(self, typ):
        typ = self._internal_type(typ) if typ else typ
        if typ == "i64":
            return 8
        if typ == "i8":
            return 1
        if typ in self.structs:
            return self.structs[typ]["size"]
        if typ.startswith("&"):
            return 8  # pointers are always 8 bytes
        return 8  # unknown, assume i64

    def _global_symbol(self, name):
        return self.globals.get(name)

    def _emit_global_load(self, sym):
        self.emit_mov("rax", f"[{sym['label']}]")

    def _internal_type(self, typ):
        """Lower user-facing types to the internal pointer-heavy representation."""
        if typ is None:
            return None
        if typ.startswith("&"):
            return typ
        if typ.endswith("[]"):
            elem = self._internal_type(typ[:-2])
            if elem.startswith("&"):
                elem = elem[1:]
            self._ensure_array_type(elem)
            return f"&_arr_{elem}"
        if typ in ("i64", "i8", "void"):
            return typ
        return f"&{typ}"

    def _array_data_type(self, elem):
        return f"&{elem}" if elem in ("i64", "i8") else f"&&{elem}"

    def _register_len_data_type(self, name, elem_ptr_type, has_cap=False):
        """Register a {data, len[, cap]} layout type. data is always offset 0."""
        if name not in self.structs:
            fields = [
                {"name": "data", "type": elem_ptr_type, "offset": 0},
                {"name": "len", "type": "i64", "offset": 8},
            ]
            size = 16
            if has_cap:
                fields.append({"name": "cap", "type": "i64", "offset": 16})
                size = 24
            self.structs[name] = {
                "fields": fields,
                "size": size,
            }

    def _ensure_array_type(self, elem):
        arr_type = f"_arr_{elem}"
        self._register_len_data_type(arr_type, self._array_data_type(elem), has_cap=True)
        return arr_type

    def _compute_struct_layouts(self, ast):
        self.structs = {}
        # Built-in str type: { data: &i8, len: i64 }
        self._register_len_data_type("str", "&i8")
        # Array-of-str type used by argv.
        self._register_len_data_type("_arr_str", "&&str", has_cap=True)
        for s in ast.structs:
            fields = []
            offset = 0
            for f in s.fields:
                ftype = self._internal_type(f.type)
                fields.append({"name": f.name, "type": ftype, "offset": offset})
                offset += 8
            self.structs[s.name] = {"fields": fields, "size": offset}

    def _pre_scan_block(self, block):
        """Allocate stack slots for all let declarations."""
        for stmt in block.stmts:
            if isinstance(stmt, LetNode):
                self.get_var_slot(stmt.name, stmt.var_type)
            elif isinstance(stmt, IfNode):
                self._pre_scan_block(stmt.then_block)
                if stmt.else_block:
                    self._pre_scan_block(stmt.else_block)
            elif isinstance(stmt, WhileNode):
                self._pre_scan_block(stmt.body)

    def _pre_scan_temps(self, node):
        """Count temp slots needed. Covers: binary ops (1), putstr (1), struct new_array (3)."""
        if isinstance(node, ASTNode):
            count = 0
            if isinstance(node, BinaryNode):
                count = 1
            elif isinstance(node, CallNode):
                count = len(node.args)
                if node.name == "putstr":
                    count += 1  # putstr saves &str across GetStdHandle
                elif node.name == "push":
                    count += 3
            elif isinstance(node, NewArrayNode):
                count = 2
            for f in dataclasses.fields(node):
                v = getattr(node, f.name)
                if isinstance(v, (ASTNode, list)):
                    count += self._pre_scan_temps(v)
            return count
        elif isinstance(node, list):
            total = 0
            for item in node:
                total += self._pre_scan_temps(item)
            return total
        return 0

    # ── statements ─────────────────────────────────────────────────────

    def emit_block(self, block):
        for stmt in block.stmts:
            self.emit_stmt(stmt)

    def emit_stmt(self, stmt):
        if isinstance(stmt, ReturnNode):
            self.emit_return(stmt)
        elif isinstance(stmt, ExprStmtNode):
            self.emit_expr(stmt.expr)
        elif isinstance(stmt, LetNode):
            self.emit_let(stmt)
        elif isinstance(stmt, IfNode):
            self.emit_if(stmt)
        elif isinstance(stmt, WhileNode):
            self.emit_while(stmt)
        elif isinstance(stmt, AssignNode):
            self.emit_assign(stmt)
        elif isinstance(stmt, FieldSetNode):
            self.emit_field_set(stmt)
        elif isinstance(stmt, SubscriptAssignNode):
            self.emit_subscript_assign(stmt)
        else:
            raise RuntimeError(f"Unknown stmt type: {type(stmt).__name__}")

    def emit_return(self, stmt):
        if self.current_fn == "main":
            if stmt.expr is None:
                self.emit_mov("ecx", "0")
            else:
                self.emit_expr(stmt.expr)
                self.emit_mov("ecx", "eax")
            self.emit_call_inst("ExitProcess")
        else:
            if stmt.expr is not None:
                self.emit_expr(stmt.expr)
            ep_label = getattr(self, "current_ep_label", f"{self.current_fn}_ep")
            self.emit_jmp(ep_label)

    def emit_let(self, stmt):
        name = stmt.name
        var_type = stmt.var_type
        value = stmt.value
        # Type inference from initializer
        if var_type is None and value is not None:
            if isinstance(value, NewNode):
                var_type = f"&{value.struct_name}"
            elif isinstance(value, NewArrayNode):
                var_type = f"&_arr_{value.elem_type}"
            elif isinstance(value, CallNode) and value.name == "itoa":
                var_type = "&str"
            elif isinstance(value, CallNode) and value.name == "str_new":
                var_type = "&str"
            elif isinstance(value, StringNode):
                var_type = "&str"
            else:
                var_type = self._expr_type(value)
        if var_type is None:
            var_type = "i64"
        var_type = self._internal_type(var_type)
        slot = self.get_var_slot(name, var_type)
        self.local_types[name] = var_type
        if value is None:
            return  # declaration without initializer
        self.emit_expr(value)
        if var_type == "i8":
            self.emit_stack_store(slot, "al")
        else:
            self.emit_stack_store(slot, "rax")

    def emit_if(self, stmt):
        else_label = self.fresh_label()
        end_label = self.fresh_label()
        self.emit_expr(stmt.cond)
        self.emit("    test rax, rax")
        if stmt.else_block:
            self.emit(f"    jz {else_label}")
        else:
            self.emit(f"    jz {end_label}")
        self.emit_block(stmt.then_block)
        if stmt.else_block:
            self.emit_jmp(end_label)
            self.emit_label(else_label)
            self.emit_block(stmt.else_block)
        self.emit_label(end_label)

    def emit_while(self, stmt):
        start_label = self.fresh_label()
        end_label = self.fresh_label()
        self.emit_label(start_label)
        self.emit_expr(stmt.cond)
        self.emit("    test rax, rax")
        self.emit(f"    jz {end_label}")
        self.emit_block(stmt.body)
        self.emit_jmp(start_label)
        self.emit_label(end_label)

    def emit_assign(self, stmt):
        name = stmt.name
        self.emit_expr(stmt.value)
        slot = self.local_offset.get(name)
        if slot is None:
            raise RuntimeError(f"Undefined variable: {name}")
        var_type = self.local_types.get(name, "i64")
        if var_type == "i8":
            self.emit_stack_store(slot, "al")
        else:
            self.emit_stack_store(slot, "rax")

    # ── expressions ────────────────────────────────────────────────────

    def emit_expr(self, expr):
        if isinstance(expr, LiteralNode):
            self.emit_mov("rax", expr.value)
        elif isinstance(expr, StringNode):
            label = self.get_string_label(expr.value)
            strlen = len(expr.value)
            self.emit_lea("rcx", f"[{label}]")
            self.emit_mov("rdx", strlen)
            self.emit_call_inst("_str_alloc")
        elif isinstance(expr, VarNode):
            name = expr.name
            if sym := self._global_symbol(name):
                self._emit_global_load(sym)
                return
            slot = self.local_offset.get(name)
            if slot is None:
                raise RuntimeError(f"Undefined variable: {name}")
            var_type = self.local_types.get(name, "i64")
            if var_type == "i8":
                self.emit(f"    movsx rax, byte [rbp{slot:+d}]")
            else:
                self.emit_stack_load("rax", slot)
        elif isinstance(expr, CallNode):
            self.emit_call(expr)
        elif isinstance(expr, SubscriptNode):
            self.emit_subscript(expr)
        elif isinstance(expr, BinaryNode):
            self.emit_binary(expr)
        elif isinstance(expr, FieldAccessNode):
            self.emit_field_access(expr)
        elif isinstance(expr, NewNode):
            self.emit_new(expr)
        elif isinstance(expr, NewArrayNode):
            self.emit_new_array(expr)
        else:
            raise RuntimeError(f"Unknown expr type: {type(expr).__name__}")

    def emit_call(self, expr):
        name = expr.name
        args = expr.args

        if symbol := self._syscall_symbol(name, expr.namespace):
            self._emit_syscall(symbol, args)
            return

        if name in self.builtins:
            if name == "putc":
                self.emit_expr(args[0])
                self.emit_mov("[_buf]", "al")
                self.emit_mov("ecx", "-11")
                self.emit_call_inst("GetStdHandle")
                self.emit_mov("rcx", "rax")
                self.emit_lea("rdx", "[_buf]")
                self.emit_mov("r8", "1")
                self.emit_lea("r9", "[_written]")
                self._call_prep(1)
                self.emit_mov("qword [rsp+32]", "0")
                self.emit_call_inst("WriteFile")
                self._call_cleanup(1)
            elif name == "putstr":
                # putstr(s: &str): save &str in temp slot, GetStdHandle, then WriteFile
                self.emit_expr(args[0])       # rax = &str
                tmp = self._alloc_temp()
                self.emit_stack_store(tmp, "rax")  # save &str
                self.emit_mov("ecx", "-11")  # STD_OUTPUT_HANDLE
                self.emit_call_inst("GetStdHandle")
                self.emit_mov("rcx", "rax")   # rcx = stdout handle
                self.emit_stack_load("rax", tmp)  # rax = &str
                self.emit_mov("rdx", "[rax]")      # rdx = str.data (offset 0)
                self.emit_mov("r8", "[rax+8]")    # r8 = str.len (offset 8)
                self.emit_lea("r9", "[_written]")
                self._call_prep(1)             # 1 stack arg (lpOverlapped)
                self.emit_mov("qword [rsp+32]", "0")
                self.emit_call_inst("WriteFile")
                self._call_cleanup(1)
            elif name == "itoa":
                # itoa(n) → &str (heap-allocated)
                self.emit_expr(args[0])     # rax = n
                self.emit_mov("rcx", "rax")  # rcx = n
                self.emit_call_inst("_itoa")
            elif name == "system":
                # system(cmd: &str) → extract cmd.data, call _system
                self.emit_expr(args[0])       # rax = &str
                self.emit_mov("rcx", "[rax]")    # rcx = cmd.data (offset 0)
                self.emit("    sub rsp, 8")       # align for _system entry
                self.emit_call_inst("_system")
                self.emit("    add rsp, 8")
            elif name == "read_file":
                self.emit_expr(args[0])
                self.emit_mov("rcx", "[rax]")
                self.emit("    sub rsp, 8")
                self.emit_call_inst("_read_file")
                self.emit("    add rsp, 8")
            elif name == "write_file":
                slots = self._spill_args(args)
                self.emit_stack_load("rax", slots[0])
                self.emit_mov("rcx", "[rax]")      # path.data
                self.emit_stack_load("rax", slots[1])
                self.emit_mov("rdx", "[rax]")      # data.data
                self.emit_mov("r8", "[rax+8]")     # data.len
                self.emit("    sub rsp, 8")
                self.emit_call_inst("_write_file")
                self.emit("    add rsp, 8")
            elif name == "append_file":
                slots = self._spill_args(args)
                self.emit_stack_load("rax", slots[0])
                self.emit_mov("rcx", "[rax]")      # path.data
                self.emit_stack_load("rax", slots[1])
                self.emit_mov("rdx", "[rax]")      # data.data
                self.emit_mov("r8", "[rax+8]")     # data.len
                self.emit("    sub rsp, 8")
                self.emit_call_inst("_append_file")
                self.emit("    add rsp, 8")
            elif name == "str_new":
                # str(bytes: &i8, len: i64) → &str (deep-copy via _str_alloc)
                slots = self._spill_args(args)
                self.emit_stack_load("rcx", slots[0])
                self.emit_stack_load("rdx", slots[1])
                self.emit_call_inst("_str_alloc")
            elif name == "push":
                self.emit_push(args)
            return

        if len(args) > 4:
            raise RuntimeError(f"Function {name} has >4 arguments (not supported)")
        slots = self._spill_args(args)
        self._load_spilled_args(slots)
        self._call_with_shadow(name)

    def emit_binary(self, expr):
        op = expr.op
        left = expr.left
        right = expr.right

        if op in ("&&", "||"):
            self.emit_short_circuit(expr)
            return

        # Evaluate right to temp slot, evaluate left → rax, load right → rcx
        # Using temp slot (not push/pop) so left expr can contain calls without
        # clobbering stack alignment or shadow space.
        left_type = self._expr_type(left)
        right_type = self._expr_type(right)
        self.emit_expr(right)
        tmp = self._alloc_temp()
        self.emit_stack_store(tmp, "rax")
        self.emit_expr(left)

        if op in ("==", "!=") and left_type == "&str" and right_type == "&str":
            self.emit_mov("rcx", "[rax]")
            self.emit_stack_load("rax", tmp)
            self.emit_mov("rdx", "[rax]")
            self._call_with_shadow("lstrcmpA")
            self.emit("    cmp eax, 0")
            self.emit("    sete al" if op == "==" else "    setne al")
            self.emit("    movzx eax, al")
            return

        if op == "+" and left_type == "&str" and right_type == "&str":
            self.emit_mov("rcx", "rax")
            self.emit_stack_load("rdx", tmp)
            self._call_with_shadow("_str_cat")
            return

        self.emit_stack_load("rcx", tmp)

        op_map = {
            "+": "add rax, rcx",
            "-": "sub rax, rcx",
            "*": "imul rax, rcx",
        }

        if op in op_map:
            self.emit(f"    {op_map[op]}")
        elif op == "/":
            self.emit("    cqo")
            self.emit("    idiv rcx")
        elif op == "%":
            self.emit("    cqo")
            self.emit("    idiv rcx")
            self.emit_mov("rax", "rdx")
        elif op == "==":
            self.emit("    cmp rax, rcx")
            self.emit("    sete al")
            self.emit("    movzx eax, al")
        elif op == "!=":
            self.emit("    cmp rax, rcx")
            self.emit("    setne al")
            self.emit("    movzx eax, al")
        elif op == "<":
            self.emit("    cmp rax, rcx")
            self.emit("    setl al")
            self.emit("    movzx eax, al")
        elif op == ">":
            self.emit("    cmp rax, rcx")
            self.emit("    setg al")
            self.emit("    movzx eax, al")
        elif op == "<=":
            self.emit("    cmp rax, rcx")
            self.emit("    setle al")
            self.emit("    movzx eax, al")
        elif op == ">=":
            self.emit("    cmp rax, rcx")
            self.emit("    setge al")
            self.emit("    movzx eax, al")
        else:
            raise RuntimeError(f"Unknown binary op: {op}")

    def emit_short_circuit(self, expr):
        op = expr.op
        end_label = self.fresh_label()
        true_label = self.fresh_label()

        self.emit_expr(expr.left)
        if op == "&&":
            self.emit("    test rax, rax")
            self.emit(f"    jz {end_label}")
        else:  # ||
            self.emit("    test rax, rax")
            self.emit(f"    jnz {true_label}")

        self.emit_expr(expr.right)

        if op == "||":
            self.emit_label(true_label)

        self.emit("    test rax, rax")
        self.emit("    setne al")
        self.emit("    movzx eax, al")
        self.emit_label(end_label)

    # ── struct operations ─────────────────────────────────────────────

    def _resolve_field(self, var_name, field_name):
        """Return (slot_offset, field_offset, field_type, is_ptr) for var.field."""
        slot = self.local_offset.get(var_name)
        if slot is None:
            raise RuntimeError(f"Undefined variable: {var_name}")
        var_type = self.local_types.get(var_name, "i64")
        is_ptr = var_type.startswith("&")
        struct_name = var_type[1:] if is_ptr else var_type
        if struct_name not in self.structs:
            raise RuntimeError(f"Field access on non-struct type '{var_type}'")
        info = self.structs[struct_name]
        for f in info["fields"]:
            if f["name"] == field_name:
                return slot, f["offset"], f["type"], is_ptr
        raise RuntimeError(f"Struct '{struct_name}' has no field '{field_name}'")

    def _emit_struct_base(self, slot, is_ptr):
        """Emit instruction to load base address into rax."""
        if is_ptr:
            self.emit_stack_load("rax", slot)
        else:
            self.emit_lea("rax", self.rbp_slot(slot))

    def _emit_struct_base_rcx(self, slot, is_ptr):
        """Emit instruction to load base address into rcx."""
        if is_ptr:
            self.emit_stack_load("rcx", slot)
        else:
            self.emit_lea("rcx", self.rbp_slot(slot))

    def emit_field_access(self, expr):
        """Read expr.object.field into rax."""
        obj = expr.object
        field_name = expr.field
        if isinstance(obj, VarNode):
            if sym := self._global_symbol(obj.name):
                self._emit_global_load(sym)
                self._emit_field_read_from_rax(obj, field_name)
                return
            slot, off, ftype, is_ptr = self._resolve_field(obj.name, field_name)
            self._emit_struct_base(slot, is_ptr)
            if ftype == "i8":
                self.emit(f"    movsx rax, byte [rax+{off}]")
            else:
                self.emit(f"    mov rax, [rax+{off}]")
        elif isinstance(obj, SubscriptNode):
            # Subscript returned a pointer; access its field
            self.emit_subscript(obj)
            # rax = pointer to element.
            self._emit_field_read_from_rax(obj, field_name)
        elif isinstance(obj, FieldAccessNode):
            # Chain: obj.field2.field1 — evaluate inner, then read field from rax
            self.emit_field_access(obj)
            self._emit_field_read_from_rax(obj, field_name)
        else:
            raise RuntimeError(f"Field access on non-variable: {type(obj).__name__}")

    def _emit_field_read_from_rax(self, source_expr, field_name):
        """Read field_name from a struct pointer already in rax."""
        elem_type = self._expr_type(source_expr)
        if not elem_type.startswith("&"):
            raise RuntimeError(f"Field access on value type '{elem_type}'")
        struct_name = elem_type[1:]
        if struct_name not in self.structs:
            raise RuntimeError(f"Field access on unknown type '{struct_name}'")
        info = self.structs[struct_name]
        for f in info["fields"]:
            if f["name"] == field_name:
                if f["type"] == "i8":
                    self.emit(f"    movsx rax, byte [rax+{f['offset']}]")
                else:
                    self.emit(f"    mov rax, [rax+{f['offset']}]")
                return
        raise RuntimeError(f"Struct '{struct_name}' has no field '{field_name}'")

    def _emit_field_write_to_rax(self, source_expr, field_name):
        """Write rcx to field_name of struct pointer in rax."""
        elem_type = self._expr_type(source_expr)
        if not elem_type.startswith("&"):
            raise RuntimeError(f"Field write on value type")
        struct_name = elem_type[1:]
        if struct_name not in self.structs:
            raise RuntimeError(f"Field write on unknown type: {struct_name}")
        info = self.structs[struct_name]
        for f in info["fields"]:
            if f["name"] == field_name:
                if f["type"] == "i8":
                    self.emit(f"    mov [rax+{f['offset']}], cl")
                else:
                    self.emit(f"    mov [rax+{f['offset']}], rcx")
                return
        raise RuntimeError(f"Struct '{struct_name}' has no field '{field_name}'")

    def emit_field_set(self, stmt):
        """stmt.object.field = stmt.value"""
        obj = stmt.object
        field_name = stmt.field
        if isinstance(obj, VarNode):
            # Evaluate value first (may use same struct)
            self.emit_expr(stmt.value)
            self.emit("    push rax")
            slot, off, ftype, is_ptr = self._resolve_field(obj.name, field_name)
            self._emit_struct_base_rcx(slot, is_ptr)
            self.emit("    pop rax")
            if ftype == "i8":
                self.emit(f"    mov [rcx+{off}], al")
            else:
                self.emit(f"    mov [rcx+{off}], rax")
        elif isinstance(obj, SubscriptNode):
            # Subscript result is a pointer; set field on it
            self.emit_expr(stmt.value)
            self.emit("    push rax")
            self.emit_subscript(obj)
            self.emit("    pop rcx")
            # rax = pointer to struct, rcx = value
            # Resolve element type from subscript base
            elem_type = self._expr_type(obj)
            # Strip leading & to get struct name
            if not elem_type.startswith("&"):
                raise RuntimeError(f"Field set on value type")
            struct_name = elem_type[1:]
            if struct_name not in self.structs:
                raise RuntimeError(f"Field set on unknown type: {struct_name}")
            info = self.structs[struct_name]
            for f in info["fields"]:
                if f["name"] == field_name:
                    if f["type"] == "i8":
                        self.emit(f"    mov [rax+{f['offset']}], cl")
                    else:
                        self.emit(f"    mov [rax+{f['offset']}], rcx")
                    return
            raise RuntimeError(f"Struct '{struct_name}' has no field '{field_name}'")
        elif isinstance(obj, FieldAccessNode):
            # Chain: obj.field2.field1 = value
            self.emit_expr(stmt.value)
            self.emit("    push rax")
            self.emit_field_access(obj)
            self.emit("    pop rcx")
            self._emit_field_write_to_rax(obj, field_name)
        else:
            raise RuntimeError(f"Field set on non-var: {type(obj).__name__}")

    def emit_subscript_assign(self, stmt):
        """base[index] = value"""
        base = stmt.base
        index = stmt.index
        value = stmt.value
        # Compute element type from a synthetic subscript expression
        synth = SubscriptNode(base=base, index=index)
        elem_type = self._expr_type(synth)
        is_i8 = (elem_type == "i8")
        # Evaluate value first
        self.emit_expr(value)
        self.emit("    push rax")
        # Compute address: base + index * size
        base_type = self._expr_type(base)
        self.emit_expr(base)        # rax = base pointer or array header
        if base_type.startswith("&_arr_"):
            self.emit("    mov rax, [rax]")
        self.emit("    push rax")
        self.emit_expr(index)       # rax = index
        self.emit("    pop rcx")    # rcx = base pointer
        if is_i8:
            self.emit(f"    lea rcx, [rcx + rax]")
        else:
            self.emit(f"    lea rcx, [rcx + rax*8]")
        self.emit("    pop rax")
        if is_i8:
            self.emit(f"    mov [rcx], al")
        else:
            self.emit(f"    mov [rcx], rax")

    def emit_new(self, expr):
        """new StructName → HeapAlloc, returns &StructName in rax."""
        struct_name = expr.struct_name
        if struct_name not in self.structs:
            raise RuntimeError(f"Unknown struct in new: {struct_name}")
        size = self.structs[struct_name]["size"]
        self.emit_mov("rcx", "[_heap]")
        self.emit_mov("edx", "8")   # HEAP_ZERO_MEMORY
        self.emit_mov("r8d", size)
        self.emit(f"    sub rsp, 40")
        self.emit_call_inst("HeapAlloc")
        self.emit(f"    add rsp, 40")
        # rax = pointer, zero-initialized

    def emit_new_array(self, expr):
        """new T[] / new T[n] → dynamic array { data, len, cap }."""
        elem = expr.elem_type
        self._ensure_array_type(elem)
        cap_expr = expr.count
        tmp_header = self._alloc_temp()
        tmp_cap = self._alloc_temp()

        # Allocate header (24 bytes): data, len, cap.
        self.emit_mov("rcx", "[_heap]")
        self.emit_mov("edx", "8")
        self.emit_mov("r8d", "24")
        self.emit(f"    sub rsp, 40")
        self.emit_call_inst("HeapAlloc")
        self.emit(f"    add rsp, 40")
        self.emit_stack_store(tmp_header, "rax")
        if cap_expr is None:
            self.emit("    mov rax, 4")
        else:
            self.emit_expr(cap_expr)
        self.emit(f"    cmp rax, 1")
        self.emit(f"    jge {self.fresh_label()}_cap_ok")
        cap_ok = f"L{self.label_counter}_cap_ok"
        self.emit("    mov rax, 1")
        self.emit_label(cap_ok)
        self.emit_stack_store(tmp_cap, "rax")
        self.emit_stack_load("rcx", tmp_header)
        self.emit_mov("qword [rcx+8]", "0")
        self.emit_mov("[rcx+16]", "rax")
        el_size = 1 if elem == "i8" else 8
        self.emit_mov("r8", "rax")
        if el_size != 1:
            self.emit(f"    imul r8, {el_size}")
        self.emit_mov("rcx", "[_heap]")
        self.emit_mov("edx", "8")
        self.emit(f"    sub rsp, 40")
        self.emit_call_inst("HeapAlloc")
        self.emit(f"    add rsp, 40")
        self.emit_stack_load("rcx", tmp_header)
        self.emit_mov("[rcx]", "rax")
        self.emit_mov("rax", "rcx")

    def emit_push(self, args):
        if len(args) != 2:
            raise RuntimeError("push expects 2 arguments")
        arr_type = self._expr_type(args[0])
        if not (arr_type.startswith("&_arr_")):
            raise RuntimeError(f"push on non-array type '{arr_type}'")
        elem = arr_type[6:]
        el_size = 1 if elem == "i8" else 8
        tmp_arr = self._alloc_temp()
        tmp_val = self._alloc_temp()
        tmp_new_data = self._alloc_temp()
        self.emit_expr(args[0])
        self.emit_stack_store(tmp_arr, "rax")
        self.emit_expr(args[1])
        self.emit_stack_store(tmp_val, "rax")
        grow = self.fresh_label()
        store = self.fresh_label()
        done = self.fresh_label()
        copy_loop = self.fresh_label()
        copy_done = self.fresh_label()
        cap_nonzero = self.fresh_label()
        self.emit_stack_load("rax", tmp_arr)
        self.emit("    mov rcx, [rax+8]")   # len
        self.emit("    cmp rcx, [rax+16]")  # cap
        self.emit(f"    jge {grow}")
        self.emit_jmp(store)
        self.emit_label(grow)
        self.emit("    mov rdx, [rax+16]")
        self.emit("    test rdx, rdx")
        self.emit(f"    jnz {cap_nonzero}")
        self.emit("    mov rdx, 2")
        self.emit_label(cap_nonzero)
        self.emit("    add rdx, rdx")
        self.emit("    mov [rax+16], rdx")
        self.emit("    mov r8, rdx")
        if el_size != 1:
            self.emit(f"    imul r8, {el_size}")
        self.emit("    mov rcx, [_heap]")
        self.emit("    mov edx, 8")
        self.emit("    sub rsp, 40")
        self.emit_call_inst("HeapAlloc")
        self.emit("    add rsp, 40")
        self.emit_stack_store(tmp_new_data, "rax")
        self.emit_stack_load("rax", tmp_arr)
        self.emit("    mov r8, [rax]")      # old data
        self.emit("    mov r9, [rax+8]")    # len
        self.emit("    xor r10, r10")
        self.emit_label(copy_loop)
        self.emit("    cmp r10, r9")
        self.emit(f"    jge {copy_done}")
        if el_size == 1:
            self.emit("    mov r11b, [r8+r10]")
            self.emit_stack_load("rax", tmp_new_data)
            self.emit("    mov [rax+r10], r11b")
        else:
            self.emit("    mov r11, [r8+r10*8]")
            self.emit_stack_load("rax", tmp_new_data)
            self.emit("    mov [rax+r10*8], r11")
        self.emit("    inc r10")
        self.emit_jmp(copy_loop)
        self.emit_label(copy_done)
        self.emit_stack_load("rax", tmp_arr)
        self.emit_stack_load("rcx", tmp_new_data)
        self.emit("    mov [rax], rcx")
        self.emit_label(store)
        self.emit_stack_load("rax", tmp_arr)
        self.emit("    mov rcx, [rax]")     # data
        self.emit("    mov rdx, [rax+8]")   # len
        if el_size == 1:
            self.emit_stack_load("r8", tmp_val)
            self.emit("    mov [rcx+rdx], r8b")
        else:
            self.emit_stack_load("r8", tmp_val)
            self.emit("    mov [rcx+rdx*8], r8")
        self.emit("    inc qword [rax+8]")
        self.emit("    xor eax, eax")
        self.emit_label(done)

    def emit_subscript(self, expr):
        """base[index] → load value from array"""
        base = expr.base
        index = expr.index
        elem_type = self._expr_type(expr)  # type of the element being accessed
        # Evaluate base (pointer), then add index * size
        base_type = self._expr_type(base)
        self.emit_expr(base)        # rax = base pointer or array header
        if base_type.startswith("&_arr_"):
            self.emit("    mov rax, [rax]")
        self.emit("    push rax")
        self.emit_expr(index)       # rax = index
        self.emit("    pop rcx")    # rcx = base pointer
        if elem_type == "i8":
            self.emit(f"    movsx rax, byte [rcx + rax]")
        else:
            # i64, struct pointer, or anything else: 8-byte stride
            self.emit(f"    mov rax, [rcx + rax*8]")

    def _expr_type(self, expr):
        """Return the type string of an expression. Minimal but principled."""
        if isinstance(expr, LiteralNode):
            return "i64"
        if isinstance(expr, StringNode):
            return "&str"
        if isinstance(expr, VarNode):
            if sym := self._global_symbol(expr.name):
                return sym["type"]
            return self.local_types.get(expr.name, "i64")
        if isinstance(expr, CallNode):
            name = expr.name
            if self._syscall_symbol(name, expr.namespace):
                return "i64"
            # Builtins with known return types
            if name in ("itoa", "str_new", "read_file"):
                return "&str"
            if name in ("system", "write_file", "append_file"):
                return "i64"
            if name in ("putc", "putstr"):
                return "void"
            # User-defined function
            if name in self.funcs:
                return self.funcs[name]["ret_type"]
            return "i64"
        if isinstance(expr, FieldAccessNode):
            obj_type = self._expr_type(expr.object)
            field_name = expr.field
            # Strip & to get the struct name
            struct_name = obj_type[1:] if obj_type.startswith("&") else obj_type
            if struct_name in self.structs:
                for f in self.structs[struct_name]["fields"]:
                    if f["name"] == field_name:
                        return f["type"]
            return "i64"  # fallback
        if isinstance(expr, SubscriptNode):
            base_type = self._expr_type(expr.base)
            # base_type is like &T where T may be _arr_X, i8, i64, or &Struct
            if base_type.startswith("&"):
                inner = base_type[1:]  # strip one layer of pointer
                if inner.startswith("_arr_"):
                    elem = inner[5:]  # element type name
                    if elem in ("i64", "i8"):
                        return elem
                    return "&" + elem  # struct arrays return &Struct
                # Direct pointer: subscript returns the pointee type
                return inner
            return "i64"  # fallback
        if isinstance(expr, BinaryNode):
            if expr.op == "+" and self._expr_type(expr.left) == "&str" and self._expr_type(expr.right) == "&str":
                return "&str"
            return "i64"
        if isinstance(expr, NewNode):
            return "&" + expr.struct_name
        if isinstance(expr, NewArrayNode):
            return "&_arr_" + expr.elem_type
        return "i64"
