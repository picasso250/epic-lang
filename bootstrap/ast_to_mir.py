"""AST -> Epic AST-to-MIR for the initial machine-backend path."""

from dataclasses import dataclass

import epic_types as et
from sema import assert_typed_program
from ast_nodes import *
from mir_builder import MirFunctionBuilder
from mir import (
    BOOL,
    I8,
    I64,
    VOID,
    ConstBoolOperand,
    ConstIntOperand,
    ConstNullOperand,
    MirBlock,
    MirExtern,
    MirField,
    MirGlobal,
    MirInst,
    MirParam,
    MirProgram,
    MirSignature,
    MirStruct,
    Ret,
    SymbolOperand,
    ValueOperand,
    ptr,
    struct as mir_struct,
    validate,
)


class MirCodegenError(RuntimeError):
    pass


@dataclass
class ValueFlow:
    value: object
    block: MirBlock


@dataclass
class BlockFlow:
    reachable: bool
    block: object = None


WINAPI_IMPORTS = [
    ("kernel32", "ExitProcess", [I64], VOID),
    ("kernel32", "Sleep", [I64], VOID),
    ("kernel32", "GetTickCount64", [], I64),
    ("kernel32", "lstrlenA", [I64], I64),
    ("kernel32", "lstrcmpA", [I64, I64], I64),
    ("kernel32", "GetStdHandle", [I64], I64),
    ("kernel32", "GetProcessHeap", [], I64),
    ("kernel32", "HeapAlloc", [I64, I64, I64], I64),
    ("kernel32", "CreateFileA", [I64, I64, I64, I64, I64, I64, I64], I64),
    ("kernel32", "GetFileSize", [I64, I64], I64),
    ("kernel32", "ReadFile", [I64, I64, I64, I64, I64], I64),
    ("kernel32", "WriteFile", [I64, I64, I64, I64, I64], I64),
    ("kernel32", "CloseHandle", [I64], I64),
    ("kernel32", "GetCommandLineA", [], I64),
    ("user32", "MessageBoxA", [I64, I64, I64, I64], I64),
]


