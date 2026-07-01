"""Code generation mixin split from bootstrap.codegen."""

from ast_nodes import *


class ExprEmitterMixin:
    def emit_expr(self, expr):
        if isinstance(expr, (LiteralNode, CharNode, BoolNode)):
            self.emit_mov("rax", expr.value)
        elif isinstance(expr, StringNode):
            label = self.get_string_label(expr.value)
            strlen = len(expr.value)
            self.emit_lea("rcx", f"[{label}]")
            self.emit_mov("rdx", strlen)
            self.emit_call_inst("_str_alloc")
        elif isinstance(expr, FStringNode):
            self.emit_expr(self._fstring_expr(expr))
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
        elif isinstance(expr, SliceNode):
            self.emit_slice(expr)
        elif isinstance(expr, BinaryNode):
            self.emit_binary(expr)
        elif isinstance(expr, UnaryNode):
            self.emit_unary(expr)
        elif isinstance(expr, FieldAccessNode):
            self.emit_field_access(expr)
        elif isinstance(expr, NewNode):
            self.emit_new(expr)
        elif isinstance(expr, NewArrayNode):
            self.emit_new_array(expr)
        elif isinstance(expr, StructInitNode):
            self.emit_struct_init(expr)
        elif isinstance(expr, ArrayLiteralNode):
            self.emit_array_literal(expr)
        else:
            raise RuntimeError(f"Unknown expr type: {type(expr).__name__}")

    def emit_call(self, expr):
        name = expr.name
        args = expr.args

        if symbol := self._syscall_symbol(name, expr.namespace):
            self._emit_syscall(symbol, args)
            return

        if name in ("i64", "u64", "u8", "bool"):
            self.emit_expr(args[0])
            if name == "u8":
                self.emit("    and rax, 255")
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
                self.emit_write_str_expr(args[0])
            elif name == "print":
                self.emit_print(args, newline=False)
            elif name == "println":
                self.emit_print(args, newline=True)
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
            elif name == "str":
                self.emit_to_string(args[0], repr_context=False)
            elif name == "str_new":
                # str(bytes: &i8, len: i64) → &str (deep-copy via _str_alloc)
                slots = self._spill_args(args)
                self.emit_stack_load("rcx", slots[0])
                self.emit_stack_load("rdx", slots[1])
                self.emit_call_inst("_str_alloc")
            elif name == "bytes":
                self.emit_expr(args[0])
                self.emit_mov("rcx", "rax")
                self.emit_call_inst("_bytes")
            elif name == "len":
                self.emit_expr(args[0])
                self.emit_mov("rax", "[rax+8]")
            elif name == "cap":
                self.emit_expr(args[0])
                self.emit_mov("rax", "[rax+16]")
            elif name == "str_starts_with":
                slots = self._spill_args(args)
                self.emit_stack_load("rcx", slots[0])
                self.emit_stack_load("rdx", slots[1])
                self._call_with_shadow("_str_starts_with")
            elif name == "str_find":
                slots = self._spill_args(args)
                self.emit_stack_load("rcx", slots[0])
                self.emit_stack_load("rdx", slots[1])
                self._call_with_shadow("_str_find")
            elif name == "str_trim":
                self.emit_expr(args[0])
                self.emit_mov("rcx", "rax")
                self._call_with_shadow("_str_trim")
            elif name == "str_slice":
                slots = self._spill_args(args)
                self.emit_stack_load("rcx", slots[0])
                self.emit_stack_load("rdx", slots[1])
                self.emit_stack_load("r8", slots[2])
                self._call_with_shadow("_str_slice")
            elif name == "str_replace_char":
                slots = self._spill_args(args)
                self.emit_stack_load("rcx", slots[0])
                self.emit_stack_load("rdx", slots[1])
                self.emit_stack_load("r8", slots[2])
                self._call_with_shadow("_str_replace_char")
            elif name == "push":
                self.emit_push(args)
            elif name == "extend":
                self.emit_extend(args)
            elif name == "map_has":
                self.emit_map_lookup(args[0], args[1], want_has=True)
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
        elif op == "&":
            self.emit("    and rax, rcx")
        elif op == "|":
            self.emit("    or rax, rcx")
        elif op == "^":
            self.emit("    xor rax, rcx")
        elif op == "<<":
            self.emit("    mov cl, cl")
            self.emit("    shl rax, cl")
        elif op == ">>":
            self.emit("    mov cl, cl")
            self.emit("    sar rax, cl")
        elif op == ">>>":
            self.emit("    mov cl, cl")
            self.emit("    shr rax, cl")
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

    def emit_unary(self, expr):
        self.emit_expr(expr.expr)
        if expr.op == "!":
            self.emit("    test rax, rax")
            self.emit("    sete al")
            self.emit("    movzx eax, al")
        elif expr.op == "-":
            self.emit("    neg rax")
            self.emit("    jo _epic_trap")
        elif expr.op == "~":
            self.emit("    not rax")
        else:
            raise RuntimeError(f"Unknown unary op: {expr.op}")

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
            self.emit_expr(obj)
            self._emit_field_read_from_rax(obj, field_name)

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

    def emit_new(self, expr):
        """new StructName → HeapAlloc, returns &StructName in rax."""
        struct_name = expr.struct_name
        if struct_name == "map[str]i64":
            self.emit_new_map()
            return
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
        elem = self._internal_type(expr.elem_type)
        if elem.startswith("&"):
            elem = elem[1:]
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

    def emit_extend(self, args):
        if len(args) != 2:
            raise RuntimeError("extend expects 2 arguments")
        arr_type = self._expr_type(args[0])
        if arr_type == "&_arr_i8":
            slots = self._spill_args(args)
            self.emit_stack_load("rcx", slots[0])
            self.emit_stack_load("rdx", slots[1])
            self.emit_call_inst("_extend_i8")
            self.emit("    xor eax, eax")
            return
        tmp_src = self._alloc_temp()
        tmp_src_len = self._alloc_temp()
        tmp_i = self._alloc_temp()
        loop = self.fresh_label()
        done = self.fresh_label()
        self.emit_expr(args[1])
        self.emit_stack_store(tmp_src, "rax")
        self.emit_mov("rax", "[rax+8]")
        self.emit_stack_store(tmp_src_len, "rax")
        self.emit_mov("rax", "0")
        self.emit_stack_store(tmp_i, "rax")
        self.emit_label(loop)
        self.emit_stack_load("rax", tmp_i)
        self.emit_stack_load("rcx", tmp_src_len)
        self.emit("    cmp rax, rcx")
        self.emit(f"    jge {done}")
        self.local_offset[f"__extend_i_{tmp_i}"] = tmp_i
        self.local_types[f"__extend_i_{tmp_i}"] = "i64"
        self.emit_push([args[0], SubscriptNode(base=args[1], index=VarNode(f"__extend_i_{tmp_i}"))])
        self.emit_stack_load("rax", tmp_i)
        self.emit("    inc rax")
        self.emit_stack_store(tmp_i, "rax")
        self.emit_jmp(loop)
        self.emit_label(done)
        self.emit("    xor eax, eax")

    def emit_struct_init(self, expr):
        if expr.variant:
            self.emit_adt_init(expr)
            return
        if expr.type_name in self.adts:
            raise RuntimeError(f"ADT construction must name a variant: {expr.type_name}")
        self.emit_new(NewNode(struct_name=expr.type_name))
        tmp = self._alloc_temp()
        self.emit_stack_store(tmp, "rax")
        for name, value in expr.fields:
            self.emit_expr(value)
            self.emit("    push rax")
            self.emit_stack_load("rax", tmp)
            self.emit("    pop rcx")
            info = self.structs.get(expr.type_name)
            if info is None:
                raise RuntimeError(f"Unknown struct in initializer: {expr.type_name}")
            found = False
            for f in info["fields"]:
                if f["name"] == name:
                    found = True
                    if f["type"] == "i8":
                        self.emit(f"    mov [rax+{f['offset']}], cl")
                    else:
                        self.emit(f"    mov [rax+{f['offset']}], rcx")
                    break
            if not found:
                raise RuntimeError(f"Struct '{expr.type_name}' has no field '{name}'")
        self.emit_stack_load("rax", tmp)

    def emit_adt_init(self, expr):
        variants = self.adts.get(expr.type_name)
        if not variants or expr.variant not in variants:
            raise RuntimeError(f"Unknown ADT variant: {expr.type_name}.{expr.variant}")
        info = variants[expr.variant]
        tmp_header = self._alloc_temp()
        tmp_payload = self._alloc_temp()
        self.emit_mov("rcx", "[_heap]")
        self.emit_mov("edx", "8")
        self.emit_mov("r8d", "16")
        self.emit("    sub rsp, 40")
        self.emit_call_inst("HeapAlloc")
        self.emit("    add rsp, 40")
        self.emit_stack_store(tmp_header, "rax")
        self.emit_mov(f"qword [rax]", str(info["tag"]))
        payload_name = info["payload"]
        size = self.structs[payload_name]["size"]
        self.emit_mov("rcx", "[_heap]")
        self.emit_mov("edx", "8")
        self.emit_mov("r8d", str(max(size, 1)))
        self.emit("    sub rsp, 40")
        self.emit_call_inst("HeapAlloc")
        self.emit("    add rsp, 40")
        self.emit_stack_store(tmp_payload, "rax")
        self.emit_stack_load("rcx", tmp_header)
        self.emit_mov("[rcx+8]", "rax")
        for name, value in expr.fields:
            self.emit_expr(value)
            self.emit("    push rax")
            self.emit_stack_load("rax", tmp_payload)
            self.emit("    pop rcx")
            for f in self.structs[payload_name]["fields"]:
                if f["name"] == name:
                    self.emit(f"    mov [rax+{f['offset']}], rcx")
                    break
        self.emit_stack_load("rax", tmp_header)

    def emit_array_literal(self, expr):
        elem = self._internal_type(expr.elem_type)
        if elem.startswith("&"):
            elem = elem[1:]
        self.emit_new_array(NewArrayNode(elem_type=elem, count=LiteralNode(len(expr.values))))
        tmp = self._alloc_temp()
        self.emit_stack_store(tmp, "rax")
        self.emit_mov("rcx", "rax")
        self.emit_mov("qword [rcx+8]", str(len(expr.values)))
        for i, value in enumerate(expr.values):
            self.emit_expr(value)
            self.emit_stack_load("rcx", tmp)
            self.emit("    mov rcx, [rcx]")
            if elem == "i8":
                self.emit(f"    mov [rcx+{i}], al")
            else:
                self.emit(f"    mov [rcx+{i * 8}], rax")
        self.emit_stack_load("rax", tmp)

    def emit_slice(self, expr):
        base_type = self._expr_type(expr.base)
        start = expr.start if expr.start is not None else LiteralNode(0)
        if expr.end is None:
            end = CallNode(name="len", args=[expr.base])
        else:
            end = expr.end
        if base_type == "&str":
            slots = self._spill_args([expr.base, start, end])
            self.emit_stack_load("rcx", slots[0])
            self.emit_stack_load("rdx", slots[1])
            self.emit_stack_load("r8", slots[2])
            self._call_with_shadow("_str_slice")
            return
        # Array slice: allocate result and push selected elements.
        elem_type = self._expr_type(SubscriptNode(expr.base, LiteralNode(0)))
        elem = "i8" if elem_type == "i8" else elem_type.lstrip("&")
        tmp_out = self._alloc_temp()
        tmp_i = self._alloc_temp()
        loop = self.fresh_label()
        done = self.fresh_label()
        self.emit_new_array(NewArrayNode(elem_type=elem, count=LiteralNode(1)))
        self.emit_stack_store(tmp_out, "rax")
        self.emit_expr(start)
        self.emit_stack_store(tmp_i, "rax")
        self.emit_label(loop)
        self.emit_stack_load("rax", tmp_i)
        self.emit_expr(end)
        self.emit("    cmp [rbp%+d], rax" % tmp_i)
        self.emit(f"    jge {done}")
        self.local_offset[f"__slice_out_{tmp_out}"] = tmp_out
        self.local_types[f"__slice_out_{tmp_out}"] = f"&_arr_{elem}"
        self.local_offset[f"__slice_i_{tmp_i}"] = tmp_i
        self.local_types[f"__slice_i_{tmp_i}"] = "i64"
        self.emit_push([VarNode(f"__slice_out_{tmp_out}"), SubscriptNode(expr.base, VarNode(f"__slice_i_{tmp_i}"))])
        self.emit_stack_load("rax", tmp_i)
        self.emit("    inc rax")
        self.emit_stack_store(tmp_i, "rax")
        self.emit_jmp(loop)
        self.emit_label(done)
        self.emit_stack_load("rax", tmp_out)

    def emit_new_map(self):
        self._ensure_map_i64_type()
        tmp = self._alloc_temp()
        self.emit_mov("rcx", "[_heap]")
        self.emit_mov("edx", "8")
        self.emit_mov("r8d", "24")
        self.emit("    sub rsp, 40")
        self.emit_call_inst("HeapAlloc")
        self.emit("    add rsp, 40")
        self.emit_stack_store(tmp, "rax")
        self.emit_mov("rcx", "[_heap]")
        self.emit_mov("edx", "8")
        self.emit_mov("r8d", str(8 * 24))
        self.emit("    sub rsp, 40")
        self.emit_call_inst("HeapAlloc")
        self.emit("    add rsp, 40")
        self.emit_stack_load("rcx", tmp)
        self.emit_mov("[rcx]", "rax")
        self.emit_mov("qword [rcx+8]", "0")
        self.emit_mov("qword [rcx+16]", "8")
        self.emit_mov("rax", "rcx")

    def emit_map_find(self, map_expr, key_expr, found_label, miss_label, entry_out_slot=None):
        tmp_map = self._alloc_temp()
        tmp_key = self._alloc_temp()
        tmp_i = self._alloc_temp()
        self.emit_expr(map_expr)
        self.emit_stack_store(tmp_map, "rax")
        self.emit_expr(key_expr)
        self.emit_stack_store(tmp_key, "rax")
        self.emit_mov("rax", "0")
        self.emit_stack_store(tmp_i, "rax")
        loop = self.fresh_label()
        self.emit_label(loop)
        self.emit_stack_load("rax", tmp_i)
        self.emit_stack_load("rcx", tmp_map)
        self.emit("    cmp rax, [rcx+8]")
        self.emit(f"    jge {miss_label}")
        self.emit("    mov rdx, [rcx]")
        self.emit("    imul rax, 24")
        self.emit("    lea rdx, [rdx+rax]")
        if entry_out_slot is not None:
            self.emit_stack_store(entry_out_slot, "rdx")
        self.emit("    mov rcx, [rdx]")
        self.emit("    mov rcx, [rcx]")
        self.emit_stack_load("rax", tmp_key)
        self.emit("    mov rdx, [rax]")
        self._call_with_shadow("lstrcmpA")
        self.emit("    cmp eax, 0")
        self.emit(f"    je {found_label}")
        self.emit_stack_load("rax", tmp_i)
        self.emit("    inc rax")
        self.emit_stack_store(tmp_i, "rax")
        self.emit_jmp(loop)

    def emit_map_lookup(self, map_expr, key_expr, want_has=False):
        found = self.fresh_label()
        miss = self.fresh_label()
        done = self.fresh_label()
        entry = self._alloc_temp()
        self.emit_map_find(map_expr, key_expr, found, miss, entry)
        self.emit_label(found)
        if want_has:
            self.emit_mov("rax", "1")
        else:
            self.emit_stack_load("rcx", entry)
            self.emit_mov("rax", "[rcx+8]")
        self.emit_jmp(done)
        self.emit_label(miss)
        self.emit_mov("rax", "0")
        self.emit_label(done)

    def emit_map_set(self, map_expr, key_expr, value_expr):
        found = self.fresh_label()
        miss = self.fresh_label()
        done = self.fresh_label()
        entry = self._alloc_temp()
        tmp_val = self._alloc_temp()
        self.emit_expr(value_expr)
        self.emit_stack_store(tmp_val, "rax")
        self.emit_map_find(map_expr, key_expr, found, miss, entry)
        self.emit_label(found)
        self.emit_stack_load("rcx", entry)
        self.emit_stack_load("rax", tmp_val)
        self.emit_mov("[rcx+8]", "rax")
        self.emit_jmp(done)
        self.emit_label(miss)
        tmp_map = self._alloc_temp()
        tmp_key = self._alloc_temp()
        self.emit_expr(map_expr)
        self.emit_stack_store(tmp_map, "rax")
        self.emit_expr(key_expr)
        self.emit_stack_store(tmp_key, "rax")
        self.emit_stack_load("rcx", tmp_map)
        self.emit("    mov rax, [rcx+8]")
        self.emit("    cmp rax, [rcx+16]")
        self.emit(f"    jge {done}")
        self.emit("    mov rdx, [rcx]")
        self.emit("    imul rax, 24")
        self.emit("    lea rdx, [rdx+rax]")
        self.emit_stack_load("rax", tmp_key)
        self.emit_mov("[rdx]", "rax")
        self.emit_stack_load("rax", tmp_val)
        self.emit_mov("[rdx+8]", "rax")
        self.emit_mov("qword [rdx+16]", "1")
        self.emit("    inc qword [rcx+8]")
        self.emit_label(done)
        self.emit("    xor eax, eax")

    def emit_subscript(self, expr):
        """base[index] → load value from array"""
        base = expr.base
        index = expr.index
        elem_type = self._expr_type(expr)  # type of the element being accessed
        base_type = self._expr_type(base)
        if base_type == "&_map_str_i64":
            self.emit_map_lookup(base, index, want_has=False)
            return
        self.emit_expr(base)
        tmp_base = self._alloc_temp()
        self.emit_stack_store(tmp_base, "rax")
        self.emit_expr(index)
        tmp_index = self._alloc_temp()
        self.emit_stack_store(tmp_index, "rax")
        self.emit_stack_load("rcx", tmp_base)
        self.emit_stack_load("rax", tmp_index)
        if base_type == "&str" or base_type.startswith("&_arr_"):
            self.emit("    cmp rax, 0")
            self.emit(f"    jl {self.fresh_label()}_oob")
            oob = f"L{self.label_counter}_oob"
            self.emit("    cmp rax, [rcx+8]")
            self.emit(f"    jge {oob}")
            self.emit("    mov rcx, [rcx]")
        else:
            oob = None
        if elem_type == "i8":
            self.emit(f"    movsx rax, byte [rcx + rax]")
        else:
            # i64, struct pointer, or anything else: 8-byte stride
            self.emit(f"    mov rax, [rcx + rax*8]")
        if oob:
            done = self.fresh_label()
            self.emit_jmp(done)
            self.emit_label(oob)
            self.emit_mov("ecx", "1")
            self.emit_call_inst("ExitProcess")
            self.emit_label(done)

    def _expr_type(self, expr):
        """Return the type string of an expression. Minimal but principled."""
        if isinstance(expr, (LiteralNode, CharNode)):
            return "i64"
        if isinstance(expr, BoolNode):
            return "bool"
        if isinstance(expr, StringNode):
            return "&str"
        if isinstance(expr, FStringNode):
            return "&str"
        if isinstance(expr, VarNode):
            if sym := self._global_symbol(expr.name):
                return sym["type"]
            return self.local_types.get(expr.name, "i64")
        if isinstance(expr, CallNode):
            name = expr.name
            if name in ("i64", "u64", "u8", "bool"):
                if name == "u8":
                    return "i8"
                if name == "bool":
                    return "bool"
                return "i64"
            if self._syscall_symbol(name, expr.namespace):
                return "i64"
            # Builtins with known return types
            if name in ("itoa", "str", "str_new", "str_slice", "str_replace_char", "str_trim"):
                return "&str"
            if name in ("bytes", "read_file"):
                return "&_arr_i8"
            if name in ("system", "write_file", "len", "cap", "str_starts_with", "str_find", "map_has"):
                return "i64"
            if name in ("putc", "putstr", "print", "println", "extend"):
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
            if base_type == "&_map_str_i64":
                return "i64"
            # base_type is like &T where T may be _arr_X, i8, i64, or &Struct
            if base_type.startswith("&"):
                inner = base_type[1:]  # strip one layer of pointer
                if inner.startswith("_arr_"):
                    elem = inner[5:]  # element type name
                    if elem in ("i64", "i8", "bool"):
                        return elem
                    return "&" + elem  # struct arrays return &Struct
                # Direct pointer: subscript returns the pointee type
                return inner
            return "i64"  # fallback
        if isinstance(expr, BinaryNode):
            if expr.op == "+" and self._expr_type(expr.left) == "&str" and self._expr_type(expr.right) == "&str":
                return "&str"
            if expr.op in ("==", "!=", "<", ">", "<=", ">=", "&&", "||"):
                return "bool"
            return "i64"
        if isinstance(expr, UnaryNode):
            if expr.op == "!":
                return "bool"
            return "i64"
        if isinstance(expr, SliceNode):
            base_type = self._expr_type(expr.base)
            if base_type == "&str":
                return "&str"
            return base_type
        if isinstance(expr, NewNode):
            if expr.struct_name == "map[str]i64":
                return "&_map_str_i64"
            return "&" + expr.struct_name
        if isinstance(expr, NewArrayNode):
            elem = self._internal_type(expr.elem_type)
            if elem.startswith("&"):
                elem = elem[1:]
            return "&_arr_" + elem
        if isinstance(expr, StructInitNode):
            return "&" + expr.type_name
        if isinstance(expr, ArrayLiteralNode):
            elem = self._internal_type(expr.elem_type)
            if elem.startswith("&"):
                elem = elem[1:]
            return "&_arr_" + elem
        return "i64"
