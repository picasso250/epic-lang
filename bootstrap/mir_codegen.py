"""AST -> Epic MIR codegen for the initial machine-backend path."""

from dataclasses import dataclass

import epic_types as et
from sema import assert_typed_program
from ast_nodes import *
from mir import (
    BOOL,
    I8,
    I64,
    VOID,
    Br,
    CondBr,
    ConstBoolOperand,
    ConstIntOperand,
    ConstNullOperand,
    I32,
    MirBlock,
    MirExtern,
    MirField,
    MirFunction,
    MirGlobal,
    MirImport,
    MirInst,
    MirParam,
    MirProgram,
    MirSignature,
    MirStruct,
    MirValue,
    Ret,
    SymbolOperand,
    ValueOperand,
    ptr,
    struct as mir_struct,
    validate,
)
from mir_runtime_helpers import inject_all_mir_helpers


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
    ("kernel32", "CreateProcessA", [], I64),
    ("kernel32", "WaitForSingleObject", [I64, I64], I64),
    ("kernel32", "GetExitCodeProcess", [I64, I64], I64),
    ("kernel32", "GetCommandLineA", [], I64),
    ("user32", "MessageBoxA", [I64, I64, I64, I64], I64),
]


class MirCodegen:
    def __init__(self):
        self.program = MirProgram()
        self.func_sigs = {}
        self.fn = None
        self.block = None
        self.locals = {}
        self.local_types = {}
        self.value_counter = 0
        self.block_counter = 0
        self.strings = {}
        self.string_counter = 0
        self.structs = {}
        self.loop_stack = []

    def emit_program(self, ast):
        self._compute_struct_layouts(ast)
        self.func_sigs = {
            fn.name: MirSignature([self._type(p.resolved_type) for p in fn.params], self._type(fn.resolved_type))
            for fn in ast.funcs
        }
        for dll, name, params, ret in WINAPI_IMPORTS:
            self.program.imports.append(MirImport(name, MirSignature(params, ret), f"{dll}.dll"))
        if "__ep_str_from_i64" not in self.func_sigs:
            self.program.externs.append(MirExtern("__ep_str_from_i64", MirSignature([I64], ptr())))
        if "__ep_str_from_u64" not in self.func_sigs:
            self.program.externs.append(MirExtern("__ep_str_from_u64", MirSignature([I64], ptr())))
        if "__ep_str_from_bool" not in self.func_sigs:
            self.program.externs.append(MirExtern("__ep_str_from_bool", MirSignature([BOOL], ptr())))
        self.program.externs.append(MirExtern("__ep_str_from_slice_u8", MirSignature([ptr()], ptr())))
        self.program.externs.append(MirExtern("__ep_str_cat", MirSignature([ptr(), ptr()], ptr())))
        if "__ep_str_eq" not in self.func_sigs:
            self.program.externs.append(MirExtern("__ep_str_eq", MirSignature([ptr(), ptr()], BOOL)))
        if "__ep_str_slice" not in self.func_sigs:
            self.program.externs.append(MirExtern("__ep_str_slice", MirSignature([ptr(), I64, I64], ptr())))
        self.program.externs.append(MirExtern("__ep_slice_u8_from_str", MirSignature([ptr()], ptr())))
        self.program.externs.append(MirExtern("__ep_cstr", MirSignature([ptr(), I64], I64)))
        self.program.externs.append(MirExtern("__ep_read_file", MirSignature([ptr(), I64], ptr())))
        self.program.externs.append(MirExtern("__ep_write_file", MirSignature([ptr(), ptr(), I64], I64)))
        self.program.externs.append(MirExtern("__ep_system_cmd", MirSignature([ptr(), I64], I64)))
        self.program.externs.append(MirExtern("__ep_slice_u8_alloc", MirSignature([I64, I64], ptr())))
        self.program.externs.append(MirExtern("__ep_slice_u8_get", MirSignature([ptr(), I64], I64)))
        self.program.externs.append(MirExtern("__ep_slice_u8_set", MirSignature([ptr(), I64, I64], VOID)))
        self.program.externs.append(MirExtern("__ep_slice_u8_push", MirSignature([ptr(), I64], VOID)))
        self.program.externs.append(MirExtern("__ep_slice_u8_slice", MirSignature([ptr(), I64, I64], ptr())))
        self.program.externs.append(MirExtern("__ep_slice_i64_new", MirSignature([I64], ptr())))
        self.program.externs.append(MirExtern("__ep_slice_i64_get", MirSignature([ptr(), I64], I64)))
        self.program.externs.append(MirExtern("__ep_slice_i64_set", MirSignature([ptr(), I64, I64], VOID)))
        self.program.externs.append(MirExtern("__ep_slice_i64_push", MirSignature([ptr(), I64], VOID)))
        self.program.externs.append(MirExtern("__ep_slice_ptr_new", MirSignature([I64], ptr())))
        self.program.externs.append(MirExtern("__ep_slice_ptr_get", MirSignature([ptr(), I64], ptr())))
        self.program.externs.append(MirExtern("__ep_slice_ptr_set", MirSignature([ptr(), I64, ptr()], VOID)))
        self.program.externs.append(MirExtern("__ep_slice_ptr_push", MirSignature([ptr(), ptr()], VOID)))
        self.program.externs.append(MirExtern("__ep_slice_u8_extend", MirSignature([ptr(), ptr()], VOID)))
        self.program.externs.append(MirExtern("__ep_map_str_i64_new", MirSignature([], ptr())))
        self.program.externs.append(MirExtern("__ep_map_str_i64_get", MirSignature([ptr(), ptr()], I64)))
        self.program.externs.append(MirExtern("__ep_map_str_i64_set", MirSignature([ptr(), ptr(), I64], VOID)))
        self.program.externs.append(MirExtern("__ep_map_str_i64_has", MirSignature([ptr(), ptr()], BOOL)))
        self.program.externs.append(MirExtern("__ep_map_str_i64_del", MirSignature([ptr(), ptr()], BOOL)))
        self.program.externs.append(MirExtern("__ep_map_str_bool_new", MirSignature([], ptr())))
        self.program.externs.append(MirExtern("__ep_map_str_bool_get", MirSignature([ptr(), ptr()], BOOL)))
        self.program.externs.append(MirExtern("__ep_map_str_bool_set", MirSignature([ptr(), ptr(), BOOL], VOID)))
        self.program.externs.append(MirExtern("__ep_map_str_bool_has", MirSignature([ptr(), ptr()], BOOL)))
        self.program.externs.append(MirExtern("__ep_map_str_bool_del", MirSignature([ptr(), ptr()], BOOL)))
        self.program.externs.append(MirExtern("__ep_map_str_str_new", MirSignature([], ptr())))
        self.program.externs.append(MirExtern("__ep_map_str_str_get", MirSignature([ptr(), ptr()], ptr())))
        self.program.externs.append(MirExtern("__ep_map_str_str_set", MirSignature([ptr(), ptr(), ptr()], VOID)))
        self.program.externs.append(MirExtern("__ep_map_str_str_has", MirSignature([ptr(), ptr()], BOOL)))
        self.program.externs.append(MirExtern("__ep_map_str_str_del", MirSignature([ptr(), ptr()], BOOL)))
        self.program.externs.append(MirExtern("__ep_print_str", MirSignature([ptr()], VOID)))
        self.program.externs.append(MirExtern("__ep_print_newline", MirSignature([], VOID)))
        self.program.externs.append(MirExtern("__epx_alloc", MirSignature([I64], ptr())))
        self.program.globals.append(MirGlobal("argv", ptr(), None))
        for fn in ast.funcs:
            self.program.functions.append(self._emit_function(fn))
        inject_all_mir_helpers(self.program)
        validate(self.program)
        return self.program

    def _emit_function(self, ast_fn):
        self.fn = MirFunction(
            ast_fn.name,
            [MirParam(p.name, self._type(p.resolved_type)) for p in ast_fn.params],
            self._type(ast_fn.resolved_type),
        )
        self.locals = {}
        self.local_types = {}
        self.value_counter = 0
        self.block_counter = 0
        entry = self._new_block("entry")
        for param in self.fn.params:
            self._set_insert_block(entry)
            addr = self._alloc_local(param.name, param.type)
            self._inst("store", [ValueOperand(param.value), ValueOperand(addr)])
            entry = self.block
        body = self._emit_block_from(entry, ast_fn.body)
        if body.reachable:
            if self.fn.return_type == VOID:
                self._terminate_block(body.block, Ret())
            else:
                self._terminate_block(body.block, Ret(ConstIntOperand(self.fn.return_type, 0)))
        return self.fn

    def _type(self, typ):
        if isinstance(typ, et.EpicType):
            return self._epic_type(typ)
        if typ is None:
            raise MirCodegenError("missing resolved type")
        if typ == "void":
            return VOID
        if typ in ("i64", "u64", "i32", "u32", "u8", "bool"):
            return BOOL if typ == "bool" else I64
        if typ == "&str":
            return ptr()
        if typ in ("u8[]", "&_slice_u8"):
            return ptr()
        if typ in ("i64[]", "u64[]", "i32[]", "u32[]", "&_slice_i64"):
            return ptr()
        if typ in ("map[str]i64", "&_map_str_i64"):
            return ptr()
        if typ in ("map[str]bool", "&_map_str_bool"):
            return ptr()
        if typ in ("map[str]str", "&_map_str_str"):
            return ptr()
        if isinstance(typ, str) and typ.endswith("[]") and typ[:-2] in self.structs:
            return ptr()
        if typ in self.structs:
            return ptr()
        if isinstance(typ, str) and typ.startswith("&") and typ[1:] in self.structs:
            return ptr()
        raise MirCodegenError(f"machine MIR does not support type yet: {typ}")

    def _epic_type(self, typ):
        if typ == et.VOID:
            return VOID
        if typ == et.BOOL:
            return BOOL
        if typ in (et.I64, et.U64, et.I32, et.U32, et.I8, et.U8):
            return I64
        if typ == et.STR:
            return ptr()
        if typ.kind == "array":
            elem = typ.elem
            if elem in (et.I8, et.U8):
                return ptr()
            if elem in (et.I64, et.U64, et.I32, et.U32, et.BOOL):
                return ptr()
            if elem == et.STR:
                return ptr()
            if elem is not None and elem.kind == "named":
                return ptr()
        if typ.kind == "map":
            if typ.elem == et.I64:
                return ptr()
            if typ.elem == et.BOOL:
                return ptr()
            if typ.elem == et.STR:
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
        if typ in (et.I64, et.U64, et.I32, et.U32):
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
            raise MirCodegenError(f"untyped AST node reached MIR codegen: {type(node).__name__}")
        return typ

    def _expr_mir_type(self, expr):
        return self._type(self._resolved_type(expr))

    def _new_value(self, typ, hint="v"):
        self.value_counter += 1
        return MirValue(f"{hint}{self.value_counter}", typ)

    def _new_block(self, prefix):
        self.block_counter += 1
        block = MirBlock(f"{prefix}{self.block_counter}")
        self.fn.blocks.append(block)
        return block

    def _ensure_insertable(self, block=None):
        block = self.block if block is None else block
        if block is None:
            raise MirCodegenError("no reachable MIR insertion block")
        if block.terminator is not None:
            raise MirCodegenError(f"cannot emit after terminator in block {block.name}")
        return block

    def _set_insert_block(self, block):
        self.block = self._ensure_insertable(block)
        return self.block

    def _terminate_block(self, block, terminator):
        block = self._ensure_insertable(block)
        block.terminator = terminator
        if self.block is block:
            self.block = None
        return BlockFlow(False, None)

    def _reachable(self, block):
        return BlockFlow(True, self._ensure_insertable(block))

    def _unreachable(self):
        return BlockFlow(False, None)

    def _expr_from(self, block, expr):
        self._set_insert_block(block)
        value = self._emit_expr(expr)
        return ValueFlow(value, self._ensure_insertable(self.block))

    def _inst(self, op, operands=None, result_type=None, type=None, callee=None):
        block = self._ensure_insertable()
        result = self._new_value(result_type, op.replace(".", "_")) if result_type is not None else None
        inst = MirInst(op, operands or [], result=result, type=type, callee=callee)
        block.instructions.append(inst)
        return result

    def _alloc_local(self, name, typ):
        block = self._ensure_insertable()
        addr = self._new_value(ptr(), f"{name}.addr")
        block.instructions.append(MirInst("alloca", result=addr, type=typ))
        self.locals[name] = addr
        self.local_types[name] = typ
        return addr

    def _alloc_struct(self, struct_name):
        size_ptr = self._inst(
            "gep",
            [ConstNullOperand(), ConstIntOperand(I64, 1)],
            result_type=ptr(),
            type=mir_struct(struct_name),
        )
        size = self._inst("ptrtoint", [ValueOperand(size_ptr)], result_type=I64, type=I64)
        obj = self._inst(
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
        addr = self._inst(
            "gep",
            [base, ConstIntOperand(I64, 0), ConstIntOperand(I32, self._field_index(struct_name, field))],
            result_type=ptr(),
            type=mir_struct(struct_name),
        )
        return ValueOperand(addr)

    def _load_field(self, base, struct_name, field, result_type=None):
        field_type = result_type or self.structs[struct_name].field(field).type
        addr = self._field_addr(base, struct_name, field, result_type=field_type)
        value = self._inst("load", [addr], result_type=field_type, type=field_type)
        return ValueOperand(value)

    def _store_field(self, base, struct_name, field, value):
        addr = self._field_addr(base, struct_name, field)
        self._inst("store", [value, addr])

    def _layout_struct_name(self, typ):
        """Return the runtime layout struct name for an EpicType."""
        if not isinstance(typ, et.EpicType):
            return None
        if typ == et.STR:
            return "str"
        if typ.kind == "array":
            if typ.elem in (et.I8, et.U8):
                return "_slice_u8"
            if typ.elem in (et.I64, et.U64, et.I32, et.U32, et.BOOL):
                return "_slice_i64"
            if typ.elem == et.STR:
                return "_slice_str"
            if typ.elem is not None and typ.elem.kind == "named":
                return f"_slice_{typ.elem.name}"
        if typ.kind == "map":
            suffix = self._map_suffix(typ)
            return f"_map_str_{suffix}" if suffix is not None else None
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

    def _map_suffix(self, typ):
        if not isinstance(typ, et.EpicType) or typ.kind != "map":
            return None
        if typ.elem == et.I64:
            return "i64"
        if typ.elem == et.BOOL:
            return "bool"
        if typ.elem == et.STR:
            return "str"
        return None

    def _map_value_type(self, typ):
        suffix = self._map_suffix(typ)
        if suffix == "i64":
            return I64
        if suffix == "bool":
            return BOOL
        if suffix == "str":
            return ptr()
        return None

    def _map_helper(self, typ, op):
        suffix = self._map_suffix(typ)
        if suffix is None:
            return None
        return f"__ep_map_str_{suffix}_{op}"

    def _is_slice_type(self, typ):
        return isinstance(typ, et.EpicType) and typ.kind == "array"

    def _is_u8_array_type(self, typ):
        return isinstance(typ, et.EpicType) and typ.kind == "array" and typ.elem in (et.I8, et.U8)

    def _is_i64_array_type(self, typ):
        return isinstance(typ, et.EpicType) and typ.kind == "array" and typ.elem in (et.I64, et.U64, et.I32, et.U32, et.BOOL)

    def _is_ptr_type(self, typ):
        return isinstance(typ, et.EpicType) and typ.kind == "ptr"

    def _emit_block(self, block):
        flow = self._emit_block_from(self._ensure_insertable(), block)
        self.block = flow.block if flow.reachable else None
        return flow

    def _emit_block_from(self, in_block, block):
        flow = self._reachable(in_block)
        for stmt in block.stmts:
            if not flow.reachable:
                return flow
            flow = self._emit_stmt_from(flow.block, stmt)
        return flow

    def _emit_stmt(self, stmt):
        flow = self._emit_stmt_from(self._ensure_insertable(), stmt)
        self.block = flow.block if flow.reachable else None
        return flow

    def _emit_stmt_from(self, in_block, stmt):
        self._set_insert_block(in_block)
        if isinstance(stmt, ExprStmtNode):
            value = self._expr_from(in_block, stmt.expr)
            return self._reachable(value.block)
        elif isinstance(stmt, LetNode):
            typ = self._type(stmt.resolved_type)
            addr = self._alloc_local(stmt.name, typ)
            init_block = self.block
            value = self._expr_from(init_block, stmt.value) if stmt.value is not None else ValueFlow(self._zero_value(typ), init_block)
            self._set_insert_block(value.block)
            self._inst("store", [value.value, ValueOperand(addr)])
            return self._reachable(self.block)
        elif isinstance(stmt, AssignNode):
            if stmt.name not in self.locals:
                raise MirCodegenError(f"undefined variable: {stmt.name}")
            value = self._expr_from(in_block, stmt.value)
            self._set_insert_block(value.block)
            self._inst("store", [value.value, ValueOperand(self.locals[stmt.name])])
            return self._reachable(self.block)
        elif isinstance(stmt, ReturnNode):
            if stmt.expr is None:
                return self._terminate_block(in_block, Ret())
            value = self._expr_from(in_block, stmt.expr)
            return self._terminate_block(value.block, Ret(value.value))
        elif isinstance(stmt, IfNode):
            return self._emit_if_from(in_block, stmt)
        elif isinstance(stmt, WhileNode):
            return self._emit_while_from(in_block, stmt)
        elif isinstance(stmt, ForRangeNode):
            return self._emit_for_range_from(in_block, stmt)
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
            self._set_insert_block(value.block)
            struct_name = self._layout_struct_name(base_type)
            if struct_name is None:
                raise MirCodegenError("field assignment base must be a struct pointer")
            self._store_field(base.value, struct_name, stmt.field, value.value)
            return self._reachable(self.block)
        elif isinstance(stmt, SubscriptAssignNode):
            base_type = self._infer_type(stmt.base)
            base = self._expr_from(in_block, stmt.base)
            index = self._expr_from(base.block, stmt.index)
            value = self._expr_from(index.block, stmt.value)
            self._set_insert_block(value.block)
            if self._is_u8_array_type(base_type):
                self._inst("call", [base.value, index.value, value.value], type=VOID, callee="__ep_slice_u8_set")
            elif self._is_i64_array_type(base_type):
                self._inst("call", [base.value, index.value, value.value], type=VOID, callee="__ep_slice_i64_set")
            else:
                callee = self._map_helper(base_type, "set")
                if callee is None:
                    raise MirCodegenError("subscript assignment only supports primitive arrays and maps in machine MIR so far")
                self._inst("call", [base.value, index.value, value.value], type=VOID, callee=callee)
            return self._reachable(self.block)
        elif isinstance(stmt, AssignOpNode):
            if isinstance(stmt.target, VarNode):
                if stmt.target.name not in self.locals:
                    raise MirCodegenError(f"undefined variable: {stmt.target.name}")
                typ = self.local_types[stmt.target.name]
                addr = ValueOperand(self.locals[stmt.target.name])
                current = self._inst("load", [addr], result_type=typ, type=typ)
                rhs = self._expr_from(in_block, stmt.value)
                self._set_insert_block(rhs.block)
                result = self._binary(stmt.op, ValueOperand(current), rhs.value)
                self._inst("store", [result, addr])
                return self._reachable(self.block)
            if isinstance(stmt.target, FieldAccessNode):
                base_type = self._infer_type(stmt.target.object)
                struct_name = self._layout_struct_name(base_type)
                if struct_name is None:
                    raise MirCodegenError("compound field assignment base must be a struct pointer")
                base = self._expr_from(in_block, stmt.target.object)
                self._set_insert_block(base.block)
                addr = self._field_addr(base.value, struct_name, stmt.target.field)
                field_type = self.structs[struct_name].field(stmt.target.field).type
                current = self._inst("load", [addr], result_type=field_type, type=field_type)
                rhs = self._expr_from(self.block, stmt.value)
                self._set_insert_block(rhs.block)
                result = self._binary(stmt.op, ValueOperand(current), rhs.value)
                self._inst("store", [result, addr])
                return self._reachable(self.block)
            if isinstance(stmt.target, SubscriptNode):
                base_type = self._infer_type(stmt.target.base)
                base = self._expr_from(in_block, stmt.target.base)
                index = self._expr_from(base.block, stmt.target.index)
                self._set_insert_block(index.block)
                map_value_type = self._map_value_type(base_type)
                if map_value_type is not None:
                    current = self._inst("call", [base.value, index.value], result_type=map_value_type, type=map_value_type, callee=self._map_helper(base_type, "get"))
                elif self._is_i64_array_type(base_type):
                    current = self._inst("call", [base.value, index.value], result_type=I64, type=I64, callee="__ep_slice_i64_get")
                elif self._is_u8_array_type(base_type):
                    current = self._inst("call", [base.value, index.value], result_type=I64, type=I64, callee="__ep_slice_u8_get")
                else:
                    raise MirCodegenError("compound subscript assignment only supports primitive arrays and maps in machine MIR so far")
                rhs = self._expr_from(self.block, stmt.value)
                self._set_insert_block(rhs.block)
                result = self._binary(stmt.op, ValueOperand(current), rhs.value)
                if map_value_type is not None:
                    self._inst("call", [base.value, index.value, result], type=VOID, callee=self._map_helper(base_type, "set"))
                elif self._is_i64_array_type(base_type):
                    self._inst("call", [base.value, index.value, result], type=VOID, callee="__ep_slice_i64_set")
                else:
                    self._inst("call", [base.value, index.value, result], type=VOID, callee="__ep_slice_u8_set")
                return self._reachable(self.block)
            raise MirCodegenError(f"unsupported compound assignment target: {type(stmt.target).__name__}")
        elif isinstance(stmt, BreakNode):
            if not self.loop_stack:
                raise MirCodegenError("break outside loop")
            return self._terminate_block(in_block, Br(self.loop_stack[-1][1]))
        elif isinstance(stmt, ContinueNode):
            if not self.loop_stack:
                raise MirCodegenError("continue outside loop")
            return self._terminate_block(in_block, Br(self.loop_stack[-1][0]))
        raise MirCodegenError(f"machine MIR does not support stmt yet: {type(stmt).__name__}")

    def _emit_if(self, stmt):
        flow = self._emit_if_from(self._ensure_insertable(), stmt)
        self.block = flow.block if flow.reachable else None
        return flow

    def _emit_if_from(self, in_block, stmt):
        cond = self._expr_from(in_block, stmt.cond)
        then_block = self._new_block("if.then")
        else_block = self._new_block("if.else") if stmt.else_block else None
        end_block = self._new_block("if.end")
        self._terminate_block(cond.block, CondBr(cond.value, then_block.name, else_block.name if else_block else end_block.name))

        then_flow = self._emit_block_from(then_block, stmt.then_block)
        if then_flow.reachable:
            self._terminate_block(then_flow.block, Br(end_block.name))

        if else_block is not None:
            else_flow = self._emit_block_from(else_block, stmt.else_block)
            if else_flow.reachable:
                self._terminate_block(else_flow.block, Br(end_block.name))

        return self._reachable(end_block)

    def _emit_while(self, stmt):
        flow = self._emit_while_from(self._ensure_insertable(), stmt)
        self.block = flow.block if flow.reachable else None
        return flow

    def _emit_while_from(self, in_block, stmt):
        cond_block = self._new_block("while.cond")
        body_block = self._new_block("while.body")
        end_block = self._new_block("while.end")
        self._terminate_block(in_block, Br(cond_block.name))
        self.loop_stack.append((cond_block.name, end_block.name))
        cond = self._expr_from(cond_block, stmt.cond)
        self._terminate_block(cond.block, CondBr(cond.value, body_block.name, end_block.name))
        body_flow = self._emit_block_from(body_block, stmt.body)
        if body_flow.reachable:
            self._terminate_block(body_flow.block, Br(cond_block.name))
        self.loop_stack.pop()
        return self._reachable(end_block)

    def _emit_for_range(self, stmt):
        flow = self._emit_for_range_from(self._ensure_insertable(), stmt)
        self.block = flow.block if flow.reachable else None
        return flow

    def _emit_for_range_from(self, in_block, stmt):
        self._set_insert_block(in_block)
        var_addr = self._alloc_local(stmt.name, I64)
        end_addr = self._alloc_local(f"__{stmt.name}.end{self.value_counter}", I64)
        start = self._expr_from(self.block, stmt.start)
        self._set_insert_block(start.block)
        self._inst("store", [start.value, ValueOperand(var_addr)])
        end_value = self._expr_from(self.block, stmt.end)
        self._set_insert_block(end_value.block)
        self._inst("store", [end_value.value, ValueOperand(end_addr)])

        cond_block = self._new_block("for.cond")
        body_block = self._new_block("for.body")
        inc_block = self._new_block("for.inc")
        end_block = self._new_block("for.end")
        self._terminate_block(self.block, Br(cond_block.name))

        self._set_insert_block(cond_block)
        cur = self._inst("load", [ValueOperand(var_addr)], result_type=I64, type=I64)
        end = self._inst("load", [ValueOperand(end_addr)], result_type=I64, type=I64)
        cond = self._inst("icmp.slt", [ValueOperand(cur), ValueOperand(end)], result_type=BOOL)
        self._terminate_block(cond_block, CondBr(ValueOperand(cond), body_block.name, end_block.name))

        self.loop_stack.append((inc_block.name, end_block.name))
        body_flow = self._emit_block_from(body_block, stmt.body)
        if body_flow.reachable:
            self._terminate_block(body_flow.block, Br(inc_block.name))
        self.loop_stack.pop()

        self._set_insert_block(inc_block)
        cur = self._inst("load", [ValueOperand(var_addr)], result_type=I64, type=I64)
        nxt = self._inst("add", [ValueOperand(cur), ConstIntOperand(I64, 1)], result_type=I64)
        self._inst("store", [ValueOperand(nxt), ValueOperand(var_addr)])
        self._terminate_block(inc_block, Br(cond_block.name))
        return self._reachable(end_block)

    def _emit_assert(self, stmt):
        flow = self._emit_assert_from(self._ensure_insertable(), stmt)
        self.block = flow.block if flow.reachable else None
        return flow

    def _emit_assert_from(self, in_block, stmt):
        cond = self._expr_from(in_block, stmt.cond)
        ok_block = self._new_block("assert.ok")
        fail_block = self._new_block("assert.fail")
        self._terminate_block(cond.block, CondBr(cond.value, ok_block.name, fail_block.name))

        self._set_insert_block(fail_block)
        self._emit_print_text(f"assert line {stmt.line}: ")
        if stmt.message is None:
            self._emit_print_text("assertion failed")
        else:
            self._emit_print_expr(stmt.message)
        self._emit_print_newline()
        self._emit_exit_current_block()
        self._terminate_block(fail_block, self._dummy_return())
        return self._reachable(ok_block)

    def _emit_panic(self, stmt):
        flow = self._emit_panic_from(self._ensure_insertable(), stmt)
        self.block = flow.block if flow.reachable else None
        return flow

    def _emit_panic_from(self, in_block, stmt):
        self._set_insert_block(in_block)
        self._emit_print_text(f"panic line {stmt.line}: ")
        self._emit_print_expr(stmt.message)
        self._emit_print_newline()
        self._emit_exit_current_block()
        return self._terminate_block(self.block, self._dummy_return())

    def _dummy_return(self):
        if self.fn.return_type == VOID:
            return Ret()
        return Ret(ConstIntOperand(self.fn.return_type, 0))

    def _emit_exit_current_block(self, code=1):
        self._inst("call", [ConstIntOperand(I64, code)], type=VOID, callee="ExitProcess")

    def _emit_print_text(self, text):
        self._inst("call", [SymbolOperand(ptr(), self._string_label(text))], type=VOID, callee="__ep_print_str")

    def _emit_print_expr(self, expr):
        self._inst("call", [self._coerce_print_arg(expr)], type=VOID, callee="__ep_print_str")

    def _emit_print_newline(self):
        self._inst("call", [], type=VOID, callee="__ep_print_newline")

    def _emit_truncating_uint_conversion(self, expr, mask):
        value = self._emit_expr(expr)
        return ValueOperand(self._inst("and", [value, ConstIntOperand(I64, mask)], result_type=I64))

    def _emit_truncating_i32_conversion(self, expr):
        value = self._emit_expr(expr)
        shifted = self._inst("shl", [value, ConstIntOperand(I64, 32)], result_type=I64)
        sign_extended = self._inst("sar", [ValueOperand(shifted), ConstIntOperand(I64, 32)], result_type=I64)
        return ValueOperand(sign_extended)

    def _emit_match(self, stmt):
        flow = self._emit_match_from(self._ensure_insertable(), stmt)
        self.block = flow.block if flow.reachable else None
        return flow

    def _emit_match_from(self, in_block, stmt):
        scrutinee = self._expr_from(in_block, stmt.expr)
        self._set_insert_block(scrutinee.block)
        match_addr = self._alloc_local(f"__match{self.value_counter}", scrutinee.value.type)
        self._inst("store", [scrutinee.value, ValueOperand(match_addr)])

        end_block = self._new_block("match.end")
        else_case = next((case for case in stmt.cases if case.is_else), None)
        checks = [(case, self._new_block("match.case")) for case in stmt.cases if not case.is_else]
        else_block = self._new_block("match.else") if else_case is not None else end_block

        check_block = self.block
        next_check_blocks = [self._new_block("match.next") for _ in checks[:-1]]
        for idx, (case, case_block) in enumerate(checks):
            self._set_insert_block(check_block)
            next_block = next_check_blocks[idx] if idx < len(checks) - 1 else else_block
            self._emit_match_check(stmt, match_addr, scrutinee.value.type, case, case_block, next_block)
            if idx < len(checks) - 1:
                check_block = next_check_blocks[idx]

        if not checks:
            self._terminate_block(check_block, Br(else_block.name))

        any_reachable = False
        for case, case_block in checks:
            self._set_insert_block(case_block)
            self._emit_match_bindings(match_addr, case)
            case_flow = self._emit_block_from(case_block, case.body)
            if case_flow.reachable:
                any_reachable = True
                self._terminate_block(case_flow.block, Br(end_block.name))

        if else_case is not None:
            else_flow = self._emit_block_from(else_block, else_case.body)
            if else_flow.reachable:
                any_reachable = True
                self._terminate_block(else_flow.block, Br(end_block.name))
        else:
            any_reachable = True

        return self._reachable(end_block)

    def _emit_match_check(self, stmt, match_addr, match_type, case, case_block, next_block):
        scrut = self._inst("load", [ValueOperand(match_addr)], result_type=match_type, type=match_type)
        scrut_op = ValueOperand(scrut)
        pat = self._emit_expr(case.pattern)
        cond = self._inst("icmp.eq", [scrut_op, pat], result_type=BOOL)
        self._terminate_block(self.block, CondBr(ValueOperand(cond), case_block.name, next_block.name))

    def _emit_match_bindings(self, match_addr, case):
        if not case.bindings:
            return

    def _emit_expr(self, expr):
        return self._emit_expr_from(self._ensure_insertable(), expr).value

    def _emit_expr_from(self, in_block, expr):
        self._set_insert_block(in_block)
        if isinstance(expr, (LiteralNode, CharNode)):
            return ValueFlow(ConstIntOperand(I64, expr.value), self.block)
        if isinstance(expr, BoolNode):
            return ValueFlow(ConstBoolOperand(bool(expr.value)), self.block)
        if isinstance(expr, StringNode):
            return ValueFlow(SymbolOperand(ptr(), self._string_label(expr.value)), self.block)
        if isinstance(expr, FStringNode):
            return self._emit_fstring_from(self.block, expr)
        if isinstance(expr, VarNode):
            if expr.name == "argv":
                return ValueFlow(SymbolOperand(ptr(), "argv"), self.block)
            if expr.name not in self.locals:
                raise MirCodegenError(f"undefined variable: {expr.name}")
            typ = self.local_types[expr.name]
            value = self._inst("load", [ValueOperand(self.locals[expr.name])], result_type=typ, type=typ)
            return ValueFlow(ValueOperand(value), self.block)
        if isinstance(expr, UnaryNode):
            inner = self._emit_expr_from(self.block, expr.expr)
            self._set_insert_block(inner.block)
            if expr.op == "-":
                zero = ConstIntOperand(I64, 0)
                return ValueFlow(ValueOperand(self._inst("sub", [zero, inner.value], result_type=I64)), self.block)
            if expr.op == "!":
                return ValueFlow(ValueOperand(self._inst("not", [inner.value], result_type=BOOL)), self.block)
            raise MirCodegenError(f"unsupported unary op: {expr.op}")
        if isinstance(expr, BinaryNode):
            return self._emit_binary_from(self.block, expr)
        if isinstance(expr, CallNode):
            return self._emit_call_from(self.block, expr)
        if isinstance(expr, SubscriptNode):
            return self._emit_subscript_from(self.block, expr)
        if isinstance(expr, ArrayLiteralNode):
            return self._emit_array_literal_from(self.block, expr)
        if isinstance(expr, NewArrayNode):
            return self._emit_new_array_from(self.block, expr)
        if isinstance(expr, MapInitNode):
            return self._emit_map_init_from(self.block, expr)
        if isinstance(expr, SliceNode):
            return self._emit_slice_from(self.block, expr)
        if isinstance(expr, StructInitNode):
            return self._emit_struct_init_from(self.block, expr)
        if isinstance(expr, FieldAccessNode):
            return self._emit_field_access_from(self.block, expr)
        raise MirCodegenError(f"machine MIR does not support expr yet: {type(expr).__name__}")

    def _emit_arg_flows_from(self, in_block, exprs):
        block = in_block
        values = []
        for expr in exprs:
            flow = self._emit_expr_from(block, expr)
            values.append(flow.value)
            block = flow.block
        self._set_insert_block(block)
        return ValueFlow(values, block)

    def _binary(self, op, left, right):
        op_map = {"+": "add", "-": "sub", "*": "mul", "&": "and", "|": "or", "^": "xor",
                  "<<": "shl", ">>": "sar", ">>>": "shr"}
        if op == "/":
            return ValueOperand(self._inst("sdiv", [left, right], result_type=I64))
        if op == "%":
            return ValueOperand(self._inst("srem", [left, right], result_type=I64))
        if op in op_map:
            return ValueOperand(self._inst(op_map[op], [left, right], result_type=I64))
        raise MirCodegenError(f"unsupported compound assignment op: {op}")

    def _emit_binary(self, expr):
        return self._emit_binary_from(self._ensure_insertable(), expr).value

    def _emit_binary_from(self, in_block, expr):
        if expr.op in ("&&", "||"):
            return self._emit_short_circuit_from(in_block, expr)

        left_type = self._infer_type(expr.left)
        right_type = self._infer_type(expr.right)
        left = self._emit_expr_from(in_block, expr.left)
        right = self._emit_expr_from(left.block, expr.right)
        self._set_insert_block(right.block)
        op_map = {"+": "add", "-": "sub", "*": "mul", "&": "and", "|": "or", "^": "xor", "<<": "shl", ">>": "sar", ">>>": "shr"}
        cmp_map = {"==": "eq", "!=": "ne", "<": "lt", ">": "gt", "<=": "le", ">=": "ge"}
        unsigned = self._is_unsigned_integer(left_type) or self._is_unsigned_integer(right_type)
        if expr.op in ("==", "!=") and left_type == et.STR and right_type == et.STR:
            result = self._inst("call", [left.value, right.value], result_type=BOOL, type=BOOL, callee="__ep_str_eq")
            value = ValueOperand(result)
            if expr.op == "!=":
                value = ValueOperand(self._inst("not", [value], result_type=BOOL))
            return ValueFlow(value, self.block)
        if expr.op == "/":
            return ValueFlow(ValueOperand(self._inst("udiv" if unsigned else "sdiv", [left.value, right.value], result_type=I64)), self.block)
        if expr.op == "%":
            return ValueFlow(ValueOperand(self._inst("urem" if unsigned else "srem", [left.value, right.value], result_type=I64)), self.block)
        if expr.op in op_map:
            return ValueFlow(ValueOperand(self._inst(op_map[expr.op], [left.value, right.value], result_type=I64)), self.block)
        if expr.op in cmp_map:
            pred = cmp_map[expr.op]
            if pred not in ("eq", "ne"):
                pred = ("u" if unsigned else "s") + pred
            return ValueFlow(ValueOperand(self._inst(f"icmp.{pred}", [left.value, right.value], result_type=BOOL)), self.block)
        raise MirCodegenError(f"unsupported binary op: {expr.op}")

    def _is_unsigned_integer(self, typ):
        return typ in (et.U64, et.U32, et.U8)

    def _emit_short_circuit(self, expr):
        return self._emit_short_circuit_from(self._ensure_insertable(), expr).value

    def _emit_short_circuit_from(self, in_block, expr):
        self._set_insert_block(in_block)
        result_addr = self._new_value(ptr(), "logic.addr")
        self.block.instructions.append(MirInst("alloca", result=result_addr, type=BOOL))

        left = self._emit_expr_from(self.block, expr.left)
        rhs_block = self._new_block("logic.rhs")
        short_block = self._new_block("logic.short")
        end_block = self._new_block("logic.end")

        if expr.op == "&&":
            self._terminate_block(left.block, CondBr(left.value, rhs_block.name, short_block.name))
            short_value = ConstBoolOperand(False)
        else:
            self._terminate_block(left.block, CondBr(left.value, short_block.name, rhs_block.name))
            short_value = ConstBoolOperand(True)

        self._set_insert_block(short_block)
        self._inst("store", [short_value, ValueOperand(result_addr)])
        self._terminate_block(short_block, Br(end_block.name))

        right = self._emit_expr_from(rhs_block, expr.right)
        self._set_insert_block(right.block)
        self._inst("store", [right.value, ValueOperand(result_addr)])
        self._terminate_block(right.block, Br(end_block.name))

        self._set_insert_block(end_block)
        result = self._inst("load", [ValueOperand(result_addr)], result_type=BOOL, type=BOOL)
        return ValueFlow(ValueOperand(result), self.block)

    def _emit_call(self, expr):
        return self._emit_call_from(self._ensure_insertable(), expr).value

    def _emit_call_from(self, in_block, expr):
        self._set_insert_block(in_block)
        name = expr.name
        if expr.namespace == "os":
            return self._emit_os_call_from(self.block, expr)
        if expr.namespace:
            raise MirCodegenError(f"unsupported namespaced call: {expr.namespace}.{name}")
        if self._is_builtin(name):
            return self._emit_builtin_from(self.block, expr)
        return self._emit_user_call_from(self.block, expr)

    def _is_builtin(self, name):
        return name in {
            "println",
            "print",
            "exit",
            "str",
            "cstr",
            "i64",
            "u64",
            "u8",
            "bool",
            "i32",
            "u32",
            "bytes",
            "read_file",
            "write_file",
            "system",
            "push",
            "len",
            "cap",
            "extend",
            "map_has",
            "map_del",
        }

    def _emit_builtin(self, expr):
        return self._emit_builtin_from(self._ensure_insertable(), expr).value

    def _emit_builtin_from(self, in_block, expr):
        self._set_insert_block(in_block)
        name = expr.name
        if name == "println":
            if len(expr.args) > 1:
                raise MirCodegenError("println expects at most one argument")
            if expr.args:
                if self._infer_type(expr.args[0]) != et.STR:
                    raise MirCodegenError(f"println expected str, got {self._infer_type(expr.args[0])}")
                arg = self._emit_expr_from(self.block, expr.args[0])
                self._set_insert_block(arg.block)
                self._inst("call", [arg.value], type=VOID, callee="__ep_print_str")
            self._inst("call", [], type=VOID, callee="__ep_print_newline")
            return ValueFlow(ConstIntOperand(I64, 0), self.block)
        if name == "print":
            if len(expr.args) != 1:
                raise MirCodegenError("print expects 1 argument")
            if self._infer_type(expr.args[0]) != et.STR:
                raise MirCodegenError(f"print expected str, got {self._infer_type(expr.args[0])}")
            arg = self._emit_expr_from(self.block, expr.args[0])
            self._set_insert_block(arg.block)
            self._inst("call", [arg.value], type=VOID, callee="__ep_print_str")
            return ValueFlow(ConstIntOperand(I64, 0), self.block)
        if name == "exit":
            arg = self._emit_expr_from(self.block, expr.args[0])
            self._set_insert_block(arg.block)
            self._inst("call", [arg.value], type=VOID, callee="ExitProcess")
            return ValueFlow(ConstIntOperand(I64, 0), self.block)
        if name == "str":
            return self._emit_str_conversion_from(self.block, expr.args[0])
        if name == "cstr":
            arg = self._emit_expr_from(self.block, expr.args[0])
            self._set_insert_block(arg.block)
            result = self._inst("call", [arg.value, ConstIntOperand(I64, expr.line)], result_type=I64, type=I64, callee="__ep_cstr")
            return ValueFlow(ValueOperand(result), self.block)
        if name in ("i64", "u64", "bool"):
            return self._emit_expr_from(self.block, expr.args[0])
        if name == "u8":
            arg = self._emit_expr_from(self.block, expr.args[0])
            self._set_insert_block(arg.block)
            return ValueFlow(self._emit_truncating_uint_conversion_value(arg.value, 255), self.block)
        if name == "u32":
            arg = self._emit_expr_from(self.block, expr.args[0])
            self._set_insert_block(arg.block)
            return ValueFlow(self._emit_truncating_uint_conversion_value(arg.value, 4294967295), self.block)
        if name == "i32":
            arg = self._emit_expr_from(self.block, expr.args[0])
            self._set_insert_block(arg.block)
            return ValueFlow(self._emit_truncating_i32_conversion_value(arg.value), self.block)
        if name == "bytes":
            arg = self._emit_expr_from(self.block, expr.args[0])
            self._set_insert_block(arg.block)
            result = self._inst("call", [arg.value], result_type=ptr(), type=ptr(), callee="__ep_slice_u8_from_str")
            return ValueFlow(ValueOperand(result), self.block)
        if name == "read_file":
            arg = self._emit_expr_from(self.block, expr.args[0])
            self._set_insert_block(arg.block)
            result = self._inst("call", [arg.value, ConstIntOperand(I64, expr.line)], result_type=ptr(), type=ptr(), callee="__ep_read_file")
            return ValueFlow(ValueOperand(result), self.block)
        if name == "write_file":
            args = self._emit_arg_flows_from(self.block, expr.args)
            args.value.append(ConstIntOperand(I64, expr.line))
            result = self._inst("call", args.value, result_type=I64, type=I64, callee="__ep_write_file")
            return ValueFlow(ValueOperand(result), self.block)
        if name == "system":
            arg = self._emit_expr_from(self.block, expr.args[0])
            self._set_insert_block(arg.block)
            result = self._inst("call", [arg.value, ConstIntOperand(I64, expr.line)], result_type=I64, type=I64, callee="__ep_system_cmd")
            return ValueFlow(ValueOperand(result), self.block)
        if name == "push":
            dst_type = self._infer_type(expr.args[0])
            dst = self._emit_expr_from(self.block, expr.args[0])
            rest = self._emit_arg_flows_from(dst.block, expr.args[1:])
            args = [dst.value, *rest.value]
            if self._is_u8_array_type(dst_type):
                self._inst("call", args, type=VOID, callee="__ep_slice_u8_push")
            elif self._is_i64_array_type(dst_type):
                self._inst("call", args, type=VOID, callee="__ep_slice_i64_push")
            else:
                self._inst("call", args, type=VOID, callee="__ep_slice_ptr_push")
            return ValueFlow(ConstIntOperand(I64, 0), self.block)
        if name in ("len", "cap"):
            base_type = self._infer_type(expr.args[0])
            base = self._emit_expr_from(self.block, expr.args[0])
            self._set_insert_block(base.block)
            struct_name = self._layout_struct_name(base_type)
            if struct_name is None:
                raise MirCodegenError(f"{name} expects an aggregate pointer")
            return ValueFlow(self._load_field(base.value, struct_name, name, result_type=I64), self.block)
        if name == "extend":
            dst_type = self._infer_type(expr.args[0])
            if not self._is_u8_array_type(dst_type):
                raise MirCodegenError("extend only supports u8[]")
            dst = self._emit_expr_from(self.block, expr.args[0])
            src = self._emit_expr_from(dst.block, expr.args[1])
            self._set_insert_block(src.block)
            self._inst("call", [dst.value, src.value], type=VOID, callee="__ep_slice_u8_extend")
            return ValueFlow(ConstIntOperand(I64, 0), self.block)
        if name in ("map_has", "map_del"):
            map_type = self._infer_type(expr.args[0])
            base = self._emit_expr_from(self.block, expr.args[0])
            key = self._emit_expr_from(base.block, expr.args[1])
            self._set_insert_block(key.block)
            op = "has" if name == "map_has" else "del"
            if self._map_helper(map_type, op) is None:
                raise MirCodegenError(f"{name} expects map")
            result = self._inst("call", [base.value, key.value], result_type=BOOL, type=BOOL, callee=self._map_helper(map_type, op))
            return ValueFlow(ValueOperand(result), self.block)
        raise MirCodegenError(f"unsupported builtin call: {name}")

    def _emit_user_call(self, expr):
        return self._emit_user_call_from(self._ensure_insertable(), expr).value

    def _emit_user_call_from(self, in_block, expr):
        self._set_insert_block(in_block)
        name = expr.name
        if name not in self.func_sigs:
            raise MirCodegenError(f"unsupported call: {name}")
        args = self._emit_arg_flows_from(self.block, expr.args)
        sig = self.func_sigs[name]
        result_type = None if sig.ret == VOID else sig.ret
        result = self._inst("call", args.value, result_type=result_type, type=sig.ret, callee=name)
        return ValueFlow(ValueOperand(result) if result is not None else ConstIntOperand(I64, 0), self.block)

    def _infer_type(self, expr):
        return self._resolved_type(expr)

    def _emit_subscript(self, expr):
        return self._emit_subscript_from(self._ensure_insertable(), expr).value

    def _emit_subscript_from(self, in_block, expr):
        base_type = self._infer_type(expr.base)
        base = self._emit_expr_from(in_block, expr.base)
        index = self._emit_expr_from(base.block, expr.index)
        self._set_insert_block(index.block)
        map_value_type = self._map_value_type(base_type)
        if map_value_type is not None:
            result = self._inst("call", [base.value, index.value], result_type=map_value_type, type=map_value_type, callee=self._map_helper(base_type, "get"))
            return ValueFlow(ValueOperand(result), self.block)
        if self._is_i64_array_type(base_type):
            result = self._inst("call", [base.value, index.value], result_type=I64, type=I64, callee="__ep_slice_i64_get")
            return ValueFlow(ValueOperand(result), self.block)
        elem = self._array_struct_elem(base_type)
        if elem is not None:
            result = self._inst("call", [base.value, index.value], result_type=ptr(), type=ptr(), callee="__ep_slice_ptr_get")
            return ValueFlow(ValueOperand(result), self.block)
        if self._is_ptr_type(base_type):
            elem_type = self._epic_pointee_type(base_type.elem)
            addr = self._inst("gep", [base.value, index.value], result_type=ptr(), type=elem_type)
            load_type = I8 if base_type.elem in (et.I8, et.U8) else elem_type
            result_type = I64 if load_type == I8 else elem_type
            result = self._inst("load", [ValueOperand(addr)], result_type=result_type, type=load_type)
            return ValueFlow(ValueOperand(result), self.block)
        result = self._inst("call", [base.value, index.value], result_type=I64, type=I64, callee="__ep_slice_u8_get")
        return ValueFlow(ValueOperand(result), self.block)

    def _emit_array_literal(self, expr):
        return self._emit_array_literal_from(self._ensure_insertable(), expr).value

    def _emit_array_literal_from(self, in_block, expr):
        self._set_insert_block(in_block)
        epic_type = self._resolved_type(expr)
        arr_type = self._type(epic_type)
        if self._is_i64_array_type(epic_type):
            result = self._inst("call", [ConstIntOperand(I64, len(expr.values))], result_type=arr_type, type=ptr(), callee="__ep_slice_i64_new")
            arr = ValueOperand(result)
            block = self.block
            for value_expr in expr.values:
                value = self._emit_expr_from(block, value_expr)
                self._set_insert_block(value.block)
                self._inst("call", [arr, value.value], type=VOID, callee="__ep_slice_i64_push")
                block = self.block
            return ValueFlow(arr, self.block)
        if not self._is_u8_array_type(epic_type):
            raise MirCodegenError(f"unsupported array literal element type: {expr.elem_type}")
        result = self._inst("call", [ConstIntOperand(I64, len(expr.values)), ConstIntOperand(I64, len(expr.values))], result_type=ptr(), type=ptr(), callee="__ep_slice_u8_alloc")
        arr = ValueOperand(result)
        block = self.block
        for idx, value_expr in enumerate(expr.values):
            value = self._emit_expr_from(block, value_expr)
            self._set_insert_block(value.block)
            self._inst("call", [arr, ConstIntOperand(I64, idx), value.value], type=VOID, callee="__ep_slice_u8_set")
            block = self.block
        return ValueFlow(arr, self.block)

    def _emit_new_array(self, expr):
        return self._emit_new_array_from(self._ensure_insertable(), expr).value

    def _emit_new_array_from(self, in_block, expr):
        self._set_insert_block(in_block)
        count_flow = self._emit_expr_from(self.block, expr.count) if expr.count is not None else ValueFlow(ConstIntOperand(I64, 0), self.block)
        self._set_insert_block(count_flow.block)
        count = count_flow.value
        epic_type = self._resolved_type(expr)
        arr_type = self._type(epic_type)
        if self._is_u8_array_type(epic_type):
            result = self._inst("call", [ConstIntOperand(I64, 0), count], result_type=ptr(), type=ptr(), callee="__ep_slice_u8_alloc")
            return ValueFlow(ValueOperand(result), self.block)
        if self._is_i64_array_type(epic_type):
            result = self._inst("call", [count], result_type=arr_type, type=ptr(), callee="__ep_slice_i64_new")
            return ValueFlow(ValueOperand(result), self.block)
        if self._array_struct_elem(epic_type) is not None:
            result = self._inst("call", [count], result_type=arr_type, type=ptr(), callee="__ep_slice_ptr_new")
            return ValueFlow(ValueOperand(result), self.block)
        raise MirCodegenError(f"unsupported array element type: {expr.elem_type}")

    def _emit_map_init(self, expr):
        return self._emit_map_init_from(self._ensure_insertable(), expr).value

    def _emit_map_init_from(self, in_block, expr):
        self._set_insert_block(in_block)
        epic_type = self._resolved_type(expr)
        result_type = self._type(epic_type)
        new_helper = self._map_helper(epic_type, "new")
        set_helper = self._map_helper(epic_type, "set")
        if new_helper is None or set_helper is None:
            raise MirCodegenError(f"unsupported map init target: {expr.type_name}")
        result = self._inst("call", [], result_type=result_type, type=result_type, callee=new_helper)
        map_value = ValueOperand(result)
        block = self.block
        for key_expr, value_expr in expr.entries:
            key = self._emit_expr_from(block, key_expr)
            value = self._emit_expr_from(key.block, value_expr)
            self._set_insert_block(value.block)
            self._inst("call", [map_value, key.value, value.value], type=VOID, callee=set_helper)
            block = self.block
        return ValueFlow(map_value, self.block)

    def _emit_slice(self, expr):
        return self._emit_slice_from(self._ensure_insertable(), expr).value

    def _emit_slice_from(self, in_block, expr):
        base_type = self._infer_type(expr.base)
        base = self._emit_expr_from(in_block, expr.base)
        start = self._emit_expr_from(base.block, expr.start)
        end = self._emit_expr_from(start.block, expr.end)
        self._set_insert_block(end.block)
        if base_type == et.STR:
            result = self._inst("call", [base.value, start.value, end.value], result_type=ptr(), type=ptr(), callee="__ep_str_slice")
            return ValueFlow(ValueOperand(result), self.block)
        if self._is_u8_array_type(base_type):
            result = self._inst("call", [base.value, start.value, end.value], result_type=ptr(), type=ptr(), callee="__ep_slice_u8_slice")
            return ValueFlow(ValueOperand(result), self.block)
        raise MirCodegenError("slice only supports str and u8[]")

    def _emit_struct_init(self, expr):
        return self._emit_struct_init_from(self._ensure_insertable(), expr).value

    def _emit_struct_init_from(self, in_block, expr):
        self._set_insert_block(in_block)
        if expr.type_name not in self.structs:
            raise MirCodegenError(f"unknown struct: {expr.type_name}")
        obj = self._alloc_struct(expr.type_name)
        block = self.block
        for field, value_expr in expr.fields:
            value = self._emit_expr_from(block, value_expr)
            self._set_insert_block(value.block)
            self._store_field(obj, expr.type_name, field, value.value)
            block = self.block
        return ValueFlow(obj, self.block)

    def _emit_field_access(self, expr):
        return self._emit_field_access_from(self._ensure_insertable(), expr).value

    def _emit_field_access_from(self, in_block, expr):
        base_type = self._infer_type(expr.object)
        base = self._emit_expr_from(in_block, expr.object)
        self._set_insert_block(base.block)
        struct_name = self._layout_struct_name(base_type)
        try:
            field_type = self.structs[struct_name].field(expr.field).type
        except KeyError as exc:
            raise MirCodegenError(f"unknown field: {expr.field}") from exc
        return ValueFlow(self._load_field(base.value, struct_name, expr.field, result_type=field_type), self.block)

    def _emit_os_call(self, expr):
        return self._emit_os_call_from(self._ensure_insertable(), expr).value

    def _emit_os_call_from(self, in_block, expr):
        self._set_insert_block(in_block)
        try:
            signature = next(imp.signature for imp in self.program.imports if imp.name == expr.name and imp.dll == f"{expr.dll}.dll")
        except StopIteration as exc:
            raise MirCodegenError(f"unsupported os call: os.{expr.dll}.{expr.name}") from exc
        args = self._emit_arg_flows_from(self.block, expr.args)
        result_type = None if signature.ret == VOID else signature.ret
        result = self._inst("call", args.value, result_type=result_type, type=signature.ret, callee=expr.name)
        return ValueFlow(ValueOperand(result) if result is not None else ConstIntOperand(I64, 0), self.block)

    def _emit_truncating_uint_conversion_value(self, value, mask):
        return ValueOperand(self._inst("and", [value, ConstIntOperand(I64, mask)], result_type=I64))

    def _emit_truncating_i32_conversion_value(self, value):
        shifted = self._inst("shl", [value, ConstIntOperand(I64, 32)], result_type=I64)
        sign_extended = self._inst("sar", [ValueOperand(shifted), ConstIntOperand(I64, 32)], result_type=I64)
        return ValueOperand(sign_extended)

    def _emit_truncating_uint_conversion(self, expr, mask):
        flow = self._emit_expr_from(self._ensure_insertable(), expr)
        self._set_insert_block(flow.block)
        return self._emit_truncating_uint_conversion_value(flow.value, mask)

    def _emit_truncating_i32_conversion(self, expr):
        flow = self._emit_expr_from(self._ensure_insertable(), expr)
        self._set_insert_block(flow.block)
        return self._emit_truncating_i32_conversion_value(flow.value)

    def _emit_str_conversion(self, expr):
        return self._emit_str_conversion_from(self._ensure_insertable(), expr).value

    def _emit_str_conversion_from(self, in_block, expr):
        self._set_insert_block(in_block)
        source_type = self._resolved_type(expr)
        typ = self._infer_type(expr)
        if typ == et.STR:
            return self._emit_expr_from(self.block, expr)
        arg = self._emit_expr_from(self.block, expr)
        self._set_insert_block(arg.block)
        if typ == et.BOOL:
            result = self._inst("call", [arg.value], result_type=ptr(), type=ptr(), callee="__ep_str_from_bool")
            return ValueFlow(ValueOperand(result), self.block)
        if self._is_u8_array_type(typ):
            result = self._inst("call", [arg.value], result_type=ptr(), type=ptr(), callee="__ep_str_from_slice_u8")
            return ValueFlow(ValueOperand(result), self.block)
        if source_type == et.U64:
            result = self._inst("call", [arg.value], result_type=ptr(), type=ptr(), callee="__ep_str_from_u64")
            return ValueFlow(ValueOperand(result), self.block)
        result = self._inst("call", [arg.value], result_type=ptr(), type=ptr(), callee="__ep_str_from_i64")
        return ValueFlow(ValueOperand(result), self.block)

    def _emit_fstring(self, expr):
        return self._emit_fstring_from(self._ensure_insertable(), expr).value

    def _emit_fstring_from(self, in_block, expr):
        self._set_insert_block(in_block)
        out = None
        block = self.block
        for kind, value in expr.parts:
            if kind == "text":
                if value:
                    piece = SymbolOperand(ptr(), self._string_label(value))
                else:
                    continue
            elif kind == "expr":
                piece_flow = self._emit_str_conversion_from(block, value)
                piece = piece_flow.value
                block = piece_flow.block
                self._set_insert_block(block)
            else:
                raise MirCodegenError(f"unsupported f-string part: {kind}")
            if out is None:
                out = piece
            else:
                result = self._inst("call", [out, piece], result_type=ptr(), type=ptr(), callee="__ep_str_cat")
                out = ValueOperand(result)
            block = self.block
        if out is None:
            return ValueFlow(SymbolOperand(ptr(), self._string_label("")), self.block)
        return ValueFlow(out, self.block)

    def _coerce_print_arg(self, expr):
        if self._infer_type(expr) == et.STR:
            return self._emit_expr(expr)
        return self._emit_str_conversion(expr)

    def _emit_str_conversion(self, expr):
        source_type = self._resolved_type(expr)
        typ = self._infer_type(expr)
        if typ == et.STR:
            return self._emit_expr(expr)
        arg = self._emit_expr(expr)
        if typ == et.BOOL:
            result = self._inst("call", [arg], result_type=ptr(), type=ptr(), callee="__ep_str_from_bool")
            return ValueOperand(result)
        if self._is_u8_array_type(typ):
            result = self._inst("call", [arg], result_type=ptr(), type=ptr(), callee="__ep_str_from_slice_u8")
            return ValueOperand(result)
        if source_type == et.U64:
            result = self._inst("call", [arg], result_type=ptr(), type=ptr(), callee="__ep_str_from_u64")
            return ValueOperand(result)
        result = self._inst("call", [arg], result_type=ptr(), type=ptr(), callee="__ep_str_from_i64")
        return ValueOperand(result)

    def _emit_fstring(self, expr):
        out = None
        for kind, value in expr.parts:
            if kind == "text":
                if value:
                    piece = SymbolOperand(ptr(), self._string_label(value))
                else:
                    continue
            elif kind == "expr":
                piece = self._emit_str_conversion(value)
            else:
                raise MirCodegenError(f"unsupported f-string part: {kind}")
            if out is None:
                out = piece
            else:
                result = self._inst("call", [out, piece], result_type=ptr(), type=ptr(), callee="__ep_str_cat")
                out = ValueOperand(result)
        if out is None:
            return SymbolOperand(ptr(), self._string_label(""))
        return out

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
        for struct_name in ("str", "_slice_u8", "_slice_i64", "_slice_str"):
            self.structs[struct_name] = self._slice_layout(struct_name)
        for map_struct in ("_map_str_i64", "_map_str_bool", "_map_str_str"):
            self.structs[map_struct] = self._make_struct_layout(
                map_struct,
                [("entries", ptr(), 0), ("len", I64, 8), ("cap", I64, 16)],
                size=24,
            )
        for struct_node in ast.structs:
            self.structs[struct_node.name] = MirStruct(struct_node.name, [], 0)
        for struct_node in ast.structs:
            fields = []
            offset = 0
            for field in struct_node.fields:
                fields.append((field.name, self._type(field.resolved_type), offset))
                offset += 8
            self.structs[struct_node.name] = self._make_struct_layout(struct_node.name, fields, size=max(offset, 1))
        for struct_name in list(self.structs):
            self.structs[f"_slice_{struct_name}"] = self._slice_layout(f"_slice_{struct_name}")
        self.program.structs = self.structs



def ast_to_mir(ast):
    assert_typed_program(ast)
    return MirCodegen().emit_program(ast)
