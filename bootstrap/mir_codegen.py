"""AST -> Epic MIR codegen for the initial machine-backend path."""

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
    MirFunction,
    MirGlobal,
    MirImport,
    MirInst,
    MirParam,
    MirProgram,
    MirSignature,
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
        self.program.globals.append(MirGlobal("@argv", ptr(), None))
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
        self.block = entry
        for param in self.fn.params:
            addr = self._alloc_local(param.name, param.type)
            self._inst("store", [ValueOperand(param.value), ValueOperand(addr)])
        self._emit_block(ast_fn.body)
        if self.block.terminator is None:
            if self.fn.return_type == VOID:
                self.block.terminator = Ret()
            else:
                self.block.terminator = Ret(ConstIntOperand(self.fn.return_type, 0))
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
        return MirValue(f"%{hint}{self.value_counter}", typ)

    def _new_block(self, prefix):
        self.block_counter += 1
        block = MirBlock(f"{prefix}{self.block_counter}")
        self.fn.blocks.append(block)
        return block

    def _inst(self, op, operands=None, result_type=None, type=None, callee=None):
        result = self._new_value(result_type, op.replace(".", "_")) if result_type is not None else None
        inst = MirInst(op, operands or [], result=result, type=type, callee=callee)
        self.block.instructions.append(inst)
        return result

    def _alloc_local(self, name, typ):
        addr = self._new_value(ptr(), f"{name}.addr")
        self.block.instructions.append(MirInst("alloca", result=addr, type=typ))
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
            return list(self.structs[struct_name]["fields"]).index(field)
        except (KeyError, ValueError) as exc:
            raise MirCodegenError(f"unknown field: {struct_name}.{field}") from exc

    def _field_addr(self, base, struct_name, field, result_type=None):
        if struct_name not in self.structs or field not in self.structs[struct_name]["fields"]:
            raise MirCodegenError(f"unknown field: {struct_name}.{field}")
        field_type = result_type or self.structs[struct_name]["fields"][field]["type"]
        addr = self._inst(
            "gep",
            [base, ConstIntOperand(I64, 0), ConstIntOperand(I32, self._field_index(struct_name, field))],
            result_type=ptr(),
            type=mir_struct(struct_name),
        )
        return ValueOperand(addr)

    def _load_field(self, base, struct_name, field, result_type=None):
        field_type = result_type or self.structs[struct_name]["fields"][field]["type"]
        addr = self._field_addr(base, struct_name, field, result_type=field_type)
        value = self._inst("load", [addr], result_type=field_type, type=field_type)
        return ValueOperand(value)

    def _load_len_cap_nullable(self, base, struct_name, field):
        result_addr = self._alloc_local(f"__{field}.result{self.value_counter}", I64)
        base_int = self._inst("ptrtoint", [base], result_type=I64, type=I64)
        is_null = self._inst("icmp.eq", [ValueOperand(base_int), ConstIntOperand(I64, 0)], result_type=BOOL)
        null_block = self._new_block(f"{field}.null")
        load_block = self._new_block(f"{field}.load")
        done_block = self._new_block(f"{field}.done")
        self.block.terminator = CondBr(ValueOperand(is_null), null_block.name, load_block.name)

        self.block = null_block
        self._inst("store", [ConstIntOperand(I64, 0), ValueOperand(result_addr)])
        self.block.terminator = Br(done_block.name)

        self.block = load_block
        value = self._load_field(base, struct_name, field, result_type=I64)
        self._inst("store", [value, ValueOperand(result_addr)])
        self.block.terminator = Br(done_block.name)

        self.block = done_block
        result = self._inst("load", [ValueOperand(result_addr)], result_type=I64, type=I64)
        return ValueOperand(result)

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

    def _is_zero_container_type(self, typ):
        return isinstance(typ, et.EpicType) and (typ == et.STR or self._is_slice_type(typ) or self._map_suffix(typ) is not None)

    def _materialize_container_slot(self, addr, typ):
        if not self._is_zero_container_type(typ):
            raise MirCodegenError(f"cannot materialize non-container type {typ}")

        mir_type = self._type(typ)
        current = self._inst("load", [addr], result_type=mir_type, type=mir_type)
        current_int = self._inst("ptrtoint", [ValueOperand(current)], result_type=I64, type=I64)
        is_null = self._inst("icmp.eq", [ValueOperand(current_int), ConstIntOperand(I64, 0)], result_type=BOOL)
        init_block = self._new_block("container.init")
        done_block = self._new_block("container.done")
        self.block.terminator = CondBr(ValueOperand(is_null), init_block.name, done_block.name)

        self.block = init_block
        empty = self._materialized_empty_container(typ)
        self._inst("store", [empty, addr])
        self.block.terminator = Br(done_block.name)

        self.block = done_block
        ensured = self._inst("load", [addr], result_type=mir_type, type=mir_type)
        return ValueOperand(ensured)

    def _container_lvalue_addr(self, expr):
        if isinstance(expr, VarNode):
            if expr.name not in self.locals:
                raise MirCodegenError(f"undefined variable: {expr.name}")
            return ValueOperand(self.locals[expr.name])
        if isinstance(expr, FieldAccessNode):
            base_type = self._infer_type(expr.object)
            base = self._emit_expr(expr.object)
            struct_name = self._layout_struct_name(base_type)
            if struct_name is None:
                raise MirCodegenError("container field base must be a struct pointer")
            field_type = self.structs[struct_name]["fields"][expr.field]["type"]
            return self._field_addr(base, struct_name, expr.field, result_type=field_type)
        raise MirCodegenError("container mutation target must be a variable or field")

    def _materialize_container_expr(self, expr):
        typ = self._resolved_type(expr)
        addr = self._container_lvalue_addr(expr)
        return self._materialize_container_slot(addr, typ)

    def _emit_map_read_nullable(self, base, index, base_type):
        value_type = self._map_value_type(base_type)
        result_addr = self._alloc_local(f"__map.get.result{self.value_counter}", value_type)
        base_int = self._inst("ptrtoint", [base], result_type=I64, type=I64)
        is_null = self._inst("icmp.eq", [ValueOperand(base_int), ConstIntOperand(I64, 0)], result_type=BOOL)
        null_block = self._new_block("map.get.null")
        load_block = self._new_block("map.get.load")
        done_block = self._new_block("map.get.done")
        self.block.terminator = CondBr(ValueOperand(is_null), null_block.name, load_block.name)

        self.block = null_block
        zero = self._materialized_empty_container(et.STR) if self._map_suffix(base_type) == "str" else self._zero_value(value_type)
        self._inst("store", [zero, ValueOperand(result_addr)])
        self.block.terminator = Br(done_block.name)

        self.block = load_block
        value = self._inst("call", [base, index], result_type=value_type, type=value_type, callee=self._map_helper(base_type, "get"))
        self._inst("store", [ValueOperand(value), ValueOperand(result_addr)])
        self.block.terminator = Br(done_block.name)

        self.block = done_block
        result = self._inst("load", [ValueOperand(result_addr)], result_type=value_type, type=value_type)
        return ValueOperand(result)

    def _emit_map_has_del_nullable(self, base, key, base_type, op):
        result_addr = self._alloc_local(f"__map.{op}.result{self.value_counter}", BOOL)
        base_int = self._inst("ptrtoint", [base], result_type=I64, type=I64)
        is_null = self._inst("icmp.eq", [ValueOperand(base_int), ConstIntOperand(I64, 0)], result_type=BOOL)
        null_block = self._new_block(f"map.{op}.null")
        call_block = self._new_block(f"map.{op}.call")
        done_block = self._new_block(f"map.{op}.done")
        self.block.terminator = CondBr(ValueOperand(is_null), null_block.name, call_block.name)

        self.block = null_block
        self._inst("store", [ConstBoolOperand(False), ValueOperand(result_addr)])
        self.block.terminator = Br(done_block.name)

        self.block = call_block
        value = self._inst("call", [base, key], result_type=BOOL, type=BOOL, callee=self._map_helper(base_type, op))
        self._inst("store", [ValueOperand(value), ValueOperand(result_addr)])
        self.block.terminator = Br(done_block.name)

        self.block = done_block
        result = self._inst("load", [ValueOperand(result_addr)], result_type=BOOL, type=BOOL)
        return ValueOperand(result)

    def _emit_block(self, block):
        for stmt in block.stmts:
            if self.block.terminator is not None:
                break
            self._emit_stmt(stmt)

    def _emit_stmt(self, stmt):
        if isinstance(stmt, ExprStmtNode):
            self._emit_expr(stmt.expr)
        elif isinstance(stmt, LetNode):
            typ = self._type(stmt.resolved_type)
            addr = self._alloc_local(stmt.name, typ)
            value = self._emit_expr(stmt.value) if stmt.value is not None else self._zero_value(typ)
            self._inst("store", [value, ValueOperand(addr)])
        elif isinstance(stmt, AssignNode):
            if stmt.name not in self.locals:
                raise MirCodegenError(f"undefined variable: {stmt.name}")
            value = self._emit_expr(stmt.value)
            self._inst("store", [value, ValueOperand(self.locals[stmt.name])])
        elif isinstance(stmt, ReturnNode):
            self.block.terminator = Ret(self._emit_expr(stmt.expr) if stmt.expr is not None else None)
        elif isinstance(stmt, IfNode):
            self._emit_if(stmt)
        elif isinstance(stmt, WhileNode):
            self._emit_while(stmt)
        elif isinstance(stmt, ForRangeNode):
            self._emit_for_range(stmt)
        elif isinstance(stmt, AssertNode):
            self._emit_assert(stmt)
        elif isinstance(stmt, PanicNode):
            self._emit_panic(stmt)
        elif isinstance(stmt, MatchNode):
            self._emit_match(stmt)
        elif isinstance(stmt, FieldSetNode):
            base_type = self._infer_type(stmt.object)
            base = self._emit_expr(stmt.object)
            value = self._emit_expr(stmt.value)
            struct_name = self._layout_struct_name(base_type)
            if struct_name is None:
                raise MirCodegenError("field assignment base must be a struct pointer")
            self._store_field(base, struct_name, stmt.field, value)
        elif isinstance(stmt, SubscriptAssignNode):
            base_type = self._infer_type(stmt.base)
            index = self._emit_expr(stmt.index)
            value = self._emit_expr(stmt.value)
            if self._is_u8_array_type(base_type):
                base = self._materialize_container_expr(stmt.base)
                self._inst("call", [base, index, value], type=VOID, callee="__ep_slice_u8_set")
            elif self._is_i64_array_type(base_type):
                base = self._materialize_container_expr(stmt.base)
                self._inst("call", [base, index, value], type=VOID, callee="__ep_slice_i64_set")
            else:
                callee = self._map_helper(base_type, "set")
                if callee is None:
                    raise MirCodegenError("subscript assignment only supports primitive arrays and maps in machine MIR so far")
                base = self._materialize_container_expr(stmt.base)
                self._inst("call", [base, index, value], type=VOID, callee=callee)
        elif isinstance(stmt, AssignOpNode):
            value = BinaryNode(op=stmt.op, left=stmt.target, right=stmt.value)
            if isinstance(stmt.target, VarNode):
                self._emit_stmt(AssignNode(name=stmt.target.name, value=value))
            elif isinstance(stmt.target, FieldAccessNode):
                self._emit_stmt(FieldSetNode(object=stmt.target.object, field=stmt.target.field, value=value))
            elif isinstance(stmt.target, SubscriptNode):
                self._emit_stmt(SubscriptAssignNode(base=stmt.target.base, index=stmt.target.index, value=value))
            else:
                raise MirCodegenError(f"unsupported compound assignment target: {type(stmt.target).__name__}")
        elif isinstance(stmt, BreakNode):
            if not self.loop_stack:
                raise MirCodegenError("break outside loop")
            self.block.terminator = Br(self.loop_stack[-1][1])
        elif isinstance(stmt, ContinueNode):
            if not self.loop_stack:
                raise MirCodegenError("continue outside loop")
            self.block.terminator = Br(self.loop_stack[-1][0])
        else:
            raise MirCodegenError(f"machine MIR does not support stmt yet: {type(stmt).__name__}")

    def _emit_if(self, stmt):
        cond = self._emit_expr(stmt.cond)
        then_block = self._new_block("if.then")
        else_block = self._new_block("if.else") if stmt.else_block else None
        end_block = self._new_block("if.end")
        self.block.terminator = CondBr(cond, then_block.name, else_block.name if else_block else end_block.name)
        self.block = then_block
        self._emit_block(stmt.then_block)
        if self.block.terminator is None:
            self.block.terminator = Br(end_block.name)
        if else_block is not None:
            self.block = else_block
            self._emit_block(stmt.else_block)
            if self.block.terminator is None:
                self.block.terminator = Br(end_block.name)
        self.block = end_block

    def _emit_while(self, stmt):
        cond_block = self._new_block("while.cond")
        body_block = self._new_block("while.body")
        end_block = self._new_block("while.end")
        self.block.terminator = Br(cond_block.name)
        self.loop_stack.append((cond_block.name, end_block.name))
        self.block = cond_block
        cond = self._emit_expr(stmt.cond)
        self.block.terminator = CondBr(cond, body_block.name, end_block.name)
        self.block = body_block
        self._emit_block(stmt.body)
        if self.block.terminator is None:
            self.block.terminator = Br(cond_block.name)
        self.loop_stack.pop()
        self.block = end_block

    def _emit_for_range(self, stmt):
        var_addr = self._alloc_local(stmt.name, I64)
        end_addr = self._alloc_local(f"__{stmt.name}.end{self.value_counter}", I64)
        self._inst("store", [self._emit_expr(stmt.start), ValueOperand(var_addr)])
        self._inst("store", [self._emit_expr(stmt.end), ValueOperand(end_addr)])
        cond_block = self._new_block("for.cond")
        body_block = self._new_block("for.body")
        inc_block = self._new_block("for.inc")
        end_block = self._new_block("for.end")
        self.block.terminator = Br(cond_block.name)
        self.block = cond_block
        cur = self._inst("load", [ValueOperand(var_addr)], result_type=I64, type=I64)
        end = self._inst("load", [ValueOperand(end_addr)], result_type=I64, type=I64)
        cond = self._inst("icmp.slt", [ValueOperand(cur), ValueOperand(end)], result_type=BOOL)
        self.block.terminator = CondBr(ValueOperand(cond), body_block.name, end_block.name)
        self.loop_stack.append((inc_block.name, end_block.name))
        self.block = body_block
        self._emit_block(stmt.body)
        if self.block.terminator is None:
            self.block.terminator = Br(inc_block.name)
        self.loop_stack.pop()
        self.block = inc_block
        cur = self._inst("load", [ValueOperand(var_addr)], result_type=I64, type=I64)
        nxt = self._inst("add", [ValueOperand(cur), ConstIntOperand(I64, 1)], result_type=I64)
        self._inst("store", [ValueOperand(nxt), ValueOperand(var_addr)])
        self.block.terminator = Br(cond_block.name)
        self.block = end_block

    def _emit_assert(self, stmt):
        cond = self._emit_expr(stmt.cond)
        ok_block = self._new_block("assert.ok")
        fail_block = self._new_block("assert.fail")
        self.block.terminator = CondBr(cond, ok_block.name, fail_block.name)
        self.block = fail_block
        self._emit_print_text(f"assert line {stmt.line}: ")
        if stmt.message is None:
            self._emit_print_text("assertion failed")
        else:
            self._emit_print_expr(stmt.message)
        self._emit_print_newline()
        self._emit_exit_current_block()
        self.block.terminator = self._dummy_return()
        self.block = ok_block

    def _emit_panic(self, stmt):
        self._emit_print_text(f"panic line {stmt.line}: ")
        self._emit_print_expr(stmt.message)
        self._emit_print_newline()
        self._emit_exit_current_block()
        self.block.terminator = self._dummy_return()

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

    def _emit_checked_int32_conversion(self, expr, target_name):
        value = self._emit_expr(expr)
        if target_name == "i32":
            lo = -2147483648
            hi = 2147483647
        elif target_name == "u32":
            lo = 0
            hi = 4294967295
        else:
            raise MirCodegenError(f"unsupported checked conversion: {target_name}")

        fail_block = self._new_block(f"{target_name}.range_fail")
        upper_block = self._new_block(f"{target_name}.range_upper")
        ok_block = self._new_block(f"{target_name}.range_ok")

        low_bad = self._inst("icmp.slt", [value, ConstIntOperand(I64, lo)], result_type=BOOL)
        self.block.terminator = CondBr(ValueOperand(low_bad), fail_block.name, upper_block.name)

        self.block = upper_block
        high_bad = self._inst("icmp.sgt", [value, ConstIntOperand(I64, hi)], result_type=BOOL)
        self.block.terminator = CondBr(ValueOperand(high_bad), fail_block.name, ok_block.name)

        self.block = fail_block
        self._emit_exit_current_block(1)
        self.block.terminator = self._dummy_return()

        self.block = ok_block
        return value

    def _emit_match(self, stmt):
        value = self._emit_expr(stmt.expr)
        match_addr = self._alloc_local(f"__match{self.value_counter}", value.type)
        self._inst("store", [value, ValueOperand(match_addr)])
        end_block = self._new_block("match.end")
        else_case = next((case for case in stmt.cases if case.is_else), None)
        checks = [(case, self._new_block("match.case")) for case in stmt.cases if not case.is_else]
        else_block = self._new_block("match.else") if else_case is not None else end_block

        next_check_blocks = [self._new_block("match.next") for _ in checks[:-1]]
        for idx, (case, case_block) in enumerate(checks):
            next_block = next_check_blocks[idx] if idx < len(checks) - 1 else else_block
            self._emit_match_check(stmt, match_addr, value.type, case, case_block, next_block)
            if idx < len(checks) - 1:
                self.block = next_check_blocks[idx]

        if not checks:
            self.block.terminator = Br(else_block.name)

        for case, case_block in checks:
            self.block = case_block
            self._emit_match_bindings(match_addr, case)
            self._emit_block(case.body)
            if self.block.terminator is None:
                self.block.terminator = Br(end_block.name)

        if else_case is not None:
            self.block = else_block
            self._emit_block(else_case.body)
            if self.block.terminator is None:
                self.block.terminator = Br(end_block.name)

        self.block = end_block

    def _emit_match_check(self, stmt, match_addr, match_type, case, case_block, next_block):
        scrut = self._inst("load", [ValueOperand(match_addr)], result_type=match_type, type=match_type)
        scrut_op = ValueOperand(scrut)
        pat = self._emit_expr(case.pattern)
        cond = self._inst("icmp.eq", [scrut_op, pat], result_type=BOOL)
        self.block.terminator = CondBr(ValueOperand(cond), case_block.name, next_block.name)

    def _emit_match_bindings(self, match_addr, case):
        if not case.bindings:
            return

    def _emit_expr(self, expr):
        if isinstance(expr, (LiteralNode, CharNode)):
            return ConstIntOperand(I64, expr.value)
        if isinstance(expr, BoolNode):
            return ConstBoolOperand(bool(expr.value))
        if isinstance(expr, StringNode):
            return SymbolOperand(ptr(), self._string_label(expr.value))
        if isinstance(expr, FStringNode):
            return self._emit_fstring(expr)
        if isinstance(expr, VarNode):
            if expr.name == "argv":
                return SymbolOperand(ptr(), "@argv")
            if expr.name not in self.locals:
                raise MirCodegenError(f"undefined variable: {expr.name}")
            typ = self.local_types[expr.name]
            value = self._inst("load", [ValueOperand(self.locals[expr.name])], result_type=typ, type=typ)
            return ValueOperand(value)
        if isinstance(expr, UnaryNode):
            inner = self._emit_expr(expr.expr)
            if expr.op == "-":
                zero = ConstIntOperand(I64, 0)
                return ValueOperand(self._inst("sub", [zero, inner], result_type=I64))
            if expr.op == "!":
                return ValueOperand(self._inst("not", [inner], result_type=BOOL))
            raise MirCodegenError(f"unsupported unary op: {expr.op}")
        if isinstance(expr, BinaryNode):
            return self._emit_binary(expr)
        if isinstance(expr, CallNode):
            return self._emit_call(expr)
        if isinstance(expr, SubscriptNode):
            return self._emit_subscript(expr)
        if isinstance(expr, ArrayLiteralNode):
            return self._emit_array_literal(expr)
        if isinstance(expr, NewArrayNode):
            return self._emit_new_array(expr)
        if isinstance(expr, MapInitNode):
            return self._emit_map_init(expr)
        if isinstance(expr, SliceNode):
            return self._emit_slice(expr)
        if isinstance(expr, StructInitNode):
            return self._emit_struct_init(expr)
        if isinstance(expr, FieldAccessNode):
            return self._emit_field_access(expr)
        raise MirCodegenError(f"machine MIR does not support expr yet: {type(expr).__name__}")

    def _emit_binary(self, expr):
        if expr.op in ("&&", "||"):
            return self._emit_short_circuit(expr)

        left_type = self._infer_type(expr.left)
        right_type = self._infer_type(expr.right)
        left = self._emit_expr(expr.left)
        right = self._emit_expr(expr.right)
        op_map = {"+": "add", "-": "sub", "*": "mul", "&": "and", "|": "or", "^": "xor", "<<": "shl", ">>": "sar", ">>>": "shr"}
        cmp_map = {"==": "eq", "!=": "ne", "<": "lt", ">": "gt", "<=": "le", ">=": "ge"}
        unsigned = self._is_unsigned_integer(left_type) or self._is_unsigned_integer(right_type)
        if expr.op in ("==", "!=") and left_type == et.STR and right_type == et.STR:
            result = self._inst("call", [left, right], result_type=BOOL, type=BOOL, callee="__ep_str_eq")
            value = ValueOperand(result)
            if expr.op == "!=":
                value = ValueOperand(self._inst("not", [value], result_type=BOOL))
            return value
        if expr.op == "/":
            return ValueOperand(self._inst("udiv" if unsigned else "sdiv", [left, right], result_type=I64))
        if expr.op == "%":
            return ValueOperand(self._inst("urem" if unsigned else "srem", [left, right], result_type=I64))
        if expr.op in op_map:
            return ValueOperand(self._inst(op_map[expr.op], [left, right], result_type=I64))
        if expr.op in cmp_map:
            pred = cmp_map[expr.op]
            if pred not in ("eq", "ne"):
                pred = ("u" if unsigned else "s") + pred
            return ValueOperand(self._inst(f"icmp.{pred}", [left, right], result_type=BOOL))
        raise MirCodegenError(f"unsupported binary op: {expr.op}")

    def _is_unsigned_integer(self, typ):
        return typ in (et.U64, et.U32, et.U8)

    def _emit_short_circuit(self, expr):
        result_addr = self._new_value(ptr(), "logic.addr")
        self.block.instructions.append(MirInst("alloca", result=result_addr, type=BOOL))

        left = self._emit_expr(expr.left)
        rhs_block = self._new_block("logic.rhs")
        short_block = self._new_block("logic.short")
        end_block = self._new_block("logic.end")

        if expr.op == "&&":
            self.block.terminator = CondBr(left, rhs_block.name, short_block.name)
            short_value = ConstBoolOperand(False)
        else:
            self.block.terminator = CondBr(left, short_block.name, rhs_block.name)
            short_value = ConstBoolOperand(True)

        self.block = short_block
        self._inst("store", [short_value, ValueOperand(result_addr)])
        self.block.terminator = Br(end_block.name)

        self.block = rhs_block
        right = self._emit_expr(expr.right)
        self._inst("store", [right, ValueOperand(result_addr)])
        self.block.terminator = Br(end_block.name)

        self.block = end_block
        result = self._inst("load", [ValueOperand(result_addr)], result_type=BOOL, type=BOOL)
        return ValueOperand(result)

    def _emit_call(self, expr):
        name = expr.name
        if expr.namespace == "os":
            return self._emit_os_call(expr)
        if expr.namespace:
            raise MirCodegenError(f"unsupported namespaced call: {expr.namespace}.{name}")
        if self._is_builtin(name):
            return self._emit_builtin(expr)
        return self._emit_user_call(expr)

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
        name = expr.name
        if name == "println":
            if len(expr.args) > 1:
                raise MirCodegenError("println expects at most one argument")
            if expr.args:
                if self._infer_type(expr.args[0]) != et.STR:
                    raise MirCodegenError(f"println expected str, got {self._infer_type(expr.args[0])}")
                self._inst("call", [self._emit_expr(expr.args[0])], type=VOID, callee="__ep_print_str")
            self._inst("call", [], type=VOID, callee="__ep_print_newline")
            return ConstIntOperand(I64, 0)
        if name == "print":
            if len(expr.args) != 1:
                raise MirCodegenError("print expects 1 argument")
            if self._infer_type(expr.args[0]) != et.STR:
                raise MirCodegenError(f"print expected str, got {self._infer_type(expr.args[0])}")
            self._inst("call", [self._emit_expr(expr.args[0])], type=VOID, callee="__ep_print_str")
            return ConstIntOperand(I64, 0)
        if name == "exit":
            arg = self._emit_expr(expr.args[0])
            self._inst("call", [arg], type=VOID, callee="ExitProcess")
            return ConstIntOperand(I64, 0)
        if name == "str":
            return self._emit_str_conversion(expr.args[0])
        if name == "cstr":
            arg = self._emit_expr(expr.args[0])
            result = self._inst(
                "call",
                [arg, ConstIntOperand(I64, expr.line)],
                result_type=I64,
                type=I64,
                callee="__ep_cstr",
            )
            return ValueOperand(result)
        if name in ("i64", "u64", "u8", "bool"):
            return self._emit_expr(expr.args[0])
        if name in ("i32", "u32"):
            return self._emit_checked_int32_conversion(expr.args[0], name)
        if name == "bytes":
            arg = self._emit_expr(expr.args[0])
            result = self._inst("call", [arg], result_type=ptr(), type=ptr(), callee="__ep_slice_u8_from_str")
            return ValueOperand(result)
        if name == "read_file":
            arg = self._emit_expr(expr.args[0])
            result = self._inst(
                "call",
                [arg, ConstIntOperand(I64, expr.line)],
                result_type=ptr(),
                type=ptr(),
                callee="__ep_read_file",
            )
            return ValueOperand(result)
        if name == "write_file":
            args = [self._emit_expr(arg) for arg in expr.args]
            args.append(ConstIntOperand(I64, expr.line))
            result = self._inst("call", args, result_type=I64, type=I64, callee="__ep_write_file")
            return ValueOperand(result)
        if name == "system":
            arg = self._emit_expr(expr.args[0])
            result = self._inst("call", [arg, ConstIntOperand(I64, expr.line)], result_type=I64, type=I64, callee="__ep_system_cmd")
            return ValueOperand(result)
        if name == "push":
            dst_type = self._infer_type(expr.args[0])
            dst = self._materialize_container_expr(expr.args[0])
            args = [dst, *[self._emit_expr(arg) for arg in expr.args[1:]]]
            if self._is_u8_array_type(dst_type):
                self._inst("call", args, type=VOID, callee="__ep_slice_u8_push")
            elif self._is_i64_array_type(dst_type):
                self._inst("call", args, type=VOID, callee="__ep_slice_i64_push")
            else:
                self._inst("call", args, type=VOID, callee="__ep_slice_ptr_push")
            return ConstIntOperand(I64, 0)
        if name in ("len", "cap"):
            base_type = self._infer_type(expr.args[0])
            base = self._emit_expr(expr.args[0])
            struct_name = self._layout_struct_name(base_type)
            if struct_name is None:
                raise MirCodegenError(f"{name} expects an aggregate pointer")
            return self._load_len_cap_nullable(base, struct_name, name)
        if name == "extend":
            dst_type = self._infer_type(expr.args[0])
            if not self._is_u8_array_type(dst_type):
                raise MirCodegenError("extend only supports u8[]")
            dst = self._materialize_container_expr(expr.args[0])
            args = [dst, self._emit_expr(expr.args[1])]
            self._inst("call", args, type=VOID, callee="__ep_slice_u8_extend")
            return ConstIntOperand(I64, 0)
        if name in ("map_has", "map_del"):
            map_type = self._infer_type(expr.args[0])
            base = self._emit_expr(expr.args[0])
            key = self._emit_expr(expr.args[1])
            op = "has" if name == "map_has" else "del"
            if self._map_helper(map_type, op) is None:
                raise MirCodegenError(f"{name} expects map")
            return self._emit_map_has_del_nullable(base, key, map_type, op)
        raise MirCodegenError(f"unsupported builtin call: {name}")

    def _emit_user_call(self, expr):
        name = expr.name
        if name not in self.func_sigs:
            raise MirCodegenError(f"unsupported call: {name}")
        args = [self._emit_expr(arg) for arg in expr.args]
        sig = self.func_sigs[name]
        result_type = None if sig.ret == VOID else sig.ret
        result = self._inst("call", args, result_type=result_type, type=sig.ret, callee=name)
        return ValueOperand(result) if result is not None else ConstIntOperand(I64, 0)

    def _infer_type(self, expr):
        return self._resolved_type(expr)

    def _emit_subscript(self, expr):
        base_type = self._infer_type(expr.base)
        base = self._emit_expr(expr.base)
        index = self._emit_expr(expr.index)
        map_value_type = self._map_value_type(base_type)
        if map_value_type is not None:
            return self._emit_map_read_nullable(base, index, base_type)
        if self._is_i64_array_type(base_type):
            result = self._inst("call", [base, index], result_type=I64, type=I64, callee="__ep_slice_i64_get")
            return ValueOperand(result)
        elem = self._array_struct_elem(base_type)
        if elem is not None:
            result_type = ptr()
            result = self._inst("call", [base, index], result_type=result_type, type=ptr(), callee="__ep_slice_ptr_get")
            return ValueOperand(result)
        if self._is_ptr_type(base_type):
            elem_type = self._epic_pointee_type(base_type.elem)
            addr = self._inst("gep", [base, index], result_type=ptr(), type=elem_type)
            load_type = I8 if base_type.elem in (et.I8, et.U8) else elem_type
            result_type = I64 if load_type == I8 else elem_type
            result = self._inst("load", [ValueOperand(addr)], result_type=result_type, type=load_type)
            return ValueOperand(result)
        result = self._inst("call", [base, index], result_type=I64, type=I64, callee="__ep_slice_u8_get")
        return ValueOperand(result)

    def _emit_array_literal(self, expr):
        epic_type = self._resolved_type(expr)
        arr_type = self._type(epic_type)
        if self._is_i64_array_type(epic_type):
            result = self._inst(
                "call",
                [ConstIntOperand(I64, len(expr.values))],
                result_type=arr_type,
                type=ptr(),
                callee="__ep_slice_i64_new",
            )
            arr = ValueOperand(result)
            for value in expr.values:
                self._inst("call", [arr, self._emit_expr(value)], type=VOID, callee="__ep_slice_i64_push")
            return arr
        if not self._is_u8_array_type(epic_type):
            raise MirCodegenError(f"unsupported array literal element type: {expr.elem_type}")
        result = self._inst(
            "call",
            [ConstIntOperand(I64, len(expr.values)), ConstIntOperand(I64, len(expr.values))],
            result_type=ptr(),
            type=ptr(),
            callee="__ep_slice_u8_alloc",
        )
        arr = ValueOperand(result)
        for idx, value in enumerate(expr.values):
            self._inst("call", [arr, ConstIntOperand(I64, idx), self._emit_expr(value)], type=VOID, callee="__ep_slice_u8_set")
        return arr

    def _emit_new_array(self, expr):
        count = self._emit_expr(expr.count) if expr.count is not None else ConstIntOperand(I64, 0)
        epic_type = self._resolved_type(expr)
        arr_type = self._type(epic_type)
        if self._is_u8_array_type(epic_type):
            result = self._inst("call", [ConstIntOperand(I64, 0), count], result_type=ptr(), type=ptr(), callee="__ep_slice_u8_alloc")
            return ValueOperand(result)
        if self._is_i64_array_type(epic_type):
            result = self._inst("call", [count], result_type=arr_type, type=ptr(), callee="__ep_slice_i64_new")
            return ValueOperand(result)
        if self._array_struct_elem(epic_type) is not None:
            result = self._inst("call", [count], result_type=arr_type, type=ptr(), callee="__ep_slice_ptr_new")
            return ValueOperand(result)
        raise MirCodegenError(f"unsupported array element type: {expr.elem_type}")

    def _emit_map_init(self, expr):
        epic_type = self._resolved_type(expr)
        result_type = self._type(epic_type)
        new_helper = self._map_helper(epic_type, "new")
        set_helper = self._map_helper(epic_type, "set")
        if new_helper is None or set_helper is None:
            raise MirCodegenError(f"unsupported map init target: {expr.type_name}")
        result = self._inst("call", [], result_type=result_type, type=result_type, callee=new_helper)
        map_value = ValueOperand(result)
        for key_expr, value_expr in expr.entries:
            self._inst("call", [map_value, self._emit_expr(key_expr), self._emit_expr(value_expr)], type=VOID, callee=set_helper)
        return map_value

    def _emit_slice(self, expr):
        base_type = self._infer_type(expr.base)
        base = self._emit_expr(expr.base)
        start = self._emit_expr(expr.start)
        end = self._emit_expr(expr.end)
        if base_type == et.STR:
            result = self._inst("call", [base, start, end], result_type=ptr(), type=ptr(), callee="__ep_str_slice")
            return ValueOperand(result)
        if self._is_u8_array_type(base_type):
            result = self._inst("call", [base, start, end], result_type=ptr(), type=ptr(), callee="__ep_slice_u8_slice")
            return ValueOperand(result)
        raise MirCodegenError("slice only supports str and u8[]")

    def _emit_struct_init(self, expr):
        if expr.type_name not in self.structs:
            raise MirCodegenError(f"unknown struct: {expr.type_name}")
        obj = self._alloc_struct(expr.type_name)
        for field, value_expr in expr.fields:
            self._store_field(obj, expr.type_name, field, self._emit_expr(value_expr))
        return obj

    def _emit_field_access(self, expr):
        base_type = self._infer_type(expr.object)
        base = self._emit_expr(expr.object)
        struct_name = self._layout_struct_name(base_type)
        if struct_name not in self.structs or expr.field not in self.structs[struct_name]["fields"]:
            raise MirCodegenError(f"unknown field: {expr.field}")
        field_type = self.structs[struct_name]["fields"][expr.field]["type"]
        return self._load_field(base, struct_name, expr.field, result_type=field_type)

    def _emit_os_call(self, expr):
        try:
            signature = next(imp.signature for imp in self.program.imports if imp.name == expr.name and imp.dll == f"{expr.dll}.dll")
        except StopIteration as exc:
            raise MirCodegenError(f"unsupported os call: os.{expr.dll}.{expr.name}") from exc
        args = [self._emit_expr(arg) for arg in expr.args]
        result_type = None if signature.ret == VOID else signature.ret
        result = self._inst("call", args, result_type=result_type, type=signature.ret, callee=expr.name)
        return ValueOperand(result) if result is not None else ConstIntOperand(I64, 0)

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

    def _materialized_empty_container(self, typ):
        mir_type = self._type(typ)
        if typ == et.STR:
            return SymbolOperand(mir_type, self._string_label(""))
        if self._is_u8_array_type(typ):
            result = self._inst("call", [ConstIntOperand(I64, 0), ConstIntOperand(I64, 0)], result_type=mir_type, type=mir_type, callee="__ep_slice_u8_alloc")
            return ValueOperand(result)
        if self._is_i64_array_type(typ):
            result = self._inst("call", [ConstIntOperand(I64, 0)], result_type=mir_type, type=ptr(), callee="__ep_slice_i64_new")
            return ValueOperand(result)
        if self._array_struct_elem(typ) is not None:
            result = self._inst("call", [ConstIntOperand(I64, 0)], result_type=mir_type, type=ptr(), callee="__ep_slice_ptr_new")
            return ValueOperand(result)
        map_new = self._map_helper(typ, "new")
        if map_new is not None:
            result = self._inst("call", [], result_type=mir_type, type=mir_type, callee=map_new)
            return ValueOperand(result)
        raise MirCodegenError(f"cannot materialize empty container for {typ}")

    def _zero_value(self, typ):
        if typ.kind == "ptr":
            return ConstNullOperand()
        return ConstIntOperand(typ, 0)

    def _string_label(self, text):
        if text not in self.strings:
            self.string_counter += 1
            label = f"@str.{self.string_counter}"
            self.strings[text] = label
            self.program.globals.append(MirGlobal(label, ptr(), text))
        return self.strings[text]

    def _compute_struct_layouts(self, ast):
        self.structs = {}
        self.structs["str"] = {
            "fields": {
                "data": {"type": ptr(), "offset": 0},
                "len": {"type": I64, "offset": 8},
                "cap": {"type": I64, "offset": 16},
            },
            "size": 24,
        }
        self.structs["_slice_u8"] = {
            "fields": {
                "data": {"type": ptr(), "offset": 0},
                "len": {"type": I64, "offset": 8},
                "cap": {"type": I64, "offset": 16},
            },
            "size": 24,
        }
        self.structs["_slice_i64"] = {
            "fields": {
                "data": {"type": ptr(), "offset": 0},
                "len": {"type": I64, "offset": 8},
                "cap": {"type": I64, "offset": 16},
            },
            "size": 24,
        }
        self.structs["_slice_str"] = {
            "fields": {
                "data": {"type": ptr(), "offset": 0},
                "len": {"type": I64, "offset": 8},
                "cap": {"type": I64, "offset": 16},
            },
            "size": 24,
        }
        for map_struct in ("_map_str_i64", "_map_str_bool", "_map_str_str"):
            self.structs[map_struct] = {
                "fields": {
                    "entries": {"type": ptr(), "offset": 0},
                    "len": {"type": I64, "offset": 8},
                    "cap": {"type": I64, "offset": 16},
                },
                "size": 24,
            }
        for struct_node in ast.structs:
            self.structs[struct_node.name] = {"fields": {}, "size": 0}
        for struct_node in ast.structs:
            fields = {}
            offset = 0
            for field in struct_node.fields:
                fields[field.name] = {"type": self._type(field.resolved_type), "offset": offset}
                offset += 8
            self.structs[struct_node.name] = {"fields": fields, "size": max(offset, 1)}
        for struct_name in list(self.structs):
            self.structs[f"_slice_{struct_name}"] = {
                "fields": {
                    "data": {"type": ptr(), "offset": 0},
                    "len": {"type": I64, "offset": 8},
                    "cap": {"type": I64, "offset": 16},
                },
                "size": 24,
            }
        self.program.structs = self.structs



def ast_to_mir(ast):
    assert_typed_program(ast)
    return MirCodegen().emit_program(ast)
