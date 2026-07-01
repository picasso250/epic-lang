"""Code generation mixin split from bootstrap.codegen."""

import dataclasses

from ast_nodes import *


class StringEmitterMixin:
    def _collect_strings_from_block(self, block):
        """Recursively collect strings from AST."""
        for stmt in block.stmts:
            if isinstance(stmt, IfNode):
                self._collect_strings_from_block(stmt.then_block)
                if stmt.else_block:
                    self._collect_strings_from_block(stmt.else_block)
            elif isinstance(stmt, WhileNode):
                self._collect_strings_from_block(stmt.body)
            elif isinstance(stmt, ForRangeNode):
                self._collect_strings_from_block(stmt.body)
            elif isinstance(stmt, PanicNode):
                self.get_string_label(f"panic line {stmt.line}: ")
            elif isinstance(stmt, AssertNode):
                self.get_string_label(f"assert line {stmt.line}: ")
            elif isinstance(stmt, MatchNode):
                for case in stmt.cases:
                    self._collect_strings_from_block(case.body)
            self._collect_strings(stmt)

    def _collect_strings(self, node):
        """Recursively find string literals and register them."""
        if isinstance(node, StringNode):
            self.get_string_label(node.value)
        if isinstance(node, FStringNode):
            if not node.parts:
                self.get_string_label("")
            for kind, value in node.parts:
                if kind == "text":
                    self.get_string_label(value)
                else:
                    self._collect_strings(value)
            return
        if isinstance(node, ASTNode):
            for f in dataclasses.fields(node):
                self._collect_strings(getattr(node, f.name))
        elif isinstance(node, list):
            for item in node:
                self._collect_strings(item)
        elif isinstance(node, tuple):
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

    def _collect_repr_static_strings(self):
        for text in ("", "true", "false", "}", ", ", ": ", "i64[]{", "u8[]{",
                     "str[]{", "bool[]{", "map[str]i64{"):
            self.get_string_label(text)
        for name, info in list(self.structs.items()):
            if name.startswith("_"):
                continue
            if name == "str":
                continue
            self.get_string_label(f"{name}{{")
            self.get_string_label(f"{name}[]{{")
            for i, field in enumerate(info["fields"]):
                prefix = "" if i == 0 else ", "
                self.get_string_label(f"{prefix}{field['name']}: ")
        for type_name, variants in self.adts.items():
            self.get_string_label(f"{type_name}[]{{")
            self.get_string_label(f"{type_name}.<invalid>{{}}")
            for variant_name, variant in variants.items():
                self.get_string_label(f"{type_name}.{variant_name}{{")
                payload = self.structs[variant["payload"]]
                for i, field in enumerate(payload["fields"]):
                    prefix = "" if i == 0 else ", "
                    self.get_string_label(f"{prefix}{field['name']}: ")

    # ── function definition ────────────────────────────────────────────

    def emit_write_str_expr(self, expr):
        self.emit_expr(expr)
        tmp = self._alloc_temp()
        self.emit_stack_store(tmp, "rax")
        self.emit_mov("ecx", "-11")
        self.emit_call_inst("GetStdHandle")
        self.emit_mov("rcx", "rax")
        self.emit_stack_load("rax", tmp)
        self.emit_mov("rdx", "[rax]")
        self.emit_mov("r8", "[rax+8]")
        self.emit_lea("r9", "[_written]")
        self._call_prep(1)
        self.emit_mov("qword [rsp+32]", "0")
        self.emit_call_inst("WriteFile")
        self._call_cleanup(1)

    def emit_literal_str(self, text):
        label = self.get_string_label(text)
        self.emit_lea("rcx", f"[{label}]")
        self.emit_mov("rdx", len(text))
        self.emit_call_inst("_str_alloc")

    def emit_append_rax_to_string_slot(self, out_slot):
        rhs = self._alloc_temp()
        self.emit_stack_store(rhs, "rax")
        self.emit_stack_load("rcx", out_slot)
        self.emit_stack_load("rdx", rhs)
        self._call_with_shadow("_str_cat")
        self.emit_stack_store(out_slot, "rax")

    def emit_append_literal_to_string_slot(self, out_slot, text):
        self.emit_literal_str(text)
        self.emit_append_rax_to_string_slot(out_slot)

    def _array_elem_display_type(self, elem):
        if elem == "i8":
            return "u8"
        if elem == "i64":
            return "i64"
        if elem == "str":
            return "str"
        return elem

    def _array_elem_value_type(self, elem):
        if elem == "i8":
            return "i8"
        if elem == "i64":
            return "i64"
        if elem == "bool":
            return "bool"
        if elem == "str":
            return "&str"
        return "&" + elem

    def _emit_bool_string_from_rax(self):
        true_label = self.fresh_label()
        done_label = self.fresh_label()
        self.emit("    test rax, rax")
        self.emit(f"    jnz {true_label}")
        self.emit_literal_str("false")
        self.emit_jmp(done_label)
        self.emit_label(true_label)
        self.emit_literal_str("true")
        self.emit_label(done_label)

    def emit_value_to_string_from_rax(self, typ, repr_context):
        if typ == "&str":
            if repr_context:
                self.emit_mov("rcx", "rax")
                self._call_with_shadow("_str_repr")
            return
        if typ == "bool":
            self._emit_bool_string_from_rax()
            return
        if typ in ("i64", "i8", "u64", "u8"):
            self.emit_mov("rcx", "rax")
            self.emit_call_inst("_itoa")
            return
        if typ == "&_map_str_i64":
            slot = self._alloc_temp()
            self.emit_stack_store(slot, "rax")
            self.emit_map_to_string(slot)
            return
        if typ.startswith("&_arr_"):
            slot = self._alloc_temp()
            self.emit_stack_store(slot, "rax")
            elem = typ[6:]
            if elem == "i8" and not repr_context:
                self.emit_stack_load("rax", slot)
                self.emit_mov("rcx", "[rax]")
                self.emit_mov("rdx", "[rax+8]")
                self.emit_call_inst("_str_alloc")
            else:
                self.emit_array_to_string(slot, elem)
            return
        if typ.startswith("&"):
            name = typ[1:]
            slot = self._alloc_temp()
            self.emit_stack_store(slot, "rax")
            if name in self.adts:
                self.emit_adt_to_string(slot, name)
                return
            if name in self.structs and not name.startswith("_"):
                self.emit_struct_to_string(slot, name)
                return
        raise RuntimeError(f"str does not support type {typ}")

    def emit_to_string(self, expr, repr_context=False):
        if isinstance(expr, BoolNode):
            self.emit_literal_str("true" if expr.value else "false")
            return
        typ = self._expr_type(expr)
        self.emit_expr(expr)
        self.emit_value_to_string_from_rax(typ, repr_context)

    def emit_struct_to_string(self, obj_slot, struct_name):
        info = self.structs[struct_name]
        self.emit_literal_str(f"{struct_name}{{")
        out_slot = self._alloc_temp()
        self.emit_stack_store(out_slot, "rax")
        for i, field in enumerate(info["fields"]):
            prefix = "" if i == 0 else ", "
            self.emit_append_literal_to_string_slot(out_slot, f"{prefix}{field['name']}: ")
            self.emit_stack_load("rcx", obj_slot)
            if field["type"] == "i8":
                self.emit(f"    movsx rax, byte [rcx+{field['offset']}]")
            else:
                self.emit(f"    mov rax, [rcx+{field['offset']}]")
            self.emit_value_to_string_from_rax(field["type"], repr_context=True)
            self.emit_append_rax_to_string_slot(out_slot)
        self.emit_append_literal_to_string_slot(out_slot, "}")
        self.emit_stack_load("rax", out_slot)

    def emit_adt_payload_to_string(self, header_slot, type_name, variant_name, info, done_label):
        payload_name = info["payload"]
        payload = self.structs[payload_name]
        self.emit_literal_str(f"{type_name}.{variant_name}{{")
        out_slot = self._alloc_temp()
        self.emit_stack_store(out_slot, "rax")
        self.emit_stack_load("rax", header_slot)
        self.emit_mov("rax", "[rax+8]")
        payload_slot = self._alloc_temp()
        self.emit_stack_store(payload_slot, "rax")
        for i, field in enumerate(payload["fields"]):
            prefix = "" if i == 0 else ", "
            self.emit_append_literal_to_string_slot(out_slot, f"{prefix}{field['name']}: ")
            self.emit_stack_load("rcx", payload_slot)
            if field["type"] == "i8":
                self.emit(f"    movsx rax, byte [rcx+{field['offset']}]")
            else:
                self.emit(f"    mov rax, [rcx+{field['offset']}]")
            self.emit_value_to_string_from_rax(field["type"], repr_context=True)
            self.emit_append_rax_to_string_slot(out_slot)
        self.emit_append_literal_to_string_slot(out_slot, "}")
        self.emit_stack_load("rax", out_slot)
        self.emit_jmp(done_label)

    def emit_adt_to_string(self, header_slot, type_name):
        done = self.fresh_label()
        for variant_name, info in self.adts[type_name].items():
            next_label = self.fresh_label()
            self.emit_stack_load("rax", header_slot)
            self.emit_mov("rax", "[rax]")
            self.emit(f"    cmp rax, {info['tag']}")
            self.emit(f"    jne {next_label}")
            self.emit_adt_payload_to_string(header_slot, type_name, variant_name, info, done)
            self.emit_label(next_label)
        self.emit_literal_str(f"{type_name}.<invalid>{{}}")
        self.emit_label(done)

    def emit_array_to_string(self, arr_slot, elem):
        display = self._array_elem_display_type(elem)
        elem_type = self._array_elem_value_type(elem)
        self.emit_literal_str(f"{display}[]{{")
        out_slot = self._alloc_temp()
        i_slot = self._alloc_temp()
        self.emit_stack_store(out_slot, "rax")
        self.emit_mov("rax", "0")
        self.emit_stack_store(i_slot, "rax")
        loop = self.fresh_label()
        done = self.fresh_label()
        no_sep = self.fresh_label()
        self.emit_label(loop)
        self.emit_stack_load("rax", i_slot)
        self.emit_stack_load("rcx", arr_slot)
        self.emit("    cmp rax, [rcx+8]")
        self.emit(f"    jge {done}")
        self.emit("    test rax, rax")
        self.emit(f"    jz {no_sep}")
        self.emit_append_literal_to_string_slot(out_slot, ", ")
        self.emit_label(no_sep)
        self.emit_stack_load("rax", i_slot)
        self.emit_stack_load("rcx", arr_slot)
        self.emit("    mov rdx, [rcx]")
        if elem == "i8":
            self.emit("    movsx rax, byte [rdx+rax]")
        else:
            self.emit("    mov rax, [rdx+rax*8]")
        self.emit_value_to_string_from_rax(elem_type, repr_context=True)
        self.emit_append_rax_to_string_slot(out_slot)
        self.emit_stack_load("rax", i_slot)
        self.emit("    inc rax")
        self.emit_stack_store(i_slot, "rax")
        self.emit_jmp(loop)
        self.emit_label(done)
        self.emit_append_literal_to_string_slot(out_slot, "}")
        self.emit_stack_load("rax", out_slot)

    def emit_map_to_string(self, map_slot):
        # TODO: map repr currently follows internal iteration order. Stabilize
        # this after hash/layout semantics are settled.
        self.emit_literal_str("map[str]i64{")
        out_slot = self._alloc_temp()
        i_slot = self._alloc_temp()
        self.emit_stack_store(out_slot, "rax")
        self.emit_mov("rax", "0")
        self.emit_stack_store(i_slot, "rax")
        loop = self.fresh_label()
        done = self.fresh_label()
        no_sep = self.fresh_label()
        self.emit_label(loop)
        self.emit_stack_load("rax", i_slot)
        self.emit_stack_load("rcx", map_slot)
        self.emit("    cmp rax, [rcx+8]")
        self.emit(f"    jge {done}")
        self.emit("    test rax, rax")
        self.emit(f"    jz {no_sep}")
        self.emit_append_literal_to_string_slot(out_slot, ", ")
        self.emit_label(no_sep)
        self.emit_stack_load("rax", i_slot)
        self.emit_stack_load("rcx", map_slot)
        self.emit("    mov rdx, [rcx]")
        self.emit("    imul rax, 24")
        self.emit("    lea rdx, [rdx+rax]")
        entry_slot = self._alloc_temp()
        self.emit_stack_store(entry_slot, "rdx")
        self.emit("    mov rax, [rdx]")
        self.emit_value_to_string_from_rax("&str", repr_context=True)
        self.emit_append_rax_to_string_slot(out_slot)
        self.emit_append_literal_to_string_slot(out_slot, ": ")
        self.emit_stack_load("rdx", entry_slot)
        self.emit("    mov rax, [rdx+8]")
        self.emit_value_to_string_from_rax("i64", repr_context=True)
        self.emit_append_rax_to_string_slot(out_slot)
        self.emit_stack_load("rax", i_slot)
        self.emit("    inc rax")
        self.emit_stack_store(i_slot, "rax")
        self.emit_jmp(loop)
        self.emit_label(done)
        self.emit_append_literal_to_string_slot(out_slot, "}")
        self.emit_stack_load("rax", out_slot)

    def emit_print(self, args, newline):
        if len(args) > 1:
            raise RuntimeError("print and println take at most one argument")
        if args:
            self.emit_to_string(args[0], repr_context=False)
            tmp = self._alloc_temp()
            self.emit_stack_store(tmp, "rax")
            self.emit_stack_load("rax", tmp)
            self.emit_write_str_expr_raw_rax()
        if newline:
            self.emit_call(CallNode(name="putc", args=[LiteralNode(10)]))

    def emit_write_str_expr_raw_rax(self):
        tmp = self._alloc_temp()
        self.emit_stack_store(tmp, "rax")
        self.emit_mov("ecx", "-11")
        self.emit_call_inst("GetStdHandle")
        self.emit_mov("rcx", "rax")
        self.emit_stack_load("rax", tmp)
        self.emit_mov("rdx", "[rax]")
        self.emit_mov("r8", "[rax+8]")
        self.emit_lea("r9", "[_written]")
        self._call_prep(1)
        self.emit_mov("qword [rsp+32]", "0")
        self.emit_call_inst("WriteFile")
        self._call_cleanup(1)

    def _fstring_expr(self, expr):
        nodes = []
        for kind, value in expr.parts:
            if kind == "text":
                if value:
                    nodes.append(StringNode(value))
                continue
            nodes.append(CallNode(name="str", args=[value]))
        if not nodes:
            return StringNode("")
        out = nodes[0]
        for node in nodes[1:]:
            out = BinaryNode(op="+", left=out, right=node)
        return out
