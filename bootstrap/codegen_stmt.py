"""Code generation mixin split from bootstrap.codegen."""

import dataclasses

from ast_nodes import *


class StmtEmitterMixin:
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
            elif isinstance(stmt, ForRangeNode):
                self.get_var_slot(stmt.name, "i64")
                self._pre_scan_block(stmt.body)
            elif isinstance(stmt, MatchNode):
                for case in stmt.cases:
                    for _, bind_name in case.bindings:
                        self.get_var_slot(bind_name, "i64")
                    self._pre_scan_block(case.body)

    def _pre_scan_temps(self, node):
        """Count temp slots needed. Covers: binary ops (1), putstr (1), struct new_array (3)."""
        if isinstance(node, ASTNode):
            count = 0
            if isinstance(node, BinaryNode):
                count = 1
            elif isinstance(node, CallNode):
                count = len(node.args)
                if node.name in ("putstr", "print", "println"):
                    count += 1  # string output saves &str across GetStdHandle
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
        elif isinstance(stmt, ForRangeNode):
            self.emit_for_range(stmt)
        elif isinstance(stmt, BreakNode):
            self.emit_break(stmt)
        elif isinstance(stmt, ContinueNode):
            self.emit_continue(stmt)
        elif isinstance(stmt, PanicNode):
            self.emit_panic(stmt)
        elif isinstance(stmt, AssertNode):
            self.emit_assert(stmt)
        elif isinstance(stmt, MatchNode):
            self.emit_match(stmt)
        elif isinstance(stmt, AssignNode):
            self.emit_assign(stmt)
        elif isinstance(stmt, FieldSetNode):
            self.emit_field_set(stmt)
        elif isinstance(stmt, SubscriptAssignNode):
            self.emit_subscript_assign(stmt)
        elif isinstance(stmt, AssignOpNode):
            self.emit_assign_op(stmt)
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
                if value.struct_name == "map[str]i64":
                    var_type = "map[str]i64"
                else:
                    var_type = f"&{value.struct_name}"
            elif isinstance(value, NewArrayNode):
                elem = self._internal_type(value.elem_type)
                if elem.startswith("&"):
                    elem = elem[1:]
                var_type = f"&_arr_{elem}"
            elif isinstance(value, StructInitNode):
                var_type = f"&{value.type_name}"
            elif isinstance(value, ArrayLiteralNode):
                var_type = f"&_arr_{self._internal_type(value.elem_type)}"
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
            self.emit_zero_value(var_type)
            if var_type == "i8":
                self.emit_stack_store(slot, "al")
            else:
                self.emit_stack_store(slot, "rax")
            return
        self.emit_expr(value)
        if var_type == "i8":
            self.emit_stack_store(slot, "al")
        else:
            self.emit_stack_store(slot, "rax")

    def emit_zero_value(self, typ):
        if typ == "&str":
            self.emit_mov("rcx", "0")
            self.emit_mov("rdx", "0")
            self.emit_call_inst("_str_alloc")
        elif typ.startswith("&_arr_"):
            elem = typ[len("&_arr_"):]
            self.emit_new_array(NewArrayNode(elem_type=elem, count=None))
        elif typ == "&_map_str_i64":
            self.emit_new_map()
        elif typ.startswith("&") and typ[1:] in self.structs:
            self.emit_new(NewNode(struct_name=typ[1:]))
        else:
            self.emit_mov("rax", "0")

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
        self.loop_stack.append((start_label, end_label))
        self.emit_label(start_label)
        self.emit_expr(stmt.cond)
        self.emit("    test rax, rax")
        self.emit(f"    jz {end_label}")
        self.emit_block(stmt.body)
        self.emit_jmp(start_label)
        self.emit_label(end_label)
        self.loop_stack.pop()

    def emit_for_range(self, stmt):
        slot = self.get_var_slot(stmt.name, "i64")
        self.local_types[stmt.name] = "i64"
        end_slot = self._alloc_temp()
        self.emit_expr(stmt.start)
        self.emit_stack_store(slot, "rax")
        self.emit_expr(stmt.end)
        self.emit_stack_store(end_slot, "rax")
        start_label = self.fresh_label()
        inc_label = self.fresh_label()
        end_label = self.fresh_label()
        self.loop_stack.append((inc_label, end_label))
        self.emit_label(start_label)
        self.emit_stack_load("rax", slot)
        self.emit_stack_load("rcx", end_slot)
        self.emit("    cmp rax, rcx")
        self.emit(f"    jge {end_label}")
        self.emit_block(stmt.body)
        self.emit_label(inc_label)
        self.emit_stack_load("rax", slot)
        self.emit("    inc rax")
        self.emit_stack_store(slot, "rax")
        self.emit_jmp(start_label)
        self.emit_label(end_label)
        self.loop_stack.pop()

    def emit_break(self, stmt):
        if not self.loop_stack:
            raise RuntimeError("break outside loop")
        self.emit_jmp(self.loop_stack[-1][1])

    def emit_continue(self, stmt):
        if not self.loop_stack:
            raise RuntimeError("continue outside loop")
        self.emit_jmp(self.loop_stack[-1][0])

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

    def emit_assign_op(self, stmt):
        # Lower AssignOp into equivalent plain assign with binary on the RHS
        binary = BinaryNode(op=stmt.op, left=stmt.target, right=stmt.value)
        target = stmt.target
        if isinstance(target, VarNode):
            self.emit_assign(AssignNode(name=target.name, value=binary))
        elif isinstance(target, FieldAccessNode):
            self.emit_field_set(FieldSetNode(object=target.object, field=target.field, value=binary))
        elif isinstance(target, SubscriptNode):
            self.emit_subscript_assign(SubscriptAssignNode(base=target.base, index=target.index, value=binary))
        else:
            raise RuntimeError(f"Unknown AssignOp target: {type(target).__name__}")

    # ── expressions ────────────────────────────────────────────────────

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
        base_type = self._expr_type(base)
        if base_type == "&_map_str_i64":
            self.emit_map_set(base, index, value)
            return
        # Compute element type from a synthetic subscript expression
        synth = SubscriptNode(base=base, index=index)
        elem_type = self._expr_type(synth)
        is_i8 = (elem_type == "i8")
        self.emit_expr(value)
        tmp_val = self._alloc_temp()
        self.emit_stack_store(tmp_val, "rax")
        self.emit_expr(base)
        tmp_base = self._alloc_temp()
        self.emit_stack_store(tmp_base, "rax")
        self.emit_expr(index)
        tmp_index = self._alloc_temp()
        self.emit_stack_store(tmp_index, "rax")
        self.emit_stack_load("rcx", tmp_base)
        self.emit_stack_load("rax", tmp_index)
        if base_type.startswith("&_arr_"):
            self.emit("    cmp rax, 0")
            self.emit(f"    jl {self.fresh_label()}_oob")
            oob = f"L{self.label_counter}_oob"
            self.emit("    cmp rax, [rcx+8]")
            self.emit(f"    jge {oob}")
            self.emit("    mov rcx, [rcx]")
        else:
            oob = None
        if is_i8:
            self.emit(f"    lea rcx, [rcx + rax]")
        else:
            self.emit(f"    lea rcx, [rcx + rax*8]")
        self.emit_stack_load("rax", tmp_val)
        if is_i8:
            self.emit(f"    mov [rcx], al")
        else:
            self.emit(f"    mov [rcx], rax")
        if oob:
            done = self.fresh_label()
            self.emit_jmp(done)
            self.emit_label(oob)
            self.emit_mov("ecx", "1")
            self.emit_call_inst("ExitProcess")
            self.emit_label(done)

    def emit_panic(self, stmt):
        self.emit_expr(StringNode(f"panic line {stmt.line}: "))
        self.emit_call(CallNode(name="putstr", args=[StringNode(f"panic line {stmt.line}: ")]))
        self.emit_call(CallNode(name="putstr", args=[stmt.message]))
        self.emit_call(CallNode(name="putc", args=[LiteralNode(10)]))
        self.emit_mov("ecx", "1")
        self.emit_call_inst("ExitProcess")

    def emit_assert(self, stmt):
        ok = self.fresh_label()
        self.emit_expr(stmt.cond)
        self.emit("    test rax, rax")
        self.emit(f"    jnz {ok}")
        msg = stmt.message if stmt.message is not None else StringNode("assertion failed")
        self.emit_call(CallNode(name="putstr", args=[StringNode(f"assert line {stmt.line}: ")]))
        self.emit_call(CallNode(name="putstr", args=[msg]))
        self.emit_call(CallNode(name="putc", args=[LiteralNode(10)]))
        self.emit_mov("ecx", "1")
        self.emit_call_inst("ExitProcess")
        self.emit_label(ok)

    def emit_match(self, stmt):
        tmp = self._alloc_temp()
        end = self.fresh_label()
        else_label = None
        self.emit_expr(stmt.expr)
        self.emit_stack_store(tmp, "rax")
        checks = []
        for case in stmt.cases:
            label = self.fresh_label()
            if case.is_else:
                else_label = label
            else:
                checks.append((case, label))
        miss = else_label or self.fresh_label()
        for case, label in checks:
            self.emit_stack_load("rax", tmp)
            if isinstance(case.pattern, FieldAccessNode) and isinstance(case.pattern.object, VarNode):
                adt = case.pattern.object.name
                tag = self.adts[adt][case.pattern.field]["tag"]
                self.emit("    cmp qword [rax], " + str(tag))
                self.emit(f"    je {label}")
            elif self._expr_type(stmt.expr) == "&str":
                self.emit_mov("rcx", "[rax]")
                left_data = self._alloc_temp()
                self.emit_stack_store(left_data, "rcx")
                self.emit_expr(case.pattern)
                self.emit_stack_load("rcx", left_data)
                self.emit_mov("rdx", "[rax]")
                self._call_with_shadow("lstrcmpA")
                self.emit("    cmp eax, 0")
                self.emit(f"    je {label}")
            else:
                self.emit_expr(case.pattern)
                self.emit_stack_load("rcx", tmp)
                self.emit("    cmp rcx, rax")
                self.emit(f"    je {label}")
        self.emit_jmp(miss)
        for case in stmt.cases:
            label = else_label if case.is_else else next(l for c, l in checks if c is case)
            self.emit_label(label)
            if not case.is_else and isinstance(case.pattern, FieldAccessNode) and case.bindings:
                adt = case.pattern.object.name
                payload = self.adts[adt][case.pattern.field]["payload"]
                self.emit_stack_load("rax", tmp)
                self.emit("    mov rax, [rax+8]")
                for field, bind in case.bindings:
                    for f in self.structs[payload]["fields"]:
                        if f["name"] == field:
                            slot = self.get_var_slot(bind, f["type"])
                            self.local_types[bind] = f["type"]
                            self.emit(f"    mov rcx, [rax+{f['offset']}]")
                            self.emit_stack_store(slot, "rcx")
                            break
            self.emit_block(case.body)
            self.emit_jmp(end)
        if else_label is None:
            self.emit_label(miss)
            self.emit_mov("ecx", "1")
            self.emit_call_inst("ExitProcess")
        self.emit_label(end)