class MirCodegen(MirFunctionBuilder):
    def __init__(self):
        super().__init__(numbered_blocks=True)
        self.program = MirProgram()
        self.func_sigs = {}
        self.globals = {}
        self.local_scopes = []
        self.local_type_scopes = []
        self.strings = {}
        self.string_counter = 0
        self.structs = {}
        self.union_defs = {}
        self.union_tags = {}
        self.loop_stack = []

    def emit_program(self, ast):
        self._compute_struct_layouts(ast)
        self.func_sigs = {
            fn.name: MirSignature([self._type(p.resolved_type) for p in fn.params], self._type(fn.resolved_type))
            for fn in ast.funcs
        }
        for _dll, name, params, ret in WINAPI_IMPORTS:
            self.program.externs.append(MirExtern(name, MirSignature(params, ret)))
        if "__ep_str_from_i64" not in self.func_sigs:
            self.program.externs.append(MirExtern("__ep_str_from_i64", MirSignature([I64], ptr())))
        if "__ep_str_from_u64" not in self.func_sigs:
            self.program.externs.append(MirExtern("__ep_str_from_u64", MirSignature([I64], ptr())))
        if "__ep_str_from_bool" not in self.func_sigs:
            self.program.externs.append(MirExtern("__ep_str_from_bool", MirSignature([BOOL], ptr())))
        self.program.externs.append(MirExtern("__ep_str_cat", MirSignature([ptr(), ptr()], ptr())))
        if "__ep_str_eq" not in self.func_sigs:
            self.program.externs.append(MirExtern("__ep_str_eq", MirSignature([ptr(), ptr()], BOOL)))
        if "__ep_str_slice" not in self.func_sigs:
            self.program.externs.append(MirExtern("__ep_str_slice", MirSignature([ptr(), I64, I64], ptr())))
        self.program.externs.append(MirExtern("__ep_cstr", MirSignature([ptr(), I64], I64)))
        self.program.externs.append(MirExtern("__ep_read_file", MirSignature([ptr(), I64], ptr())))
        self.program.externs.append(MirExtern("__ep_write_file", MirSignature([ptr(), ptr(), I64], I64)))
        self.program.externs.append(MirExtern("__ep_slice_u8_alloc", MirSignature([I64, I64], ptr())))
        self.program.externs.append(MirExtern("__ep_slice_u8_get", MirSignature([ptr(), I64], I64)))
        self.program.externs.append(MirExtern("__ep_slice_u8_set", MirSignature([ptr(), I64, I64], VOID)))
        self.program.externs.append(MirExtern("__ep_slice_u8_push", MirSignature([ptr(), I64], VOID)))
        self.program.externs.append(MirExtern("__ep_slice_u8_pop", MirSignature([ptr()], I64)))
        self.program.externs.append(MirExtern("__ep_slice_u8_slice", MirSignature([ptr(), I64, I64], ptr())))
        self.program.externs.append(MirExtern("__ep_slice_i64_new", MirSignature([I64], ptr())))
        self.program.externs.append(MirExtern("__ep_slice_i64_get", MirSignature([ptr(), I64], I64)))
        self.program.externs.append(MirExtern("__ep_slice_i64_set", MirSignature([ptr(), I64, I64], VOID)))
        self.program.externs.append(MirExtern("__ep_slice_i64_push", MirSignature([ptr(), I64], VOID)))
        self.program.externs.append(MirExtern("__ep_slice_i64_pop", MirSignature([ptr()], I64)))
        self.program.externs.append(MirExtern("__ep_slice_i64_extend", MirSignature([ptr(), ptr()], VOID)))
        self.program.externs.append(MirExtern("__ep_slice_ptr_new", MirSignature([I64], ptr())))
        self.program.externs.append(MirExtern("__ep_slice_ptr_get", MirSignature([ptr(), I64], ptr())))
        self.program.externs.append(MirExtern("__ep_slice_ptr_set", MirSignature([ptr(), I64, ptr()], VOID)))
        self.program.externs.append(MirExtern("__ep_slice_ptr_push", MirSignature([ptr(), ptr()], VOID)))
        self.program.externs.append(MirExtern("__ep_slice_ptr_pop", MirSignature([ptr()], ptr())))
        self.program.externs.append(MirExtern("__ep_slice_ptr_extend", MirSignature([ptr(), ptr()], VOID)))
        self.program.externs.append(MirExtern("__ep_slice_u8_extend", MirSignature([ptr(), ptr()], VOID)))
        self.program.externs.append(MirExtern("__ep_print_str", MirSignature([ptr()], VOID)))
        self.program.externs.append(MirExtern("__ep_print_newline", MirSignature([], VOID)))
        self.program.externs.append(MirExtern("__ep_debug_i64", MirSignature([I64], VOID)))
        self.program.externs.append(MirExtern("__epx_alloc", MirSignature([I64], ptr())))
        self.program.globals.append(MirGlobal("argv", ptr(), None))
        self._emit_global_lets(ast)
        self._emit_global_init_function(ast)
        for fn in ast.funcs:
            self.program.functions.append(self._emit_function(fn))
        self.program.retain_referenced_externs()
        validate(self.program)
        return self.program

    def _emit_function(self, ast_fn):
        self.begin_function(
            ast_fn.name,
            [MirParam(i + 1, self._type(p.resolved_type)) for i, p in enumerate(ast_fn.params)],
            self._type(ast_fn.resolved_type),
        )
        self.local_scopes = [{}]
        self.local_type_scopes = [{}]
        entry = self.new_block("entry")
        for ast_param, param in zip(ast_fn.params, self.fn.params):
            self.set_block(entry)
            addr = self._alloc_local(ast_param.name, param.type)
            self.inst("store", [ValueOperand(param.value), ValueOperand(addr)])
            entry = self.current_block
        self._push_local_scope()
        try:
            body = self._emit_block_stmts_from(entry, ast_fn.body)
            if body.reachable:
                if ast_fn.body.value_expr is not None:
                    value = self._expr_from(body.block, ast_fn.body.value_expr)
                    if self.fn.return_type == VOID:
                        self.ret(value.block)
                    else:
                        self.ret(value.block, value.value)
                elif self.fn.return_type == VOID:
                    self.ret(body.block)
                else:
                    self.ret(body.block, ConstIntOperand(self.fn.return_type, 0))
        finally:
            self._pop_local_scope()
        return self.fn

    def _type(self, typ):
        if typ is None:
            raise MirCodegenError("missing resolved type")
        if not isinstance(typ, et.EpicType):
            raise MirCodegenError(f"internal parser produced non-EpicType type: {typ}")
        return self._epic_type(typ)

    def _epic_type(self, typ):
        if typ == et.VOID:
            return VOID
        if typ == et.BOOL:
            return BOOL
        if typ in (et.I64, et.U64, et.I8, et.U8):
            return I64
        if typ == et.STR:
            return ptr()
        if typ.kind == "array":
            elem = typ.elem
            if elem in (et.I8, et.U8):
                return ptr()
            if elem in (et.I64, et.U64, et.BOOL):
                return ptr()
            if elem == et.STR:
                return ptr()
            if elem is not None and elem.kind == "named":
                return ptr()
        if typ.kind == "named":
            return ptr()
        if typ.kind == "ptr":
            return ptr()
        raise MirCodegenError(f"machine MIR does not support type yet: {typ}")

    def _epic_pointee_type(self, typ):
        if typ in (et.I8, et.U8):
            return I8
        if typ == et.BOOL:
            return BOOL
        if typ in (et.I64, et.U64):
            return I64
        if typ == et.STR:
            return ptr()
        if typ is not None and typ.kind == "named":
            return ptr()
        if typ is not None and typ.kind == "ptr":
            return ptr()
        raise MirCodegenError(f"machine MIR does not support pointer type yet: {typ}")

    def _resolved_type(self, node):
        typ = getattr(node, "resolved_type", None)
        if typ is None:
            raise MirCodegenError(f"untyped AST node reached AST-to-MIR: {type(node).__name__}")
        return typ

    def _expr_mir_type(self, expr):
        return self._type(self._resolved_type(expr))

    def terminate(self, block_or_terminator, terminator=None):
        super().terminate(block_or_terminator, terminator)
        return BlockFlow(False, None)

    def _reachable(self, block):
        return BlockFlow(True, self.ensure_insertable(block))

    def _unreachable(self):
        return BlockFlow(False, None)

    def _expr_from(self, block, expr):
        self.set_block(block)
        value = self._emit_expr(expr)
        return ValueFlow(value, self.ensure_insertable(self.current_block))

    def _alloc_local(self, name, typ):
        block = self.ensure_insertable()
        addr = self.new_value(ptr())
        block.instructions.append(MirInst("alloca", result=addr, type=typ))
        self._define_local(name, addr, typ)
        return addr

    def _push_local_scope(self):
        self.local_scopes.append({})
        self.local_type_scopes.append({})

    def _pop_local_scope(self):
        self.local_scopes.pop()
        self.local_type_scopes.pop()

    def _define_local(self, name, addr, typ):
        if not self.local_scopes:
            raise MirCodegenError("internal: no active local scope")
        self.local_scopes[-1][name] = addr
        self.local_type_scopes[-1][name] = typ

    def _local_addr(self, name):
        for scope in reversed(self.local_scopes):
            if name in scope:
                return scope[name]
        raise MirCodegenError(f"undefined variable: {name}")

    def _local_type(self, name):
        for scope in reversed(self.local_type_scopes):
            if name in scope:
                return scope[name]
        raise MirCodegenError(f"undefined variable: {name}")

    def _alloc_struct(self, struct_name):
        size_ptr = self.inst(
            "gep",
            [ConstNullOperand(), ConstIntOperand(I64, 1)],
            result_type=ptr(),
            type=mir_struct(struct_name),
        )
        size = self.inst("ptrtoint", [ValueOperand(size_ptr)], result_type=I64, type=I64)
        obj = self.inst(
            "call",
            [ValueOperand(size)],
            result_type=ptr(),
            type=ptr(),
            callee="__epx_alloc",
        )
        return ValueOperand(obj)

    def _field_index(self, struct_name, field):
        try:
            return self.structs[struct_name].field_index(field)
        except KeyError as exc:
            raise MirCodegenError(f"unknown field: {struct_name}.{field}") from exc

    def _field_addr(self, base, struct_name, field, result_type=None):
        try:
            field_layout = self.structs[struct_name].field(field)
        except KeyError as exc:
            raise MirCodegenError(f"unknown field: {struct_name}.{field}") from exc
        field_type = result_type or field_layout.type
        addr = self.inst(
            "gep",
            [base, ConstIntOperand(I64, 0), ConstIntOperand(I64, self._field_index(struct_name, field))],
            result_type=ptr(),
            type=mir_struct(struct_name),
        )
        return ValueOperand(addr)

    def _load_field(self, base, struct_name, field, result_type=None):
        field_type = result_type or self.structs[struct_name].field(field).type
        addr = self._field_addr(base, struct_name, field, result_type=field_type)
        value = self.inst("load", [addr], result_type=field_type, type=field_type)
        return ValueOperand(value)

    def _union_common_field_layout(self, union_name, field):
        found = None
        for member in self.union_defs.get(union_name, []):
            try:
                candidate = self.structs[member].field(field)
            except KeyError:
                raise MirCodegenError(f"union {union_name} has no common field {field}")
            if found is not None and candidate.type != found.type:
                raise MirCodegenError(f"union {union_name} field {field} has inconsistent types")
            found = candidate
        if found is None:
            raise MirCodegenError(f"union {union_name} has no common field {field}")
        return found

    def _uniform_direct_field_member(self, union_name, field):
        members = list(self.union_defs.get(union_name, []))
        if not members:
            return None
        first_member = members[0]
        try:
            first_layout = self.structs[first_member].field(field)
            first_index = self.structs[first_member].field_index(field)
        except KeyError:
            return None
        for member in members[1:]:
            try:
                layout = self.structs[member].field(field)
                index = self.structs[member].field_index(field)
            except KeyError:
                return None
            if layout.type != first_layout.type or index != first_index:
                return None
        return first_member

    def _load_union_common_field(self, union_value, union_name, field):
        field_layout = self._union_common_field_layout(union_name, field)
        uniform_member = self._uniform_direct_field_member(union_name, field)
        if uniform_member is not None:
            payload = self._load_field(union_value, union_name, "payload")
            return self._load_field(payload, uniform_member, field, result_type=field_layout.type)
        wrapper_addr = self._alloc_local("__union_field", ptr())
        self.inst("store", [union_value, ValueOperand(wrapper_addr)])
        result_addr = self._alloc_local("__union_field_result", field_layout.type)
        end = self.new_block("union.field.end")
        members = list(self.union_defs.get(union_name, []))
        case_blocks = [self.new_block("union.field.case") for _ in members]
        next_blocks = [self.new_block("union.field.next") for _ in range(max(len(members) - 1, 0))]
        check_block = self.current_block
        for idx, member in enumerate(members):
            self.set_block(check_block)
            wrapper = self.inst("load", [ValueOperand(wrapper_addr)], result_type=ptr(), type=ptr())
            tag = self._load_field(ValueOperand(wrapper), union_name, "tag")
            cond = self.inst("icmp.eq", [tag, ConstIntOperand(I64, self.union_tags[union_name][member])], result_type=BOOL)
            next_block = next_blocks[idx] if idx < len(next_blocks) else end
            self.condbr(ValueOperand(cond), case_blocks[idx], next_block)
            if idx < len(next_blocks):
                check_block = next_blocks[idx]
        if not members:
            self.br(check_block, end)
        for idx, member in enumerate(members):
            self.set_block(case_blocks[idx])
            wrapper = self.inst("load", [ValueOperand(wrapper_addr)], result_type=ptr(), type=ptr())
            payload = self._load_field(ValueOperand(wrapper), union_name, "payload")
            value = self._load_field(payload, member, field)
            self.inst("store", [value, ValueOperand(result_addr)])
            self.br(end)
        self.set_block(end)
        result = self.inst("load", [ValueOperand(result_addr)], result_type=field_layout.type, type=field_layout.type)
        return ValueOperand(result)

    def _store_field(self, base, struct_name, field, value):
        addr = self._field_addr(base, struct_name, field)
        self.inst("store", [value, addr])

    def _layout_struct_name(self, typ):
        """Return the runtime layout struct name for an EpicType."""
        if not isinstance(typ, et.EpicType):
            return None
        if typ == et.STR:
            return "str"
        if typ.kind == "array":
            if typ.elem in (et.I8, et.U8):
                return "_slice_u8"
            if typ.elem in (et.I64, et.U64, et.BOOL):
                return "_slice_i64"
            if typ.elem == et.STR:
                return "_slice_str"
            if typ.elem is not None and typ.elem.kind == "named":
                return f"_slice_{typ.elem.name}"
        if typ.kind == "named":
            return typ.name
        return None

    def _array_struct_elem(self, typ):
        if not isinstance(typ, et.EpicType):
            return None
        if typ.kind == "array" and typ.elem == et.STR:
            return "str"
        if typ.kind == "array" and typ.elem is not None and typ.elem.kind == "named":
            return typ.elem.name if typ.elem.name in self.structs else None
        return None

    def _is_slice_type(self, typ):
        return isinstance(typ, et.EpicType) and typ.kind == "array"

    def _is_u8_array_type(self, typ):
        return isinstance(typ, et.EpicType) and typ.kind == "array" and typ.elem in (et.I8, et.U8)

    def _is_i64_array_type(self, typ):
        return isinstance(typ, et.EpicType) and typ.kind == "array" and typ.elem in (et.I64, et.U64, et.BOOL)

    def _is_ptr_type(self, typ):
        return isinstance(typ, et.EpicType) and typ.kind == "ptr"

    def _array_extend_helper(self, typ):
        if self._is_u8_array_type(typ):
            return "__ep_slice_u8_extend"
        if self._is_i64_array_type(typ):
            return "__ep_slice_i64_extend"
        if self._array_struct_elem(typ) is not None:
            return "__ep_slice_ptr_extend"
        return None

    def _array_pop_helper(self, typ):
        if self._is_u8_array_type(typ):
            return "__ep_slice_u8_pop", I64
        if self._is_i64_array_type(typ):
            return "__ep_slice_i64_pop", I64
        if isinstance(typ, et.EpicType) and typ.kind == "array":
            return "__ep_slice_ptr_pop", ptr()
        return None, None

    def _emit_block(self, block):
        flow = self._emit_block_from(self.ensure_insertable(), block)
        self.current_block = flow.block if flow.reachable else None
        return flow

    def _emit_block_stmts_from(self, in_block, block):
        flow = self._reachable(in_block)
        for stmt in block.stmts:
            if not flow.reachable:
                return flow
            flow = self._emit_stmt_from(flow.block, stmt)
        return flow

    def _emit_block_from(self, in_block, block):
        self._push_local_scope()
        try:
            flow = self._emit_block_stmts_from(in_block, block)
            if flow.reachable and block.value_expr is not None:
                value = self._expr_from(flow.block, block.value_expr)
                return self._reachable(value.block)
            return flow
        finally:
            self._pop_local_scope()

    def _emit_stmt(self, stmt):
        flow = self._emit_stmt_from(self.ensure_insertable(), stmt)
        self.current_block = flow.block if flow.reachable else None
        return flow

    def _emit_stmt_from(self, in_block, stmt):
        self.set_block(in_block)
        if isinstance(stmt, ExprStmtNode):
            value = self._expr_from(in_block, stmt.expr)
            return self._reachable(value.block)
        elif isinstance(stmt, LetNode):
            typ = self._type(stmt.resolved_type)
            addr = self._alloc_local(stmt.name, typ)
            init_block = self.current_block
            value = self._expr_from(init_block, stmt.value) if stmt.value is not None else ValueFlow(self._zero_value(typ), init_block)
            self.set_block(value.block)
            self.inst("store", [value.value, ValueOperand(addr)])
            return self._reachable(self.current_block)
        elif isinstance(stmt, AssignNode):
            value = self._expr_from(in_block, stmt.value)
            self.set_block(value.block)
            if stmt.name in self.globals:
                self.inst("store", [value.value, SymbolOperand(ptr(), self._global_label(stmt.name))])
                return self._reachable(self.current_block)
            self.inst("store", [value.value, ValueOperand(self._local_addr(stmt.name))])
            return self._reachable(self.current_block)
        elif isinstance(stmt, ReturnNode):
            if stmt.expr is None:
                return self.ret(in_block)
            value = self._expr_from(in_block, stmt.expr)
            return self.ret(value.block, value.value)
        elif isinstance(stmt, IfNode):
            return self._emit_if_from(in_block, stmt)
        elif isinstance(stmt, WhileNode):
            return self._emit_while_from(in_block, stmt)
        elif isinstance(stmt, ForRangeNode):
            return self._emit_for_range_from(in_block, stmt)
        elif isinstance(stmt, ForInNode):
            return self._emit_for_in_from(in_block, stmt)
        elif isinstance(stmt, AssertNode):
            return self._emit_assert_from(in_block, stmt)
        elif isinstance(stmt, PanicNode):
            return self._emit_panic_from(in_block, stmt)
        elif isinstance(stmt, MatchNode):
            return self._emit_match_from(in_block, stmt)
        elif isinstance(stmt, FieldSetNode):
            base_type = self._infer_type(stmt.object)
            base = self._expr_from(in_block, stmt.object)
            value = self._expr_from(base.block, stmt.value)
            self.set_block(value.block)
            if base_type.kind == "named" and base_type.name in self.union_defs:
                raise MirCodegenError("field assignment base must be struct")
            struct_name = self._layout_struct_name(base_type)
            if struct_name is None:
                raise MirCodegenError("field assignment base must be a struct pointer")
            self._store_field(base.value, struct_name, stmt.field, value.value)
            return self._reachable(self.current_block)
        elif isinstance(stmt, SubscriptAssignNode):
            base_type = self._infer_type(stmt.base)
            base = self._expr_from(in_block, stmt.base)
            index = self._expr_from(base.block, stmt.index)
            value = self._expr_from(index.block, stmt.value)
            self.set_block(value.block)
            if self._is_u8_array_type(base_type):
                self.inst("call", [base.value, index.value, value.value], type=VOID, callee="__ep_slice_u8_set")
            elif self._is_i64_array_type(base_type):
                self.inst("call", [base.value, index.value, value.value], type=VOID, callee="__ep_slice_i64_set")
            elif self._array_struct_elem(base_type) is not None:
                self.inst("call", [base.value, index.value, value.value], type=VOID, callee="__ep_slice_ptr_set")
            else:
                raise MirCodegenError("subscript assignment only supports arrays in machine MIR")
            return self._reachable(self.current_block)
        elif isinstance(stmt, AssignOpNode):
            if isinstance(stmt.target, VarNode):
                typ = self._local_type(stmt.target.name)
                addr = ValueOperand(self._local_addr(stmt.target.name))
                current = self.inst("load", [addr], result_type=typ, type=typ)
                rhs = self._expr_from(in_block, stmt.value)
                self.set_block(rhs.block)
                result = self._binary(stmt.op, ValueOperand(current), rhs.value, self._infer_type(stmt.target), self._node_line(stmt))
                self.inst("store", [result, addr])
                return self._reachable(self.current_block)
            if isinstance(stmt.target, FieldAccessNode):
                base_type = self._infer_type(stmt.target.object)
                struct_name = self._layout_struct_name(base_type)
                if struct_name is None:
                    raise MirCodegenError("compound field assignment base must be a struct pointer")
                base = self._expr_from(in_block, stmt.target.object)
                self.set_block(base.block)
                try:
                    field_layout = self.structs[struct_name].field(stmt.target.field)
                except KeyError:
                    raise MirCodegenError(f"unknown field: {struct_name}.{stmt.target.field}")
                addr = self._field_addr(base.value, struct_name, stmt.target.field)
                field_type = field_layout.type
                current = self.inst("load", [addr], result_type=field_type, type=field_type)
                rhs = self._expr_from(self.current_block, stmt.value)
                self.set_block(rhs.block)
                result = self._binary(stmt.op, ValueOperand(current), rhs.value, self._infer_type(stmt.target), self._node_line(stmt))
                self.inst("store", [result, addr])
                return self._reachable(self.current_block)
            if isinstance(stmt.target, SubscriptNode):
                base_type = self._infer_type(stmt.target.base)
                base = self._expr_from(in_block, stmt.target.base)
                index = self._expr_from(base.block, stmt.target.index)
                self.set_block(index.block)
                if self._is_i64_array_type(base_type):
                    current = self.inst("call", [base.value, index.value], result_type=I64, type=I64, callee="__ep_slice_i64_get")
                elif self._is_u8_array_type(base_type):
                    current = self.inst("call", [base.value, index.value], result_type=I64, type=I64, callee="__ep_slice_u8_get")
                else:
                    raise MirCodegenError("compound subscript assignment only supports primitive arrays in machine MIR")
                rhs = self._expr_from(self.current_block, stmt.value)
                self.set_block(rhs.block)
                result = self._binary(stmt.op, ValueOperand(current), rhs.value, self._infer_type(stmt.target), self._node_line(stmt))
                if self._is_i64_array_type(base_type):
                    self.inst("call", [base.value, index.value, result], type=VOID, callee="__ep_slice_i64_set")
                else:
                    self.inst("call", [base.value, index.value, result], type=VOID, callee="__ep_slice_u8_set")
                return self._reachable(self.current_block)
            raise MirCodegenError(f"unsupported compound assignment target: {type(stmt.target).__name__}")
        elif isinstance(stmt, BreakNode):
            if not self.loop_stack:
                raise MirCodegenError("break outside loop")
            return self.br(in_block, self.loop_stack[-1][1])
        elif isinstance(stmt, ContinueNode):
            if not self.loop_stack:
                raise MirCodegenError("continue outside loop")
            return self.br(in_block, self.loop_stack[-1][0])
        raise MirCodegenError(f"machine MIR does not support stmt yet: {type(stmt).__name__}")

    def _emit_if(self, stmt):
        flow = self._emit_if_from(self.ensure_insertable(), stmt)
        self.current_block = flow.block if flow.reachable else None
        return flow

    def _emit_if_from(self, in_block, stmt):
        cond = self._expr_from(in_block, stmt.cond)
        then_block = self.new_block("if.then")
        else_block = self.new_block("if.else") if stmt.else_block else None
        end_block = self.new_block("if.end")
        self.condbr(cond.block, cond.value, then_block.name, else_block.name if else_block else end_block.name)

        then_flow = self._emit_block_from(then_block, stmt.then_block)
        if then_flow.reachable:
            self.br(then_flow.block, end_block.name)

        if else_block is not None:
            else_flow = self._emit_block_from(else_block, stmt.else_block)
            if else_flow.reachable:
                self.br(else_flow.block, end_block.name)

        return self._reachable(end_block)

    def _emit_while(self, stmt):
        flow = self._emit_while_from(self.ensure_insertable(), stmt)
        self.current_block = flow.block if flow.reachable else None
        return flow

    def _emit_while_from(self, in_block, stmt):
        cond_block = self.new_block("while.cond")
        body_block = self.new_block("while.body")
        end_block = self.new_block("while.end")
        self.br(in_block, cond_block.name)
        self.loop_stack.append((cond_block.name, end_block.name))
        cond = self._expr_from(cond_block, stmt.cond)
        self.condbr(cond.block, cond.value, body_block.name, end_block.name)
        body_flow = self._emit_block_from(body_block, stmt.body)
        if body_flow.reachable:
            self.br(body_flow.block, cond_block.name)
        self.loop_stack.pop()
        return self._reachable(end_block)

    def _emit_for_range(self, stmt):
        flow = self._emit_for_range_from(self.ensure_insertable(), stmt)
        self.current_block = flow.block if flow.reachable else None
        return flow

    def _emit_for_range_from(self, in_block, stmt):
        self.set_block(in_block)
        start = self._expr_from(self.current_block, stmt.start)
        end_value = self._expr_from(start.block, stmt.end)
        self.set_block(end_value.block)
        self._push_local_scope()
        try:
            var_addr = self._alloc_local(stmt.name, I64)
            end_addr = self._alloc_local(f"__{stmt.name}.end{self.value_counter}", I64)
            self.inst("store", [start.value, ValueOperand(var_addr)])
            self.inst("store", [end_value.value, ValueOperand(end_addr)])

            cond_block = self.new_block("for.cond")
            body_block = self.new_block("for.body")
            inc_block = self.new_block("for.inc")
            end_block = self.new_block("for.end")
            self.br(self.current_block, cond_block.name)

            self.set_block(cond_block)
            cur = self.inst("load", [ValueOperand(var_addr)], result_type=I64, type=I64)
            end = self.inst("load", [ValueOperand(end_addr)], result_type=I64, type=I64)
            cond = self.inst("icmp.slt", [ValueOperand(cur), ValueOperand(end)], result_type=BOOL)
            self.condbr(cond_block, ValueOperand(cond), body_block.name, end_block.name)

            self.loop_stack.append((inc_block.name, end_block.name))
            body_flow = self._emit_block_from(body_block, stmt.body)
            if body_flow.reachable:
                self.br(body_flow.block, inc_block.name)
            self.loop_stack.pop()

            self.set_block(inc_block)
            cur = self.inst("load", [ValueOperand(var_addr)], result_type=I64, type=I64)
            nxt = self.inst("add", [ValueOperand(cur), ConstIntOperand(I64, 1)], result_type=I64)
            self.inst("store", [ValueOperand(nxt), ValueOperand(var_addr)])
            self.br(inc_block, cond_block.name)
            return self._reachable(end_block)
        finally:
            self._pop_local_scope()

    def _emit_for_in_from(self, in_block, stmt):
        source_type = self._infer_type(stmt.source)
        if source_type.kind == "array":
            return self._emit_for_in_array_from(in_block, stmt, source_type)
        raise MirCodegenError(f"for-in expected array, got {source_type}")

    def _emit_for_in_array_from(self, in_block, stmt, source_type):
        source = self._expr_from(in_block, stmt.source)
        self.set_block(source.block)
        struct_name = self._layout_struct_name(source_type)
        if struct_name is None:
            raise MirCodegenError(f"unsupported for-in array source: {source_type}")

        self._push_local_scope()
        try:
            var_addr = self._alloc_local(stmt.name, I64)
            limit_addr = self._alloc_local(f"__{stmt.name}.limit{self.value_counter}", I64)
            initial_len = self._load_field(source.value, struct_name, "len", result_type=I64)
            self.inst("store", [initial_len, ValueOperand(limit_addr)])
            self.inst("store", [ConstIntOperand(I64, 0), ValueOperand(var_addr)])

            cond_block = self.new_block("for.in.cond")
            len_block = self.new_block("for.in.len")
            body_block = self.new_block("for.in.body")
            inc_block = self.new_block("for.in.inc")
            end_block = self.new_block("for.in.end")
            self.br(self.current_block, cond_block.name)

            self.set_block(cond_block)
            cur = self.inst("load", [ValueOperand(var_addr)], result_type=I64, type=I64)
            limit = self.inst("load", [ValueOperand(limit_addr)], result_type=I64, type=I64)
            within_limit = self.inst("icmp.slt", [ValueOperand(cur), ValueOperand(limit)], result_type=BOOL)
            self.condbr(cond_block, ValueOperand(within_limit), len_block.name, end_block.name)

            self.set_block(len_block)
            cur2 = self.inst("load", [ValueOperand(var_addr)], result_type=I64, type=I64)
            current_len = self._load_field(source.value, struct_name, "len", result_type=I64)
            within_current = self.inst("icmp.slt", [ValueOperand(cur2), current_len], result_type=BOOL)
            self.condbr(len_block, ValueOperand(within_current), body_block.name, end_block.name)

            self.loop_stack.append((inc_block.name, end_block.name))
            body_flow = self._emit_block_from(body_block, stmt.body)
            if body_flow.reachable:
                self.br(body_flow.block, inc_block.name)
            self.loop_stack.pop()

            self.set_block(inc_block)
            cur3 = self.inst("load", [ValueOperand(var_addr)], result_type=I64, type=I64)
            nxt = self.inst("add", [ValueOperand(cur3), ConstIntOperand(I64, 1)], result_type=I64)
            self.inst("store", [ValueOperand(nxt), ValueOperand(var_addr)])
            self.br(inc_block, cond_block.name)
            return self._reachable(end_block)
        finally:
            self._pop_local_scope()

    def _emit_assert(self, stmt):
        flow = self._emit_assert_from(self.ensure_insertable(), stmt)
        self.current_block = flow.block if flow.reachable else None
        return flow

    def _emit_assert_from(self, in_block, stmt):
        cond = self._expr_from(in_block, stmt.cond)
        ok_block = self.new_block("assert.ok")
        fail_block = self.new_block("assert.fail")
        self.condbr(cond.block, cond.value, ok_block.name, fail_block.name)

        self.set_block(fail_block)
        self._emit_print_text(f"assert line {stmt.line}: ")
        if stmt.message is None:
            self._emit_print_text("assertion failed")
        else:
            self._emit_print_expr(stmt.message)
        self._emit_print_newline()
        self._emit_exit_current_block()
        self.terminate(fail_block, self._dummy_return())
        return self._reachable(ok_block)

    def _emit_panic(self, stmt):
        flow = self._emit_panic_from(self.ensure_insertable(), stmt)
        self.current_block = flow.block if flow.reachable else None
        return flow

    def _emit_panic_from(self, in_block, stmt):
        self.set_block(in_block)
        self._emit_print_text(f"panic line {stmt.line}: ")
        self._emit_print_expr(stmt.message)
        self._emit_print_newline()
        self._emit_exit_current_block()
        return self.terminate(self.current_block, self._dummy_return())

    def _dummy_return(self):
        if self.fn.return_type == VOID:
            return Ret()
        return Ret(ConstIntOperand(self.fn.return_type, 0))

    def _emit_exit_current_block(self, code=1):
        self.inst("call", [ConstIntOperand(I64, code)], type=VOID, callee="ExitProcess")

    def _emit_print_text(self, text):
        self.inst("call", [SymbolOperand(ptr(), self._string_label(text))], type=VOID, callee="__ep_print_str")

    def _emit_print_expr(self, expr):
        self.inst("call", [self._coerce_print_arg(expr)], type=VOID, callee="__ep_print_str")

    def _emit_print_newline(self):
        self.inst("call", [], type=VOID, callee="__ep_print_newline")

    def _node_line(self, node):
        return getattr(node, "line", getattr(getattr(node, "target", None), "line", getattr(getattr(node, "value", None), "line", 0)))

    def _shift_width(self, typ):
        if typ in (et.U8, "u8"):
            return 8
        return 64

    def _emit_shift_count_check(self, count, lhs_type, line):
        width = self._shift_width(lhs_type)
        high_block = self.new_block("shift.high")
        ok_block = self.new_block("shift.ok")
        fail_block = self.new_block("shift.fail")

        nonneg = self.inst("icmp.sge", [count, ConstIntOperand(I64, 0)], result_type=BOOL)
        self.condbr(self.current_block, ValueOperand(nonneg), high_block.name, fail_block.name)

        self.set_block(high_block)
        in_range = self.inst("icmp.slt", [count, ConstIntOperand(I64, width)], result_type=BOOL)
        self.condbr(high_block, ValueOperand(in_range), ok_block.name, fail_block.name)

        self.set_block(fail_block)
        self._emit_print_text(f"panic line {line}: invalid shift count")
        self._emit_print_newline()
        self._emit_exit_current_block()
        self.terminate(fail_block, self._dummy_return())

        self.set_block(ok_block)

    def _emit_truncating_uint_conversion(self, expr, mask):
        value = self._emit_expr(expr)
        return ValueOperand(self.inst("and", [value, ConstIntOperand(I64, mask)], result_type=I64))

    def _emit_truncating_i32_conversion(self, expr):
        value = self._emit_expr(expr)
        shifted = self.inst("shl", [value, ConstIntOperand(I64, 32)], result_type=I64)
        sign_extended = self.inst("sar", [ValueOperand(shifted), ConstIntOperand(I64, 32)], result_type=I64)
        return ValueOperand(sign_extended)

    def _emit_match(self, stmt):
        flow = self._emit_match_from(self.ensure_insertable(), stmt)
        self.current_block = flow.block if flow.reachable else None
        return flow

    def _emit_match_from(self, in_block, stmt):
        if getattr(stmt, "union_name", ""):
            return self._emit_union_match_from(in_block, stmt)
        scrutinee = self._expr_from(in_block, stmt.expr)
        self.set_block(scrutinee.block)
        match_addr = self._alloc_local(f"__match{self.value_counter}", scrutinee.value.type)
        self.inst("store", [scrutinee.value, ValueOperand(match_addr)])

        end_block = self.new_block("match.end")
        else_case = next((case for case in stmt.cases if case.is_else), None)
        checks = [(case, self.new_block("match.case")) for case in stmt.cases if not case.is_else]
        else_block = self.new_block("match.else") if else_case is not None else end_block

        check_block = self.current_block
        next_check_blocks = [self.new_block("match.next") for _ in checks[:-1]]
        for idx, (case, case_block) in enumerate(checks):
            self.set_block(check_block)
            next_block = next_check_blocks[idx] if idx < len(checks) - 1 else else_block
            self._emit_match_check(stmt, match_addr, scrutinee.value.type, case, case_block, next_block)
            if idx < len(checks) - 1:
                check_block = next_check_blocks[idx]

        if not checks:
            self.br(check_block, else_block.name)

        any_reachable = False
        for case, case_block in checks:
            self.set_block(case_block)
            self._emit_match_bindings(match_addr, case)
            case_flow = self._emit_block_from(case_block, case.body)
            if case_flow.reachable:
                any_reachable = True
                self.br(case_flow.block, end_block.name)

        if else_case is not None:
            else_flow = self._emit_block_from(else_block, else_case.body)
            if else_flow.reachable:
                any_reachable = True
                self.br(else_flow.block, end_block.name)
        else:
            any_reachable = True

        return self._reachable(end_block)

    def _emit_match_check(self, stmt, match_addr, match_type, case, case_block, next_block):
        scrut = self.inst("load", [ValueOperand(match_addr)], result_type=match_type, type=match_type)
        scrut_op = ValueOperand(scrut)
        pat = self._emit_expr(case.pattern)
        cond = self.inst("icmp.eq", [scrut_op, pat], result_type=BOOL)
        self.condbr(self.current_block, ValueOperand(cond), case_block.name, next_block.name)

    def _emit_match_bindings(self, match_addr, case):
        if not case.bindings:
            return

    def _emit_union_match_from(self, in_block, stmt):
        scrutinee = self._expr_from(in_block, stmt.expr)
        self.set_block(scrutinee.block)
        match_addr = self._alloc_local(f"__match{self.value_counter}", scrutinee.value.type)
        self.inst("store", [scrutinee.value, ValueOperand(match_addr)])

        union_name = stmt.union_name
        end_block = self.new_block("match.end")
        else_case = next((case for case in stmt.cases if case.is_else), None)
        checks = [(case, self.new_block("match.case")) for case in stmt.cases if not case.is_else]
        else_block = self.new_block("match.else") if else_case is not None else end_block

        check_block = self.current_block
        next_check_blocks = [self.new_block("match.next") for _ in checks[:-1]]
        for idx, (case, case_block) in enumerate(checks):
            self.set_block(check_block)
            next_block = next_check_blocks[idx] if idx < len(checks) - 1 else else_block
            wrapper = self.inst("load", [ValueOperand(match_addr)], result_type=ptr(), type=ptr())
            tag = self._load_field(ValueOperand(wrapper), union_name, "tag", result_type=I64)
            expected = ConstIntOperand(I64, self.union_tags[union_name][case.variant_name])
            cond = self.inst("icmp.eq", [tag, expected], result_type=BOOL)
            self.condbr(self.current_block, ValueOperand(cond), case_block.name, next_block.name)
            if idx < len(checks) - 1:
                check_block = next_check_blocks[idx]

        if not checks:
            self.br(check_block, else_block.name)

        for case, case_block in checks:
            self.set_block(case_block)
            wrapper = self.inst("load", [ValueOperand(match_addr)], result_type=ptr(), type=ptr())
            payload = self._load_field(ValueOperand(wrapper), union_name, "payload", result_type=ptr())
            self._push_local_scope()
            bind_addr = self._alloc_local(case.binding_name, ptr())
            self.inst("store", [payload, ValueOperand(bind_addr)])
            case_flow = self._emit_block_from(self.current_block, case.body)
            self._pop_local_scope()
            if case_flow.reachable:
                self.br(case_flow.block, end_block.name)

        if else_case is not None:
            else_flow = self._emit_block_from(else_block, else_case.body)
            if else_flow.reachable:
                self.br(else_flow.block, end_block.name)

        return self._reachable(end_block)

    def _emit_expr(self, expr):
        return self._emit_expr_from(self.ensure_insertable(), expr).value

    def _emit_expr_from(self, in_block, expr):
        self.set_block(in_block)
        if isinstance(expr, (LiteralNode, CharNode)):
            return ValueFlow(ConstIntOperand(I64, expr.value), self.current_block)
        if isinstance(expr, BoolNode):
            return ValueFlow(ConstBoolOperand(bool(expr.value)), self.current_block)
        if isinstance(expr, StringNode):
            return ValueFlow(SymbolOperand(ptr(), self._string_label(expr.value)), self.current_block)
        if isinstance(expr, FStringNode):
            return self._emit_fstring_from(self.current_block, expr)
        if isinstance(expr, VarNode):
            if expr.name == "argv":
                return ValueFlow(SymbolOperand(ptr(), "argv"), self.current_block)
            if expr.name in self.globals:
                typ = self.globals[expr.name]
                value = self.inst("load", [SymbolOperand(ptr(), self._global_label(expr.name))], result_type=typ, type=typ)
                return ValueFlow(ValueOperand(value), self.current_block)
            typ = self._local_type(expr.name)
            value = self.inst("load", [ValueOperand(self._local_addr(expr.name))], result_type=typ, type=typ)
            return ValueFlow(ValueOperand(value), self.current_block)
        if isinstance(expr, UnaryNode):
            inner = self._emit_expr_from(self.current_block, expr.expr)
            self.set_block(inner.block)
            if expr.op == "-":
                zero = ConstIntOperand(I64, 0)
                return ValueFlow(ValueOperand(self.inst("sub", [zero, inner.value], result_type=I64)), self.current_block)
            if expr.op == "!":
                return ValueFlow(ValueOperand(self.inst("not", [inner.value], result_type=BOOL)), self.current_block)
            raise MirCodegenError(f"unsupported unary op: {expr.op}")
        if isinstance(expr, BinaryNode):
            return self._emit_binary_from(self.current_block, expr)
        if isinstance(expr, CallNode):
            return self._emit_call_from(self.current_block, expr)
        if isinstance(expr, DotCallNode):
            return self._emit_dot_call_from(self.current_block, expr)
        if isinstance(expr, SubscriptNode):
            return self._emit_subscript_from(self.current_block, expr)
        if isinstance(expr, ArrayLiteralNode):
            return self._emit_array_literal_from(self.current_block, expr)
        if isinstance(expr, NewArrayNode):
            return self._emit_new_array_from(self.current_block, expr)
        if isinstance(expr, SliceNode):
            return self._emit_slice_from(self.current_block, expr)
        if isinstance(expr, StructInitNode):
            return self._emit_struct_init_from(self.current_block, expr)
        if isinstance(expr, UnionInitNode):
            return self._emit_union_init_from(self.current_block, expr)
        if isinstance(expr, FieldAccessNode):
            return self._emit_field_access_from(self.current_block, expr)
        if isinstance(expr, NullCheckNode):
            value = self._emit_expr_from(self.current_block, expr.expr)
            self.set_block(value.block)
            result = self.inst("icmp.ne", [value.value, ConstNullOperand()], result_type=BOOL)
            return ValueFlow(ValueOperand(result), self.current_block)
        raise MirCodegenError(f"machine MIR does not support expr yet: {type(expr).__name__}")

    def _emit_arg_flows_from(self, in_block, exprs):
        block = in_block
        values = []
        for expr in exprs:
            flow = self._emit_expr_from(block, expr)
            values.append(flow.value)
            block = flow.block
        self.set_block(block)
        return ValueFlow(values, block)

    def _normalize_integer_value(self, value, typ):
        if typ in (et.U8, "u8"):
            return self._emit_truncating_uint_conversion_value(value, 255)
        return value

    def _binary(self, op, left, right, lhs_type=None, line=0):
        op_map = {"+": "add", "-": "sub", "*": "mul", "&": "and", "|": "or", "^": "xor",
                  "<<": "shl", ">>": "sar", ">>>": "shr"}
        unsigned = self._is_unsigned_integer(lhs_type)
        if op == "/":
            value = ValueOperand(self.inst("udiv" if unsigned else "sdiv", [left, right], result_type=I64))
            return self._normalize_integer_value(value, lhs_type)
        if op == "%":
            value = ValueOperand(self.inst("urem" if unsigned else "srem", [left, right], result_type=I64))
            return self._normalize_integer_value(value, lhs_type)
        if op in ("<<", ">>", ">>>"):
            self._emit_shift_count_check(right, lhs_type, line)
        if op in op_map:
            value = ValueOperand(self.inst(op_map[op], [left, right], result_type=I64))
            return self._normalize_integer_value(value, lhs_type)
        raise MirCodegenError(f"unsupported compound assignment op: {op}")

    def _emit_binary(self, expr):
        return self._emit_binary_from(self.ensure_insertable(), expr).value

    def _emit_binary_from(self, in_block, expr):
        if expr.op in ("&&", "||"):
            return self._emit_short_circuit_from(in_block, expr)

        left_type = self._infer_type(expr.left)
        right_type = self._infer_type(expr.right)
        left = self._emit_expr_from(in_block, expr.left)
        right = self._emit_expr_from(left.block, expr.right)
        self.set_block(right.block)
        op_map = {"+": "add", "-": "sub", "*": "mul", "&": "and", "|": "or", "^": "xor", "<<": "shl", ">>": "sar", ">>>": "shr"}
        cmp_map = {"==": "eq", "!=": "ne", "<": "lt", ">": "gt", "<=": "le", ">=": "ge"}
        unsigned = self._is_unsigned_integer(left_type)
        if expr.op in ("==", "!=") and left_type == et.STR and right_type == et.STR:
            result = self.inst("call", [left.value, right.value], result_type=BOOL, type=BOOL, callee="__ep_str_eq")
            value = ValueOperand(result)
            if expr.op == "!=":
                value = ValueOperand(self.inst("not", [value], result_type=BOOL))
            return ValueFlow(value, self.current_block)
        if expr.op == "/":
            value = ValueOperand(self.inst("udiv" if unsigned else "sdiv", [left.value, right.value], result_type=I64))
            return ValueFlow(self._normalize_integer_value(value, left_type), self.current_block)
        if expr.op == "%":
            value = ValueOperand(self.inst("urem" if unsigned else "srem", [left.value, right.value], result_type=I64))
            return ValueFlow(self._normalize_integer_value(value, left_type), self.current_block)
        if expr.op in op_map:
            if expr.op in ("<<", ">>", ">>>"):
                self._emit_shift_count_check(right.value, left_type, self._node_line(expr))
            value = ValueOperand(self.inst(op_map[expr.op], [left.value, right.value], result_type=I64))
            return ValueFlow(self._normalize_integer_value(value, left_type), self.current_block)
        if expr.op in cmp_map:
            pred = cmp_map[expr.op]
            if pred not in ("eq", "ne"):
                pred = ("u" if unsigned else "s") + pred
            return ValueFlow(ValueOperand(self.inst(f"icmp.{pred}", [left.value, right.value], result_type=BOOL)), self.current_block)
        raise MirCodegenError(f"unsupported binary op: {expr.op}")

    def _is_unsigned_integer(self, typ):
        return typ in (et.U64, et.U8)

    def _emit_short_circuit(self, expr):
        return self._emit_short_circuit_from(self.ensure_insertable(), expr).value

    def _emit_short_circuit_from(self, in_block, expr):
        self.set_block(in_block)
        result_addr = self.new_value(ptr())
        self.current_block.instructions.append(MirInst("alloca", result=result_addr, type=BOOL))

        left = self._emit_expr_from(self.current_block, expr.left)
        rhs_block = self.new_block("logic.rhs")
        short_block = self.new_block("logic.short")
        end_block = self.new_block("logic.end")

        if expr.op == "&&":
            self.condbr(left.block, left.value, rhs_block.name, short_block.name)
            short_value = ConstBoolOperand(False)
        else:
            self.condbr(left.block, left.value, short_block.name, rhs_block.name)
            short_value = ConstBoolOperand(True)

        self.set_block(short_block)
        self.inst("store", [short_value, ValueOperand(result_addr)])
        self.br(short_block, end_block.name)

        right = self._emit_expr_from(rhs_block, expr.right)
        self.set_block(right.block)
        self.inst("store", [right.value, ValueOperand(result_addr)])
        self.br(right.block, end_block.name)

        self.set_block(end_block)
        result = self.inst("load", [ValueOperand(result_addr)], result_type=BOOL, type=BOOL)
        return ValueFlow(ValueOperand(result), self.current_block)

    def _emit_call(self, expr):
        return self._emit_call_from(self.ensure_insertable(), expr).value

    def _emit_call_from(self, in_block, expr):
        self.set_block(in_block)
        name = expr.name
        if expr.namespace == "os":
            return self._emit_os_call_from(self.current_block, expr)
        if expr.namespace:
            raise MirCodegenError(f"unsupported namespaced call: {expr.namespace}.{name}")
        if self._is_builtin(name):
            return self._emit_builtin_from(self.current_block, expr)
        return self._emit_user_call_from(self.current_block, expr)

    def _is_builtin(self, name):
        return name in {
            "println",
            "print",
            "print_debug",
            "exit",
            "str",
            "cstr",
            "i64",
            "u64",
            "u8",
            "bool",
            "bytes",
            "read_file",
            "write_file",
            "len",
            "cap",
        }

    def _emit_builtin(self, expr):
        return self._emit_builtin_from(self.ensure_insertable(), expr).value

    def _emit_builtin_from(self, in_block, expr):
        self.set_block(in_block)
        name = expr.name
        if name == "println":
            if len(expr.args) > 1:
                raise MirCodegenError("println expects at most one argument")
            if expr.args:
                if self._infer_type(expr.args[0]) != et.STR:
                    raise MirCodegenError(f"println expected str, got {self._infer_type(expr.args[0])}")
                arg = self._emit_expr_from(self.current_block, expr.args[0])
                self.set_block(arg.block)
                self.inst("call", [arg.value], type=VOID, callee="__ep_print_str")
            self.inst("call", [], type=VOID, callee="__ep_print_newline")
            return ValueFlow(ConstIntOperand(I64, 0), self.current_block)
        if name == "print":
            if len(expr.args) != 1:
                raise MirCodegenError("print expects 1 argument")
            if self._infer_type(expr.args[0]) != et.STR:
                raise MirCodegenError(f"print expected str, got {self._infer_type(expr.args[0])}")
            arg = self._emit_expr_from(self.current_block, expr.args[0])
            self.set_block(arg.block)
            self.inst("call", [arg.value], type=VOID, callee="__ep_print_str")
            return ValueFlow(ConstIntOperand(I64, 0), self.current_block)
        if name == "print_debug":
            if len(expr.args) != 1:
                raise MirCodegenError("print_debug expects 1 argument")
            arg = self._emit_expr_from(self.current_block, expr.args[0])
            self.set_block(arg.block)
            self.inst("call", [arg.value], type=VOID, callee="__ep_debug_i64")
            return ValueFlow(ConstIntOperand(I64, 0), self.current_block)
        if name == "exit":
            arg = self._emit_expr_from(self.current_block, expr.args[0])
            self.set_block(arg.block)
            self.inst("call", [arg.value], type=VOID, callee="ExitProcess")
            return ValueFlow(ConstIntOperand(I64, 0), self.current_block)
        if name == "str":
            return self._emit_str_conversion_from(self.current_block, expr.args[0])
        if name == "cstr":
            arg = self._emit_expr_from(self.current_block, expr.args[0])
            self.set_block(arg.block)
            result = self.inst("call", [arg.value, ConstIntOperand(I64, expr.line)], result_type=I64, type=I64, callee="__ep_cstr")
            return ValueFlow(ValueOperand(result), self.current_block)
        if name in ("i64", "u64", "bool"):
            return self._emit_expr_from(self.current_block, expr.args[0])
        if name == "u8":
            arg = self._emit_expr_from(self.current_block, expr.args[0])
            self.set_block(arg.block)
            return ValueFlow(self._emit_truncating_uint_conversion_value(arg.value, 255), self.current_block)
        if name == "bytes":
            arg = self._emit_expr_from(self.current_block, expr.args[0])
            self.set_block(arg.block)
            return ValueFlow(arg.value, self.current_block)
        if name == "read_file":
            arg = self._emit_expr_from(self.current_block, expr.args[0])
            self.set_block(arg.block)
            result = self.inst("call", [arg.value, ConstIntOperand(I64, expr.line)], result_type=ptr(), type=ptr(), callee="__ep_read_file")
            return ValueFlow(ValueOperand(result), self.current_block)
        if name == "write_file":
            args = self._emit_arg_flows_from(self.current_block, expr.args)
            args.value.append(ConstIntOperand(I64, expr.line))
            result = self.inst("call", args.value, result_type=I64, type=I64, callee="__ep_write_file")
            return ValueFlow(ValueOperand(result), self.current_block)
        if name == "push":
            dst_type = self._infer_type(expr.args[0])
            dst = self._emit_expr_from(self.current_block, expr.args[0])
            rest = self._emit_arg_flows_from(dst.block, expr.args[1:])
            args = [dst.value, *rest.value]
            if self._is_u8_array_type(dst_type):
                self.inst("call", args, type=VOID, callee="__ep_slice_u8_push")
            elif self._is_i64_array_type(dst_type):
                self.inst("call", args, type=VOID, callee="__ep_slice_i64_push")
            else:
                self.inst("call", args, type=VOID, callee="__ep_slice_ptr_push")
            return ValueFlow(ConstIntOperand(I64, 0), self.current_block)
        if name in ("len", "cap"):
            base_type = self._infer_type(expr.args[0])
            base = self._emit_expr_from(self.current_block, expr.args[0])
            self.set_block(base.block)
            struct_name = self._layout_struct_name(base_type)
            if struct_name is None:
                raise MirCodegenError(f"{name} expects an aggregate pointer")
            return ValueFlow(self._load_field(base.value, struct_name, name, result_type=I64), self.current_block)
        if name == "extend":
            dst_type = self._infer_type(expr.args[0])
            helper = self._array_extend_helper(dst_type)
            if helper is None:
                raise MirCodegenError("extend expects supported array type")
            dst = self._emit_expr_from(self.current_block, expr.args[0])
            src = self._emit_expr_from(dst.block, expr.args[1])
            self.set_block(src.block)
            self.inst("call", [dst.value, src.value], type=VOID, callee=helper)
            return ValueFlow(ConstIntOperand(I64, 0), self.current_block)
        raise MirCodegenError(f"unsupported builtin call: {name}")

    def _emit_dot_call_from(self, in_block, expr):
        self.set_block(in_block)
        if (
            isinstance(expr.object, FieldAccessNode)
            and isinstance(expr.object.object, VarNode)
            and expr.object.object.name == "os"
        ):
            call = CallNode(name=expr.name, args=expr.args, namespace="os", dll=expr.object.field, line=expr.line)
            return self._emit_os_call_from(self.current_block, call)
        receiver_type = self._infer_type(expr.object)
        if receiver_type.kind == "array":
            if expr.name == "push":
                dst = self._emit_expr_from(self.current_block, expr.object)
                value = self._emit_expr_from(dst.block, expr.args[0])
                self.set_block(value.block)
                args = [dst.value, value.value]
                if self._is_u8_array_type(receiver_type):
                    self.inst("call", args, type=VOID, callee="__ep_slice_u8_push")
                elif self._is_i64_array_type(receiver_type):
                    self.inst("call", args, type=VOID, callee="__ep_slice_i64_push")
                else:
                    self.inst("call", args, type=VOID, callee="__ep_slice_ptr_push")
                return ValueFlow(ConstIntOperand(I64, 0), self.current_block)
            if expr.name == "pop":
                helper, ret_type = self._array_pop_helper(receiver_type)
                if helper is None:
                    raise MirCodegenError("pop expects supported array type")
                dst = self._emit_expr_from(self.current_block, expr.object)
                self.set_block(dst.block)
                result = self.inst("call", [dst.value], result_type=ret_type, type=ret_type, callee=helper)
                return ValueFlow(ValueOperand(result), self.current_block)
            if expr.name == "extend":
                helper = self._array_extend_helper(receiver_type)
                if helper is None:
                    raise MirCodegenError("extend expects supported array type")
                dst = self._emit_expr_from(self.current_block, expr.object)
                src = self._emit_expr_from(dst.block, expr.args[0])
                self.set_block(src.block)
                self.inst("call", [dst.value, src.value], type=VOID, callee=helper)
                return ValueFlow(ConstIntOperand(I64, 0), self.current_block)
        if receiver_type.kind == "named":
            method_symbol = f"{receiver_type.name}__{expr.name}"
            call = CallNode(name=method_symbol, args=[expr.object] + expr.args, line=expr.line)
            return self._emit_user_call_from(self.current_block, call)
        raise MirCodegenError(f"unsupported dot call: {expr.name}")

    def _emit_user_call(self, expr):
        return self._emit_user_call_from(self.ensure_insertable(), expr).value

    def _emit_user_call_from(self, in_block, expr):
        self.set_block(in_block)
        name = expr.name
        if name not in self.func_sigs:
            raise MirCodegenError(f"unsupported call: {name}")
        args = self._emit_arg_flows_from(self.current_block, expr.args)
        sig = self.func_sigs[name]
        result_type = None if sig.ret == VOID else sig.ret
        result = self.inst("call", args.value, result_type=result_type, type=sig.ret, callee=name)
        return ValueFlow(ValueOperand(result) if result is not None else ConstIntOperand(I64, 0), self.current_block)

    def _infer_type(self, expr):
        return self._resolved_type(expr)

    def _emit_subscript(self, expr):
        return self._emit_subscript_from(self.ensure_insertable(), expr).value

    def _emit_subscript_from(self, in_block, expr):
        base_type = self._infer_type(expr.base)
        base = self._emit_expr_from(in_block, expr.base)
        index = self._emit_expr_from(base.block, expr.index)
        self.set_block(index.block)
        if self._is_i64_array_type(base_type):
            result = self.inst("call", [base.value, index.value], result_type=I64, type=I64, callee="__ep_slice_i64_get")
            return ValueFlow(ValueOperand(result), self.current_block)
        elem = self._array_struct_elem(base_type)
        if elem is not None:
            result = self.inst("call", [base.value, index.value], result_type=ptr(), type=ptr(), callee="__ep_slice_ptr_get")
            return ValueFlow(ValueOperand(result), self.current_block)
        if self._is_ptr_type(base_type):
            elem_type = self._epic_pointee_type(base_type.elem)
            addr = self.inst("gep", [base.value, index.value], result_type=ptr(), type=elem_type)
            load_type = I8 if base_type.elem in (et.I8, et.U8) else elem_type
            result_type = I64 if load_type == I8 else elem_type
            result = self.inst("load", [ValueOperand(addr)], result_type=result_type, type=load_type)
            return ValueFlow(ValueOperand(result), self.current_block)
        result = self.inst("call", [base.value, index.value], result_type=I64, type=I64, callee="__ep_slice_u8_get")
        return ValueFlow(ValueOperand(result), self.current_block)

    def _emit_array_literal(self, expr):
        return self._emit_array_literal_from(self.ensure_insertable(), expr).value

    def _emit_array_literal_from(self, in_block, expr):
        self.set_block(in_block)
        epic_type = self._resolved_type(expr)
        arr_type = self._type(epic_type)
        if self._is_i64_array_type(epic_type):
            result = self.inst("call", [ConstIntOperand(I64, len(expr.values))], result_type=arr_type, type=ptr(), callee="__ep_slice_i64_new")
            arr = ValueOperand(result)
            block = self.current_block
            for idx, value_expr in enumerate(expr.values):
                value = self._emit_expr_from(block, value_expr)
                self.set_block(value.block)
                self.inst("call", [arr, ConstIntOperand(I64, idx), value.value], type=VOID, callee="__ep_slice_i64_set")
                block = self.current_block
            return ValueFlow(arr, self.current_block)
        if not self._is_u8_array_type(epic_type):
            raise MirCodegenError(f"unsupported array literal element type: {expr.elem_type}")
        result = self.inst("call", [ConstIntOperand(I64, len(expr.values)), ConstIntOperand(I64, len(expr.values))], result_type=ptr(), type=ptr(), callee="__ep_slice_u8_alloc")
        arr = ValueOperand(result)
        block = self.current_block
        for idx, value_expr in enumerate(expr.values):
            value = self._emit_expr_from(block, value_expr)
            self.set_block(value.block)
            self.inst("call", [arr, ConstIntOperand(I64, idx), value.value], type=VOID, callee="__ep_slice_u8_set")
            block = self.current_block
        return ValueFlow(arr, self.current_block)

    def _emit_new_array(self, expr):
        return self._emit_new_array_from(self.ensure_insertable(), expr).value

    def _emit_new_array_from(self, in_block, expr):
        self.set_block(in_block)
        count_flow = self._emit_expr_from(self.current_block, expr.count) if expr.count is not None else ValueFlow(ConstIntOperand(I64, 0), self.current_block)
        self.set_block(count_flow.block)
        count = count_flow.value
        epic_type = self._resolved_type(expr)
        arr_type = self._type(epic_type)
        if self._is_u8_array_type(epic_type):
            result = self.inst("call", [count, count], result_type=ptr(), type=ptr(), callee="__ep_slice_u8_alloc")
            return ValueFlow(ValueOperand(result), self.current_block)
        if self._is_i64_array_type(epic_type):
            result = self.inst("call", [count], result_type=arr_type, type=ptr(), callee="__ep_slice_i64_new")
            return ValueFlow(ValueOperand(result), self.current_block)
        if self._array_struct_elem(epic_type) is not None:
            result = self.inst("call", [count], result_type=arr_type, type=ptr(), callee="__ep_slice_ptr_new")
            return ValueFlow(ValueOperand(result), self.current_block)
        raise MirCodegenError(f"unsupported array element type: {expr.elem_type}")

    def _emit_slice(self, expr):
        return self._emit_slice_from(self.ensure_insertable(), expr).value

    def _emit_slice_from(self, in_block, expr):
        base_type = self._infer_type(expr.base)
        base = self._emit_expr_from(in_block, expr.base)
        start = self._emit_expr_from(base.block, expr.start)
        end = self._emit_expr_from(start.block, expr.end)
        self.set_block(end.block)
        if base_type == et.STR:
            result = self.inst("call", [base.value, start.value, end.value], result_type=ptr(), type=ptr(), callee="__ep_str_slice")
            return ValueFlow(ValueOperand(result), self.current_block)
        if self._is_u8_array_type(base_type):
            result = self.inst("call", [base.value, start.value, end.value], result_type=ptr(), type=ptr(), callee="__ep_slice_u8_slice")
            return ValueFlow(ValueOperand(result), self.current_block)
        raise MirCodegenError("slice only supports str and u8[]")

    def _emit_struct_init(self, expr):
        return self._emit_struct_init_from(self.ensure_insertable(), expr).value

    def _emit_struct_init_from(self, in_block, expr):
        self.set_block(in_block)
        if expr.type_name not in self.structs:
            raise MirCodegenError(f"unknown struct: {expr.type_name}")
        obj = self._alloc_struct(expr.type_name)
        block = self.current_block
        for field, value_expr in expr.fields:
            value = self._emit_expr_from(block, value_expr)
            self.set_block(value.block)
            self._store_field(obj, expr.type_name, field, value.value)
            block = self.current_block
        return ValueFlow(obj, self.current_block)

    def _emit_union_init_from(self, in_block, expr):
        self.set_block(in_block)
        if expr.type_name not in self.union_defs:
            raise MirCodegenError(f"unknown union: {expr.type_name}")
        payload_type = self._infer_type(expr.payload)
        if payload_type.kind != "named" or payload_type.name not in self.union_tags[expr.type_name]:
            raise MirCodegenError(f"invalid union payload for {expr.type_name}")
        payload = self._emit_expr_from(self.current_block, expr.payload)
        self.set_block(payload.block)
        wrapper = self._alloc_struct(expr.type_name)
        self._store_field(wrapper, expr.type_name, "tag", ConstIntOperand(I64, self.union_tags[expr.type_name][payload_type.name]))
        self._store_field(wrapper, expr.type_name, "payload", payload.value)
        return ValueFlow(wrapper, self.current_block)

    def _emit_field_access(self, expr):
        return self._emit_field_access_from(self.ensure_insertable(), expr).value

    def _emit_field_access_from(self, in_block, expr):
        base_type = self._infer_type(expr.object)
        base = self._emit_expr_from(in_block, expr.object)
        self.set_block(base.block)
        if base_type.kind == "named" and base_type.name in self.union_defs:
            try:
                self._union_common_field_layout(base_type.name, expr.field)
            except MirCodegenError:
                raise MirCodegenError("field access base must be struct")
            return ValueFlow(self._load_union_common_field(base.value, base_type.name, expr.field), self.current_block)
        struct_name = self._layout_struct_name(base_type)
        try:
            self.structs[struct_name].field(expr.field)
        except KeyError:
            raise MirCodegenError(f"unknown field: {expr.field}")
        return ValueFlow(self._load_field(base.value, struct_name, expr.field), self.current_block)

    def _emit_os_call(self, expr):
        return self._emit_os_call_from(self.ensure_insertable(), expr).value

    def _emit_os_call_from(self, in_block, expr):
        self.set_block(in_block)
        signature = next(
            (
                MirSignature(params, ret)
                for dll, name, params, ret in WINAPI_IMPORTS
                if dll == expr.dll and name == expr.name
            ),
            None,
        )
        if signature is None:
            raise MirCodegenError(f"unsupported os call: os.{expr.dll}.{expr.name}")
        args = self._emit_arg_flows_from(self.current_block, expr.args)
        result_type = None if signature.ret == VOID else signature.ret
        result = self.inst("call", args.value, result_type=result_type, type=signature.ret, callee=expr.name)
        return ValueFlow(ValueOperand(result) if result is not None else ConstIntOperand(I64, 0), self.current_block)

    def _emit_truncating_uint_conversion_value(self, value, mask):
        return ValueOperand(self.inst("and", [value, ConstIntOperand(I64, mask)], result_type=I64))

    def _emit_truncating_uint_conversion(self, expr, mask):
        flow = self._emit_expr_from(self.ensure_insertable(), expr)
        self.set_block(flow.block)
        return self._emit_truncating_uint_conversion_value(flow.value, mask)

    def _emit_str_conversion(self, expr):
        return self._emit_str_conversion_from(self.ensure_insertable(), expr).value

    def _emit_str_conversion_from(self, in_block, expr):
        self.set_block(in_block)
        source_type = self._resolved_type(expr)
        typ = self._infer_type(expr)
        if typ == et.STR:
            return self._emit_expr_from(self.current_block, expr)
        arg = self._emit_expr_from(self.current_block, expr)
        self.set_block(arg.block)
        if typ == et.BOOL:
            result = self.inst("call", [arg.value], result_type=ptr(), type=ptr(), callee="__ep_str_from_bool")
            return ValueFlow(ValueOperand(result), self.current_block)
        if self._is_u8_array_type(typ):
            return ValueFlow(arg.value, self.current_block)
        if source_type == et.U64:
            result = self.inst("call", [arg.value], result_type=ptr(), type=ptr(), callee="__ep_str_from_u64")
            return ValueFlow(ValueOperand(result), self.current_block)
        result = self.inst("call", [arg.value], result_type=ptr(), type=ptr(), callee="__ep_str_from_i64")
        return ValueFlow(ValueOperand(result), self.current_block)

    def _emit_fstring(self, expr):
        return self._emit_fstring_from(self.ensure_insertable(), expr).value

    def _emit_fstring_from(self, in_block, expr):
        self.set_block(in_block)
        out = None
        block = self.current_block
        for part in expr.parts:
            if isinstance(part, FStringTextPart):
                if part.value:
                    piece = SymbolOperand(ptr(), self._string_label(part.value))
                else:
                    continue
            elif isinstance(part, FStringExprPart):
                piece_flow = self._emit_str_conversion_from(block, part.expr)
                piece = piece_flow.value
                block = piece_flow.block
                self.set_block(block)
            else:
                raise MirCodegenError(f"unsupported f-string part: {part}")
            if out is None:
                out = piece
            else:
                result = self.inst("call", [out, piece], result_type=ptr(), type=ptr(), callee="__ep_str_cat")
                out = ValueOperand(result)
            block = self.current_block
        if out is None:
            return ValueFlow(SymbolOperand(ptr(), self._string_label("")), self.current_block)
        return ValueFlow(out, self.current_block)

    def _coerce_print_arg(self, expr):
        if self._infer_type(expr) == et.STR:
            return self._emit_expr(expr)
        return self._emit_str_conversion(expr)

    def _zero_value(self, typ):
        if typ.kind == "ptr":
            return ConstNullOperand()
        return ConstIntOperand(typ, 0)

    def _string_label(self, text):
        if text not in self.strings:
            self.string_counter += 1
            label = f"str.{self.string_counter}"
            self.strings[text] = label
            self.program.globals.append(MirGlobal(label, ptr(), text))
        return self.strings[text]

    def _global_label(self, name):
        return f"__epg_{name}"

    def _emit_global_lets(self, ast):
        for glob in ast.globals:
            typ = self._type(glob.resolved_type)
            label = self._global_label(glob.name)
            self.globals[glob.name] = typ
            self.program.globals.append(MirGlobal(label, typ, None))

    def _emit_global_init_function(self, ast):
        if not ast.globals:
            return
        self.begin_function("__ep_global_init", [], VOID)
        self.local_scopes = [{}]
        self.local_type_scopes = [{}]
        entry = self.new_block("entry")
        block = entry
        for glob in ast.globals:
            value = self._expr_from(block, glob.value)
            self.set_block(value.block)
            self.inst("store", [value.value, SymbolOperand(ptr(), self._global_label(glob.name))])
            block = self.current_block
        self.ret(block)
        self.program.functions.append(self.fn)

    def _make_struct_layout(self, name, fields, size=None):
        layout_fields = [MirField(field_name, field_type, offset) for field_name, field_type, offset in fields]
        if size is None:
            size = max((field.offset + 8 for field in layout_fields), default=1)
        return MirStruct(name, layout_fields, size)

    def _slice_layout(self, name):
        return self._make_struct_layout(
            name,
            [("data", ptr(), 0), ("len", I64, 8), ("cap", I64, 16)],
            size=24,
        )

    def _compute_struct_layouts(self, ast):
        self.structs = {}
        self.union_defs = {union.name: union.members for union in ast.unions}
        self.union_tags = {union.name: {member: idx for idx, member in enumerate(union.members, start=1)} for union in ast.unions}
        for struct_name in ("str", "_slice_u8", "_slice_i64", "_slice_str"):
            self.structs[struct_name] = self._slice_layout(struct_name)
        for struct_node in ast.structs:
            self.structs[struct_node.name] = MirStruct(struct_node.name, [], 0)
        for union_node in ast.unions:
            self.structs[union_node.name] = MirStruct(union_node.name, [], 0)
        for struct_node in ast.structs:
            fields = []
            offset = 0
            for field in struct_node.fields:
                fields.append((field.name, self._type(field.resolved_type), offset))
                offset += 8
            self.structs[struct_node.name] = self._make_struct_layout(struct_node.name, fields, size=max(offset, 1))
        for union_node in ast.unions:
            self.structs[union_node.name] = self._make_struct_layout(
                union_node.name,
                [("tag", I64, 0), ("payload", ptr(), 8)],
                size=16,
            )
        for struct_name in list(self.structs):
            self.structs[f"_slice_{struct_name}"] = self._slice_layout(f"_slice_{struct_name}")
        self.program.structs = self.structs



def ast_to_mir(ast):
    assert_typed_program(ast)
    return MirCodegen().emit_program(ast)
