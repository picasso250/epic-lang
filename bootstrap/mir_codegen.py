"""AST -> Epic MIR codegen for the initial machine-backend path."""

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


class MirCodegenError(RuntimeError):
    pass


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
        self.adts = {}
        self.loop_stack = []

    def emit_program(self, ast):
        self._compute_struct_layouts(ast)
        self.func_sigs = {
            fn.name: MirSignature([self._type(p.type) for p in fn.params], self._type(fn.ret_type))
            for fn in ast.funcs
        }
        self.program.imports.append(MirImport("ExitProcess", MirSignature([I64], VOID), "kernel32.dll"))
        self.program.imports.append(MirImport("Sleep", MirSignature([I64], VOID), "kernel32.dll"))
        self.program.imports.append(MirImport("GetTickCount64", MirSignature([], I64), "kernel32.dll"))
        self.program.imports.append(MirImport("lstrlenA", MirSignature([ptr(I8)], I64), "kernel32.dll"))
        self.program.imports.append(MirImport("lstrcmpA", MirSignature([ptr(I8), ptr(I8)], I64), "kernel32.dll"))
        self.program.imports.append(MirImport("GetStdHandle", MirSignature([I64], I64), "kernel32.dll"))
        self.program.imports.append(MirImport("GetProcessHeap", MirSignature([], I64), "kernel32.dll"))
        self.program.imports.append(MirImport("HeapAlloc", MirSignature([I64, I64, I64], I64), "kernel32.dll"))
        self.program.imports.append(MirImport("CreateFileA", MirSignature([ptr(I8), I64, I64, I64, I64, I64, I64], I64), "kernel32.dll"))
        self.program.imports.append(MirImport("GetFileSize", MirSignature([I64, I64], I64), "kernel32.dll"))
        self.program.imports.append(MirImport("ReadFile", MirSignature([I64, I64, I64, I64, I64], I64), "kernel32.dll"))
        self.program.imports.append(MirImport("WriteFile", MirSignature([I64, I64, I64, I64, I64], I64), "kernel32.dll"))
        self.program.imports.append(MirImport("CloseHandle", MirSignature([I64], I64), "kernel32.dll"))
        self.program.imports.append(MirImport("CreateProcessA", MirSignature([], I64), "kernel32.dll"))
        self.program.imports.append(MirImport("WaitForSingleObject", MirSignature([I64, I64], I64), "kernel32.dll"))
        self.program.imports.append(MirImport("GetExitCodeProcess", MirSignature([I64, I64], I64), "kernel32.dll"))
        self.program.imports.append(MirImport("GetCommandLineA", MirSignature([], I64), "kernel32.dll"))
        self.program.externs.append(MirExtern("str_i64", MirSignature([I64], ptr_str())))
        self.program.externs.append(MirExtern("str_new", MirSignature([I64, I64], ptr_str())))
        self.program.externs.append(MirExtern("str_bool", MirSignature([BOOL], ptr_str())))
        self.program.externs.append(MirExtern("str_arr_i8", MirSignature([ptr_arr_i8()], ptr_str())))
        self.program.externs.append(MirExtern("str_cat", MirSignature([ptr_str(), ptr_str()], ptr_str())))
        self.program.externs.append(MirExtern("str_slice", MirSignature([ptr_str(), I64, I64], ptr_str())))
        self.program.externs.append(MirExtern("str_replace_char", MirSignature([ptr_str(), I64, I64], ptr_str())))
        self.program.externs.append(MirExtern("str_get", MirSignature([ptr_str(), I64], I64)))
        self.program.externs.append(MirExtern("str_starts_with", MirSignature([ptr_str(), ptr_str()], I64)))
        self.program.externs.append(MirExtern("str_find", MirSignature([ptr_str(), ptr_str()], I64)))
        self.program.externs.append(MirExtern("str_trim", MirSignature([ptr_str()], ptr_str())))
        self.program.externs.append(MirExtern("bytes_str", MirSignature([ptr_str()], ptr_arr_i8())))
        self.program.externs.append(MirExtern("read_file", MirSignature([ptr_str()], ptr_arr_i8())))
        self.program.externs.append(MirExtern("write_file", MirSignature([ptr_str(), ptr_arr_i8()], I64)))
        self.program.externs.append(MirExtern("system_cmd", MirSignature([ptr_str()], I64)))
        self.program.externs.append(MirExtern("new_arr_i8", MirSignature([I64], ptr_arr_i8())))
        self.program.externs.append(MirExtern("new_arr_i8_empty", MirSignature([I64], ptr_arr_i8())))
        self.program.externs.append(MirExtern("arr_i8_get", MirSignature([ptr_arr_i8(), I64], I64)))
        self.program.externs.append(MirExtern("arr_i8_set", MirSignature([ptr_arr_i8(), I64, I64], VOID)))
        self.program.externs.append(MirExtern("arr_i8_push", MirSignature([ptr_arr_i8(), I64], VOID)))
        self.program.externs.append(MirExtern("arr_i8_slice", MirSignature([ptr_arr_i8(), I64, I64], ptr_arr_i8())))
        self.program.externs.append(MirExtern("arr_i64_get", MirSignature([ptr_arr_i64(), I64], I64)))
        self.program.externs.append(MirExtern("arr_i64_set", MirSignature([ptr_arr_i64(), I64, I64], VOID)))
        self.program.externs.append(MirExtern("extend_i8", MirSignature([ptr_arr_i8(), ptr_arr_i8()], VOID)))
        self.program.externs.append(MirExtern("map_new", MirSignature([], ptr_map_str_i64())))
        self.program.externs.append(MirExtern("map_get", MirSignature([ptr_map_str_i64(), ptr_str()], I64)))
        self.program.externs.append(MirExtern("map_set", MirSignature([ptr_map_str_i64(), ptr_str(), I64], VOID)))
        self.program.externs.append(MirExtern("map_has", MirSignature([ptr_map_str_i64(), ptr_str()], BOOL)))
        self.program.externs.append(MirExtern("map_repr", MirSignature([ptr_map_str_i64()], ptr_str())))
        self.program.externs.append(MirExtern("print_str", MirSignature([ptr_str()], VOID)))
        self.program.externs.append(MirExtern("print_newline", MirSignature([], VOID)))
        self.program.externs.append(MirExtern("putc", MirSignature([I64], VOID)))
        self.program.externs.append(MirExtern("__epic_alloc", MirSignature([I64], ptr())))
        self.program.externs.append(MirExtern("__epic_arr_qword_new", MirSignature([I64], ptr())))
        self.program.externs.append(MirExtern("__epic_arr_i64_push", MirSignature([ptr(), I64], VOID)))
        self.program.externs.append(MirExtern("__epic_arr_ptr_push", MirSignature([ptr(), ptr()], VOID)))
        self.program.externs.append(MirExtern("__epic_arr_qword_extend", MirSignature([ptr(), ptr()], VOID)))
        self.program.externs.append(MirExtern("__epic_arr_i64_get", MirSignature([ptr(), I64], I64)))
        self.program.externs.append(MirExtern("__epic_arr_ptr_get", MirSignature([ptr(), I64], ptr())))
        self.program.globals.append(MirGlobal("@argv", ptr_arr_str(), None))
        for fn in ast.funcs:
            self.program.functions.append(self._emit_function(fn))
        validate(self.program)
        return self.program

    def _emit_function(self, ast_fn):
        self.fn = MirFunction(
            ast_fn.name,
            [MirParam(p.name, self._type(p.type)) for p in ast_fn.params],
            self._type(ast_fn.ret_type),
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
        if typ in (None, "void"):
            return VOID
        if typ in ("i64", "u64", "i8", "u8", "bool"):
            return BOOL if typ == "bool" else I64
        if typ == "&str":
            return ptr_str()
        if typ in ("u8[]", "i8[]", "&_arr_i8"):
            return ptr_arr_i8()
        if typ in ("i64[]", "u64[]", "&_arr_i64"):
            return ptr_arr_i64()
        if typ in ("map[str]i64", "&_map_str_i64"):
            return ptr_map_str_i64()
        if isinstance(typ, str) and typ.endswith("[]") and typ[:-2] in self.structs:
            return ptr_arr_struct(typ[:-2])
        if typ in self.structs:
            return ptr_struct(typ)
        if isinstance(typ, str) and typ.startswith("&") and typ[1:] in self.structs:
            return ptr_struct(typ[1:])
        raise MirCodegenError(f"machine MIR does not support type yet: {typ}")

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
        addr = self._new_value(ptr(typ), f"{name}.addr")
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
            result_type=ptr_struct(struct_name),
            type=ptr(),
            callee="__epic_alloc",
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
            result_type=ptr(field_type),
            type=mir_struct(struct_name),
        )
        return ValueOperand(addr)

    def _load_field(self, base, struct_name, field, result_type=None):
        field_type = result_type or self.structs[struct_name]["fields"][field]["type"]
        addr = self._field_addr(base, struct_name, field, result_type=field_type)
        value = self._inst("load", [addr], result_type=field_type, type=field_type)
        return ValueOperand(value)

    def _store_field(self, base, struct_name, field, value):
        addr = self._field_addr(base, struct_name, field)
        self._inst("store", [value, addr])

    def _ptr_struct_name(self, typ):
        if typ.kind == "ptr" and typ.pointee is not None and typ.pointee.kind == "struct":
            return typ.pointee.name
        return None

    def _array_struct_elem(self, typ):
        struct_name = self._ptr_struct_name(typ)
        if struct_name is None or not struct_name.startswith("_arr_"):
            return None
        elem = struct_name[len("_arr_"):]
        return elem if elem in self.structs else None

    def _emit_block(self, block):
        for stmt in block.stmts:
            if self.block.terminator is not None:
                break
            self._emit_stmt(stmt)

    def _emit_stmt(self, stmt):
        if isinstance(stmt, ExprStmtNode):
            self._emit_expr(stmt.expr)
        elif isinstance(stmt, LetNode):
            typ = self._infer_type(stmt.value) if stmt.var_type is None else self._type(stmt.var_type)
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
            base = self._emit_expr(stmt.object)
            value = self._emit_expr(stmt.value)
            struct_name = self._ptr_struct_name(base.type)
            if struct_name is None:
                raise MirCodegenError("field assignment base must be a struct pointer")
            self._store_field(base, struct_name, stmt.field, value)
        elif isinstance(stmt, SubscriptAssignNode):
            base = self._emit_expr(stmt.base)
            index = self._emit_expr(stmt.index)
            value = self._emit_expr(stmt.value)
            if base.type == ptr_arr_i8():
                self._inst("call", [base, index, value], type=VOID, callee="arr_i8_set")
            elif base.type == ptr_arr_i64():
                self._inst("call", [base, index, value], type=VOID, callee="arr_i64_set")
            elif base.type == ptr_map_str_i64():
                self._inst("call", [base, index, value], type=VOID, callee="map_set")
            else:
                raise MirCodegenError("subscript assignment only supports primitive arrays in machine MIR so far")
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
        cond = self._inst("icmp.lt", [ValueOperand(cur), ValueOperand(end)], result_type=BOOL)
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
        message = stmt.message if stmt.message is not None else StringNode("assertion failed")
        self._emit_call(CallNode("print", [StringNode(f"assert line {stmt.line}: ")]))
        self._emit_call(CallNode("print", [message]))
        self._emit_call(CallNode("println", []))
        self._emit_call(CallNode("ExitProcess", [LiteralNode(1)], namespace="os"))
        self.block.terminator = self._dummy_return()
        self.block = ok_block

    def _emit_panic(self, stmt):
        self._emit_call(CallNode("print", [StringNode(f"panic line {stmt.line}: ")]))
        self._emit_call(CallNode("print", [stmt.message]))
        self._emit_call(CallNode("println", []))
        self._emit_call(CallNode("ExitProcess", [LiteralNode(1)], namespace="os"))
        self.block.terminator = self._dummy_return()

    def _dummy_return(self):
        if self.fn.return_type == VOID:
            return Ret()
        return Ret(ConstIntOperand(self.fn.return_type, 0))

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
            self._emit_match_check(stmt, match_addr, case, case_block, next_block)
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

    def _emit_match_check(self, stmt, match_addr, case, case_block, next_block):
        scrut = self._inst("load", [ValueOperand(match_addr)], result_type=match_addr.type.pointee, type=match_addr.type.pointee)
        scrut_op = ValueOperand(scrut)
        if isinstance(case.pattern, FieldAccessNode) and isinstance(case.pattern.object, VarNode):
            adt_name = case.pattern.object.name
            tag = self.adts[adt_name][case.pattern.field]["tag"]
            tag_value = self._load_field(scrut_op, adt_name, "tag").value
            cond = self._inst("icmp.eq", [ValueOperand(tag_value), ConstIntOperand(I64, tag)], result_type=BOOL)
            self.block.terminator = CondBr(ValueOperand(cond), case_block.name, next_block.name)
            return
        pat = self._emit_expr(case.pattern)
        cond = self._inst("icmp.eq", [scrut_op, pat], result_type=BOOL)
        self.block.terminator = CondBr(ValueOperand(cond), case_block.name, next_block.name)

    def _emit_match_bindings(self, match_addr, case):
        if not case.bindings:
            return
        if not (isinstance(case.pattern, FieldAccessNode) and isinstance(case.pattern.object, VarNode)):
            return
        adt_name = case.pattern.object.name
        variant = case.pattern.field
        payload_name = self.adts[adt_name][variant]["payload"]
        if payload_name is None:
            return
        scrut = self._inst("load", [ValueOperand(match_addr)], result_type=match_addr.type.pointee, type=match_addr.type.pointee)
        payload = self._load_field(ValueOperand(scrut), adt_name, "data", result_type=ptr_struct(payload_name))
        for field, bind_name in case.bindings:
            field_type = self.structs[payload_name]["fields"][field]["type"]
            loaded = self._load_field(payload, payload_name, field, result_type=field_type).value
            addr = self._alloc_local(bind_name, field_type)
            self._inst("store", [ValueOperand(loaded), ValueOperand(addr)])

    def _emit_expr(self, expr):
        if isinstance(expr, (LiteralNode, CharNode)):
            return ConstIntOperand(I64, expr.value)
        if isinstance(expr, BoolNode):
            return ConstBoolOperand(bool(expr.value))
        if isinstance(expr, StringNode):
            return SymbolOperand(ptr_str(), self._string_label(expr.value))
        if isinstance(expr, FStringNode):
            return self._emit_expr(self._fstring_expr(expr))
        if isinstance(expr, VarNode):
            if expr.name == "argv":
                return SymbolOperand(ptr_arr_str(), "@argv")
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
        if isinstance(expr, NewNode):
            return self._emit_new(expr)
        if isinstance(expr, SliceNode):
            return self._emit_slice(expr)
        if isinstance(expr, StructInitNode):
            return self._emit_struct_init(expr)
        if isinstance(expr, FieldAccessNode):
            return self._emit_field_access(expr)
        raise MirCodegenError(f"machine MIR does not support expr yet: {type(expr).__name__}")

    def _emit_binary(self, expr):
        left = self._emit_expr(expr.left)
        right = self._emit_expr(expr.right)
        op_map = {"+": "add", "-": "sub", "*": "mul", "/": "div", "%": "mod", "&": "and", "|": "or", "^": "xor", "<<": "shl", ">>": "sar", ">>>": "shr"}
        bool_map = {"&&": "and", "||": "or"}
        cmp_map = {"==": "eq", "!=": "ne", "<": "lt", ">": "gt", "<=": "le", ">=": "ge"}
        if expr.op == "+" and left.type == ptr_str() and right.type == ptr_str():
            result = self._inst("call", [left, right], result_type=ptr_str(), type=ptr_str(), callee="str_cat")
            return ValueOperand(result)
        if expr.op in op_map:
            return ValueOperand(self._inst(op_map[expr.op], [left, right], result_type=I64))
        if expr.op in bool_map:
            return ValueOperand(self._inst(bool_map[expr.op], [left, right], result_type=BOOL))
        if expr.op in cmp_map:
            return ValueOperand(self._inst(f"icmp.{cmp_map[expr.op]}", [left, right], result_type=BOOL))
        raise MirCodegenError(f"unsupported binary op: {expr.op}")

    def _emit_call(self, expr):
        name = expr.name
        if expr.namespace == "os" and name == "ExitProcess":
            arg = self._emit_expr(expr.args[0])
            self._inst("call", [arg], type=VOID, callee="ExitProcess")
            return ConstIntOperand(I64, 0)
        if expr.namespace == "os":
            return self._emit_os_call(expr)
        if expr.namespace:
            raise MirCodegenError(f"unsupported namespaced call: {expr.namespace}.{name}")
        if name == "println":
            if len(expr.args) > 1:
                raise MirCodegenError("println expects at most one argument in machine MIR")
            if expr.args:
                as_str = self._coerce_print_arg(expr.args[0])
                self._inst("call", [as_str], type=VOID, callee="print_str")
            self._inst("call", [], type=VOID, callee="print_newline")
            return ConstIntOperand(I64, 0)
        if name == "print":
            if len(expr.args) > 1:
                raise MirCodegenError("print expects at most one argument in machine MIR")
            if expr.args:
                as_str = self._coerce_print_arg(expr.args[0])
                self._inst("call", [as_str], type=VOID, callee="print_str")
            return ConstIntOperand(I64, 0)
        if name == "putstr":
            arg = self._emit_expr(expr.args[0])
            self._inst("call", [arg], type=VOID, callee="print_str")
            return ConstIntOperand(I64, 0)
        if name == "putc":
            arg = self._emit_expr(expr.args[0])
            self._inst("call", [arg], type=VOID, callee="putc")
            return ConstIntOperand(I64, 0)
        if name == "str":
            static = self._static_repr(expr.args[0], repr_context=False)
            if static is not None:
                return SymbolOperand(ptr_str(), self._string_label(static))
            if self._infer_type(expr.args[0]) == ptr_str():
                return self._emit_expr(expr.args[0])
            if self._infer_type(expr.args[0]) == BOOL:
                arg = self._emit_expr(expr.args[0])
                result = self._inst("call", [arg], result_type=ptr_str(), type=ptr_str(), callee="str_bool")
                return ValueOperand(result)
            if self._infer_type(expr.args[0]) == ptr_arr_i8():
                arg = self._emit_expr(expr.args[0])
                result = self._inst("call", [arg], result_type=ptr_str(), type=ptr_str(), callee="str_arr_i8")
                return ValueOperand(result)
            if self._infer_type(expr.args[0]) == ptr_map_str_i64():
                arg = self._emit_expr(expr.args[0])
                result = self._inst("call", [arg], result_type=ptr_str(), type=ptr_str(), callee="map_repr")
                return ValueOperand(result)
            arg = self._emit_expr(expr.args[0])
            result = self._inst("call", [arg], result_type=ptr_str(), type=ptr_str(), callee="str_i64")
            return ValueOperand(result)
        if name == "str_new":
            args = [self._emit_expr(arg) for arg in expr.args]
            result = self._inst("call", args, result_type=ptr_str(), type=ptr_str(), callee="str_new")
            return ValueOperand(result)
        if name == "itoa":
            arg = self._emit_expr(expr.args[0])
            result = self._inst("call", [arg], result_type=ptr_str(), type=ptr_str(), callee="str_i64")
            return ValueOperand(result)
        if name in ("i64", "u64", "u8", "bool"):
            return self._emit_expr(expr.args[0])
        if name == "bytes":
            arg = self._emit_expr(expr.args[0])
            result = self._inst("call", [arg], result_type=ptr_arr_i8(), type=ptr_arr_i8(), callee="bytes_str")
            return ValueOperand(result)
        if name == "read_file":
            arg = self._emit_expr(expr.args[0])
            result = self._inst("call", [arg], result_type=ptr_arr_i8(), type=ptr_arr_i8(), callee="read_file")
            return ValueOperand(result)
        if name == "write_file":
            args = [self._emit_expr(arg) for arg in expr.args]
            result = self._inst("call", args, result_type=I64, type=I64, callee="write_file")
            return ValueOperand(result)
        if name in ("str_slice", "str_replace_char"):
            args = [self._emit_expr(arg) for arg in expr.args]
            result = self._inst("call", args, result_type=ptr_str(), type=ptr_str(), callee=name)
            return ValueOperand(result)
        if name in ("str_starts_with", "str_find"):
            args = [self._emit_expr(arg) for arg in expr.args]
            result = self._inst("call", args, result_type=I64, type=I64, callee=name)
            return ValueOperand(result)
        if name == "str_trim":
            arg = self._emit_expr(expr.args[0])
            result = self._inst("call", [arg], result_type=ptr_str(), type=ptr_str(), callee=name)
            return ValueOperand(result)
        if name == "system":
            arg = self._emit_expr(expr.args[0])
            result = self._inst("call", [arg], result_type=I64, type=I64, callee="system_cmd")
            return ValueOperand(result)
        if name == "push":
            args = [self._emit_expr(arg) for arg in expr.args]
            if args[0].type == ptr_arr_i8():
                self._inst("call", args, type=VOID, callee="arr_i8_push")
            elif args[0].type == ptr_arr_i64():
                self._inst("call", args, type=VOID, callee="__epic_arr_i64_push")
            else:
                self._inst("call", args, type=VOID, callee="__epic_arr_ptr_push")
            return ConstIntOperand(I64, 0)
        if name in ("len", "cap"):
            base = self._emit_expr(expr.args[0])
            struct_name = self._ptr_struct_name(base.type)
            if struct_name is None:
                raise MirCodegenError(f"{name} expects an aggregate pointer")
            return self._load_field(base, struct_name, name, result_type=I64)
        if name == "extend":
            args = [self._emit_expr(arg) for arg in expr.args]
            if args[0].type == ptr_arr_i8():
                self._inst("call", args, type=VOID, callee="extend_i8")
            else:
                self._inst("call", args, type=VOID, callee="__epic_arr_qword_extend")
            return ConstIntOperand(I64, 0)
        if name == "map_has":
            args = [self._emit_expr(arg) for arg in expr.args]
            result = self._inst("call", args, result_type=BOOL, type=BOOL, callee="map_has")
            return ValueOperand(result)
        if name not in self.func_sigs:
            raise MirCodegenError(f"unsupported call: {name}")
        args = [self._emit_expr(arg) for arg in expr.args]
        sig = self.func_sigs[name]
        result_type = None if sig.ret == VOID else sig.ret
        result = self._inst("call", args, result_type=result_type, type=sig.ret, callee=name)
        return ValueOperand(result) if result is not None else ConstIntOperand(I64, 0)

    def _infer_type(self, expr):
        if isinstance(expr, BoolNode):
            return BOOL
        if isinstance(expr, CharNode):
            return I64
        if isinstance(expr, StringNode):
            return ptr_str()
        if isinstance(expr, FStringNode):
            return ptr_str()
        if isinstance(expr, VarNode):
            if expr.name == "argv":
                return ptr_arr_str()
            return self.local_types.get(expr.name, I64)
        if isinstance(expr, CallNode) and expr.name == "str":
            return ptr_str()
        if isinstance(expr, CallNode) and expr.name == "str_new":
            return ptr_str()
        if isinstance(expr, CallNode) and expr.name in ("str_slice", "str_replace_char"):
            return ptr_str()
        if isinstance(expr, CallNode) and expr.name == "str_trim":
            return ptr_str()
        if isinstance(expr, CallNode) and expr.name in ("str_starts_with", "str_find"):
            return I64
        if isinstance(expr, CallNode) and expr.name == "map_has":
            return BOOL
        if isinstance(expr, CallNode) and expr.name in ("i64", "u64"):
            return I64
        if isinstance(expr, CallNode) and expr.name == "u8":
            return I64
        if isinstance(expr, CallNode) and expr.name == "bool":
            return BOOL
        if isinstance(expr, CallNode) and expr.name in ("bytes", "read_file"):
            return ptr_arr_i8()
        if isinstance(expr, CallNode) and expr.name == "itoa":
            return ptr_str()
        if isinstance(expr, CallNode) and expr.name in self.func_sigs:
            return self.func_sigs[expr.name].ret
        if isinstance(expr, ArrayLiteralNode):
            if expr.elem_type in ("u8", "i8"):
                return ptr_arr_i8()
            if expr.elem_type in ("i64", "u64"):
                return ptr_arr_i64()
        if isinstance(expr, NewArrayNode):
            if expr.elem_type in ("u8", "i8"):
                return ptr_arr_i8()
            if expr.elem_type in ("i64", "u64"):
                return ptr_arr_i64()
            if expr.elem_type in self.structs:
                return ptr_arr_struct(expr.elem_type)
        if isinstance(expr, NewNode) and expr.struct_name == "map[str]i64":
            return ptr_map_str_i64()
        if isinstance(expr, SubscriptNode):
            base_type = self._infer_type(expr.base)
            if base_type == ptr_map_str_i64():
                return I64
            if base_type == ptr_str():
                return I64
            if base_type == ptr_arr_i64():
                return I64
            elem = self._array_struct_elem(base_type)
            if elem is not None:
                return ptr_struct(elem)
            if base_type.kind == "ptr" and base_type.pointee is not None and base_type.pointee.kind == "ptr":
                return base_type.pointee
            if base_type == ptr(I8):
                return I64
            if base_type == ptr(I64):
                return I64
            return I64
        if isinstance(expr, SliceNode):
            return self._infer_type(expr.base)
        if isinstance(expr, StructInitNode):
            return ptr_struct(expr.type_name)
        if isinstance(expr, FieldAccessNode):
            base_type = self._infer_type(expr.object)
            struct_name = self._ptr_struct_name(base_type)
            if struct_name in self.structs:
                return self.structs[struct_name]["fields"][expr.field]["type"]
        if isinstance(expr, BinaryNode) and expr.op in ("==", "!=", "<", ">", "<=", ">="):
            return BOOL
        if isinstance(expr, BinaryNode) and expr.op == "+" and self._infer_type(expr.left) == ptr_str() and self._infer_type(expr.right) == ptr_str():
            return ptr_str()
        return I64

    def _emit_subscript(self, expr):
        base = self._emit_expr(expr.base)
        index = self._emit_expr(expr.index)
        if base.type == ptr_map_str_i64():
            result = self._inst("call", [base, index], result_type=I64, type=I64, callee="map_get")
            return ValueOperand(result)
        if base.type == ptr_str():
            result = self._inst("call", [base, index], result_type=I64, type=I64, callee="str_get")
            return ValueOperand(result)
        if base.type == ptr_arr_i64():
            result = self._inst("call", [base, index], result_type=I64, type=I64, callee="__epic_arr_i64_get")
            return ValueOperand(result)
        elem = self._array_struct_elem(base.type)
        if elem is not None:
            result_type = ptr_struct(elem)
            result = self._inst("call", [base, index], result_type=result_type, type=ptr(), callee="__epic_arr_ptr_get")
            return ValueOperand(result)
        if base.type.kind == "ptr" and base.type.pointee is not None and base.type.pointee.kind == "ptr":
            addr = self._inst("gep", [base, index], result_type=ptr(base.type.pointee), type=ptr())
            result = self._inst("load", [ValueOperand(addr)], result_type=base.type.pointee, type=base.type.pointee)
            return ValueOperand(result)
        if base.type == ptr(I8):
            addr = self._inst("gep", [base, index], result_type=ptr(I8), type=I8)
            result = self._inst("load", [ValueOperand(addr)], result_type=I64, type=I8)
            return ValueOperand(result)
        if base.type == ptr(I64):
            addr = self._inst("gep", [base, index], result_type=ptr(I64), type=I64)
            result = self._inst("load", [ValueOperand(addr)], result_type=I64, type=I64)
            return ValueOperand(result)
        result = self._inst("call", [base, index], result_type=I64, type=I64, callee="arr_i8_get")
        return ValueOperand(result)

    def _emit_array_literal(self, expr):
        arr_type = self._type(expr.elem_type + "[]")
        if arr_type == ptr_arr_i64():
            result = self._inst(
                "call",
                [ConstIntOperand(I64, len(expr.values))],
                result_type=arr_type,
                type=ptr(),
                callee="__epic_arr_qword_new",
            )
            arr = ValueOperand(result)
            for value in expr.values:
                self._inst("call", [arr, self._emit_expr(value)], type=VOID, callee="__epic_arr_i64_push")
            return arr
        if arr_type != ptr_arr_i8():
            raise MirCodegenError(f"unsupported array literal element type: {expr.elem_type}")
        result = self._inst(
            "call",
            [ConstIntOperand(I64, len(expr.values))],
            result_type=ptr_arr_i8(),
            type=ptr_arr_i8(),
            callee="new_arr_i8",
        )
        arr = ValueOperand(result)
        for idx, value in enumerate(expr.values):
            self._inst("call", [arr, ConstIntOperand(I64, idx), self._emit_expr(value)], type=VOID, callee="arr_i8_set")
        return arr

    def _emit_new_array(self, expr):
        count = self._emit_expr(expr.count) if expr.count is not None else ConstIntOperand(I64, 4)
        if expr.elem_type in ("u8", "i8"):
            result = self._inst("call", [count], result_type=ptr_arr_i8(), type=ptr_arr_i8(), callee="new_arr_i8_empty")
            return ValueOperand(result)
        if expr.elem_type in ("i64", "u64"):
            result_type = ptr_arr_i64()
            result = self._inst("call", [count], result_type=result_type, type=ptr(), callee="__epic_arr_qword_new")
            return ValueOperand(result)
        if expr.elem_type in self.structs:
            result_type = ptr_arr_struct(expr.elem_type)
            result = self._inst("call", [count], result_type=result_type, type=ptr(), callee="__epic_arr_qword_new")
            return ValueOperand(result)
        raise MirCodegenError(f"unsupported array element type: {expr.elem_type}")

    def _emit_new(self, expr):
        if expr.struct_name == "map[str]i64":
            result = self._inst("call", [], result_type=ptr_map_str_i64(), type=ptr_map_str_i64(), callee="map_new")
            return ValueOperand(result)
        if expr.struct_name in self.structs:
            return self._alloc_struct(expr.struct_name)
        raise MirCodegenError(f"unsupported new target: {expr.struct_name}")

    def _emit_slice(self, expr):
        base = self._emit_expr(expr.base)
        start = self._emit_expr(expr.start) if expr.start is not None else ConstIntOperand(I64, 0)
        if expr.end is not None:
            end = self._emit_expr(expr.end)
        else:
            struct_name = self._ptr_struct_name(base.type)
            if struct_name is None:
                raise MirCodegenError("slice base must be an aggregate pointer")
            end = self._load_field(base, struct_name, "len", result_type=I64)
        if base.type == ptr_str():
            result = self._inst("call", [base, start, end], result_type=ptr_str(), type=ptr_str(), callee="str_slice")
            return ValueOperand(result)
        if base.type == ptr_arr_i8():
            result = self._inst("call", [base, start, end], result_type=ptr_arr_i8(), type=ptr_arr_i8(), callee="arr_i8_slice")
            return ValueOperand(result)
        raise MirCodegenError("slice only supports str and u8[] in machine MIR so far")

    def _emit_struct_init(self, expr):
        if expr.variant:
            return self._emit_adt_init(expr)
        if expr.type_name not in self.structs:
            raise MirCodegenError(f"unknown struct: {expr.type_name}")
        obj = self._alloc_struct(expr.type_name)
        for field, value_expr in expr.fields:
            self._store_field(obj, expr.type_name, field, self._emit_expr(value_expr))
        return obj

    def _emit_adt_init(self, expr):
        if expr.type_name not in self.adts or expr.variant not in self.adts[expr.type_name]:
            raise MirCodegenError(f"unknown ADT variant: {expr.type_name}.{expr.variant}")
        info = self.adts[expr.type_name][expr.variant]
        header = self._alloc_struct(expr.type_name)
        self._store_field(header, expr.type_name, "tag", ConstIntOperand(I64, info["tag"]))
        payload_name = info["payload"]
        if payload_name is not None:
            payload = self._alloc_struct(payload_name)
            self._store_field(header, expr.type_name, "data", payload)
            for field, value_expr in expr.fields:
                self._store_field(payload, payload_name, field, self._emit_expr(value_expr))
        return header

    def _emit_field_access(self, expr):
        base = self._emit_expr(expr.object)
        struct_name = self._ptr_struct_name(base.type)
        if struct_name not in self.structs or expr.field not in self.structs[struct_name]["fields"]:
            raise MirCodegenError(f"unknown field: {expr.field}")
        field_type = self.structs[struct_name]["fields"][expr.field]["type"]
        return self._load_field(base, struct_name, expr.field, result_type=field_type)

    def _emit_os_call(self, expr):
        if expr.name not in {imp.name for imp in self.program.imports}:
            raise MirCodegenError(f"unsupported os call: os.{expr.name}")
        args = []
        for arg_expr in expr.args:
            if self._infer_type(arg_expr) == ptr_str():
                base = self._emit_expr(arg_expr)
                args.append(self._load_field(base, "str", "data", result_type=ptr(I8)))
            else:
                args.append(self._emit_expr(arg_expr))
        signature = next(imp.signature for imp in self.program.imports if imp.name == expr.name)
        result_type = None if signature.ret == VOID else signature.ret
        result = self._inst("call", args, result_type=result_type, type=signature.ret, callee=expr.name)
        return ValueOperand(result) if result is not None else ConstIntOperand(I64, 0)

    def _coerce_print_arg(self, expr):
        if self._infer_type(expr) == ptr_str():
            return self._emit_expr(expr)
        return self._emit_call(CallNode("str", [expr]))

    def _fstring_expr(self, expr):
        nodes = []
        for kind, value in expr.parts:
            if kind == "text":
                if value:
                    nodes.append(StringNode(value))
            elif kind == "expr":
                nodes.append(CallNode(name="str", args=[value]))
        if not nodes:
            return StringNode("")
        out = nodes[0]
        for node in nodes[1:]:
            out = BinaryNode(op="+", left=out, right=node)
        return out

    def _static_repr(self, expr, repr_context):
        if isinstance(expr, LiteralNode):
            return str(expr.value)
        if isinstance(expr, CharNode):
            return str(expr.value)
        if isinstance(expr, BoolNode):
            return "true" if expr.value else "false"
        if isinstance(expr, StringNode):
            return self._quote(expr.value) if repr_context else expr.value
        if isinstance(expr, CallNode) and expr.name in ("i64", "u64", "u8", "bool"):
            return self._static_repr(expr.args[0], repr_context)
        if isinstance(expr, BinaryNode):
            left = self._static_repr(expr.left, False)
            right = self._static_repr(expr.right, False)
            if left is not None and right is not None:
                try:
                    lv = int(left)
                    rv = int(right)
                    if expr.op == "+":
                        return str(lv + rv)
                    if expr.op == "-":
                        return str(lv - rv)
                except ValueError:
                    pass
        if isinstance(expr, ArrayLiteralNode):
            values = [self._static_repr(v, True) for v in expr.values]
            if any(v is None for v in values):
                return None
            if expr.elem_type in ("u8", "i8") and not repr_context:
                return "".join(chr(int(v)) for v in values)
            elem = "bool" if expr.elem_type == "bool" else "str" if expr.elem_type == "str" else "i64" if expr.elem_type in ("i64", "u64") else expr.elem_type
            return f"{elem}[]" + "{" + ", ".join(values) + "}"
        if isinstance(expr, StructInitNode):
            if expr.variant:
                return self._static_adt_repr(expr)
            if expr.type_name not in self.structs:
                return None
            supplied = dict(expr.fields)
            parts = []
            for name, info in self.structs[expr.type_name]["fields"].items():
                if name.startswith("_"):
                    continue
                value = supplied.get(name)
                if value is None:
                    rendered = self._zero_repr(info["type"])
                else:
                    rendered = self._static_repr(value, True)
                if rendered is None:
                    return None
                parts.append(f"{name}: {rendered}")
            return f"{expr.type_name}" + "{" + ", ".join(parts) + "}"
        if isinstance(expr, FStringNode):
            out = []
            for kind, value in expr.parts:
                if kind == "text":
                    out.append(value)
                else:
                    rendered = self._static_repr(value, False)
                    if rendered is None:
                        return None
                    out.append(rendered)
            return "".join(out)
        return None

    def _static_adt_repr(self, expr):
        if expr.type_name not in self.adts or expr.variant not in self.adts[expr.type_name]:
            return None
        payload_name = self.adts[expr.type_name][expr.variant]["payload"]
        supplied = dict(expr.fields)
        parts = []
        if payload_name is not None:
            for name, info in self.structs[payload_name]["fields"].items():
                value = supplied.get(name)
                rendered = self._zero_repr(info["type"]) if value is None else self._static_repr(value, True)
                if rendered is None:
                    return None
                parts.append(f"{name}: {rendered}")
        return f"{expr.type_name}.{expr.variant}" + "{" + ", ".join(parts) + "}"

    def _zero_repr(self, typ):
        if typ == I64:
            return "0"
        if typ == BOOL:
            return "false"
        if typ == ptr_str():
            return self._quote("")
        if typ == ptr_arr_i8():
            return "u8[]{}"
        if typ.kind == "ptr" and typ.pointee is not None and typ.pointee.kind == "struct":
            name = typ.pointee.name
            if name in self.adts:
                return f"{name}.Empty" + "{}"
        return "0"

    def _quote(self, text):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t") + '"'

    def _zero_value(self, typ):
        if typ == ptr_str():
            return SymbolOperand(ptr_str(), self._string_label(""))
        if typ == ptr_arr_i8():
            result = self._inst("call", [ConstIntOperand(I64, 0)], result_type=ptr_arr_i8(), type=ptr_arr_i8(), callee="new_arr_i8_empty")
            return ValueOperand(result)
        if typ == ptr_arr_i64():
            result = self._inst("call", [ConstIntOperand(I64, 0)], result_type=ptr_arr_i64(), type=ptr(), callee="__epic_arr_qword_new")
            return ValueOperand(result)
        if typ == ptr_map_str_i64():
            result = self._inst("call", [], result_type=ptr_map_str_i64(), type=ptr_map_str_i64(), callee="map_new")
            return ValueOperand(result)
        if typ.kind == "ptr" and typ.pointee is not None and typ.pointee.kind == "struct" and typ.pointee.name in self.structs and not typ.pointee.name.startswith("_arr_"):
            return self._alloc_struct(typ.pointee.name)
        return ConstIntOperand(typ, 0)

    def _string_label(self, text):
        if text not in self.strings:
            self.string_counter += 1
            label = f"@str.{self.string_counter}"
            self.strings[text] = label
            self.program.globals.append(MirGlobal(label, ptr_str(), text))
        return self.strings[text]

    def _compute_struct_layouts(self, ast):
        self.structs = {}
        self.structs["str"] = {
            "fields": {
                "data": {"type": ptr(I8), "offset": 0},
                "len": {"type": I64, "offset": 8},
            },
            "size": 16,
        }
        self.structs["_arr_i8"] = {
            "fields": {
                "data": {"type": ptr(I8), "offset": 0},
                "len": {"type": I64, "offset": 8},
                "cap": {"type": I64, "offset": 16},
            },
            "size": 24,
        }
        self.structs["_arr_i64"] = {
            "fields": {
                "data": {"type": ptr(I64), "offset": 0},
                "len": {"type": I64, "offset": 8},
                "cap": {"type": I64, "offset": 16},
            },
            "size": 24,
        }
        self.structs["_arr_str"] = {
            "fields": {
                "data": {"type": ptr(ptr_str()), "offset": 0},
                "len": {"type": I64, "offset": 8},
                "cap": {"type": I64, "offset": 16},
            },
            "size": 24,
        }
        self.structs["_map_str_i64"] = {
            "fields": {
                "entries": {"type": ptr(I64), "offset": 0},
                "len": {"type": I64, "offset": 8},
                "cap": {"type": I64, "offset": 16},
            },
            "size": 24,
        }
        for type_node in getattr(ast, "types", []):
            self.structs[type_node.name] = {
                "fields": {
                    "tag": {"type": I64, "offset": 0},
                    "data": {"type": ptr(I64), "offset": 8},
                },
                "size": 16,
            }
        for struct_node in ast.structs:
            self.structs[struct_node.name] = {"fields": {}, "size": 0}
        for struct_node in ast.structs:
            fields = {}
            offset = 0
            for field in struct_node.fields:
                fields[field.name] = {"type": self._type(field.type), "offset": offset}
                offset += 8
            self.structs[struct_node.name] = {"fields": fields, "size": max(offset, 1)}
        for type_node in getattr(ast, "types", []):
            variants = {}
            for tag, variant in enumerate(type_node.variants):
                payload_name = None
                if variant.fields:
                    payload_name = f"{type_node.name}_{variant.name}"
                    fields = {}
                    offset = 0
                    for field in variant.fields:
                        fields[field.name] = {"type": self._type(field.type), "offset": offset}
                        offset += 8
                    self.structs[payload_name] = {"fields": fields, "size": max(offset, 1)}
                variants[variant.name] = {"tag": tag, "payload": payload_name}
            self.adts[type_node.name] = variants
        for struct_name in list(self.structs):
            self.structs[f"_arr_{struct_name}"] = {
                "fields": {
                    "data": {"type": ptr(ptr_struct(struct_name)), "offset": 0},
                    "len": {"type": I64, "offset": 8},
                    "cap": {"type": I64, "offset": 16},
                },
                "size": 24,
            }
        self.program.structs = self.structs
        self.program.adts = self.adts


def ptr_str():
    from mir import I8, struct

    return ptr(struct("str"))


def ptr_arr_i8():
    from mir import struct

    return ptr(struct("_arr_i8"))


def ptr_arr_i64():
    from mir import struct

    return ptr(struct("_arr_i64"))


def ptr_struct(name):
    from mir import struct

    return ptr(struct(name))


def ptr_arr_struct(name):
    from mir import struct

    return ptr(struct(f"_arr_{name}"))


def ptr_arr_str():
    from mir import struct

    return ptr(struct("_arr_str"))


def ptr_map_str_i64():
    from mir import struct

    return ptr(struct("_map_str_i64"))


def ast_to_mir(ast):
    return MirCodegen().emit_program(ast)
