"""AST -> Epic MIR codegen for the initial machine-backend path."""

from ast_nodes import *
from mir import (
    BOOL,
    I64,
    VOID,
    Br,
    CondBr,
    ConstBoolOperand,
    ConstIntOperand,
    MirBlock,
    MirExtern,
    MirFunction,
    MirImport,
    MirInst,
    MirParam,
    MirProgram,
    MirSignature,
    MirValue,
    Ret,
    ValueOperand,
    ptr,
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

    def emit_program(self, ast):
        self.func_sigs = {
            fn.name: MirSignature([self._type(p.type) for p in fn.params], self._type(fn.ret_type))
            for fn in ast.funcs
        }
        self.program.imports.append(MirImport("ExitProcess", MirSignature([I64], VOID), "kernel32.dll"))
        self.program.externs.append(MirExtern("str_i64", MirSignature([I64], ptr_str())))
        self.program.externs.append(MirExtern("print_str", MirSignature([ptr_str()], VOID)))
        self.program.externs.append(MirExtern("print_newline", MirSignature([], VOID)))
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
            value = self._emit_expr(stmt.value) if stmt.value is not None else ConstIntOperand(typ, 0)
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
        self.block = cond_block
        cond = self._emit_expr(stmt.cond)
        self.block.terminator = CondBr(cond, body_block.name, end_block.name)
        self.block = body_block
        self._emit_block(stmt.body)
        if self.block.terminator is None:
            self.block.terminator = Br(cond_block.name)
        self.block = end_block

    def _emit_expr(self, expr):
        if isinstance(expr, LiteralNode):
            return ConstIntOperand(I64, expr.value)
        if isinstance(expr, BoolNode):
            return ConstBoolOperand(bool(expr.value))
        if isinstance(expr, VarNode):
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
        raise MirCodegenError(f"machine MIR does not support expr yet: {type(expr).__name__}")

    def _emit_binary(self, expr):
        left = self._emit_expr(expr.left)
        right = self._emit_expr(expr.right)
        op_map = {"+": "add", "-": "sub", "*": "mul", "/": "div", "%": "mod"}
        cmp_map = {"==": "eq", "!=": "ne", "<": "lt", ">": "gt", "<=": "le", ">=": "ge"}
        if expr.op in op_map:
            return ValueOperand(self._inst(op_map[expr.op], [left, right], result_type=I64))
        if expr.op in cmp_map:
            return ValueOperand(self._inst(f"icmp.{cmp_map[expr.op]}", [left, right], result_type=BOOL))
        raise MirCodegenError(f"unsupported binary op: {expr.op}")

    def _emit_call(self, expr):
        name = expr.name
        if expr.namespace == "os" and name == "ExitProcess":
            arg = self._emit_expr(expr.args[0])
            self._inst("call", [arg], type=VOID, callee="ExitProcess")
            return ConstIntOperand(I64, 0)
        if expr.namespace:
            raise MirCodegenError(f"unsupported namespaced call: {expr.namespace}.{name}")
        if name == "println":
            if len(expr.args) != 1:
                raise MirCodegenError("println expects one argument in machine MIR")
            as_str = self._emit_call(CallNode("str", [expr.args[0]]))
            self._inst("call", [as_str], type=VOID, callee="print_str")
            self._inst("call", [], type=VOID, callee="print_newline")
            return ConstIntOperand(I64, 0)
        if name == "print":
            if len(expr.args) != 1:
                raise MirCodegenError("print expects one argument in machine MIR")
            as_str = self._emit_call(CallNode("str", [expr.args[0]]))
            self._inst("call", [as_str], type=VOID, callee="print_str")
            return ConstIntOperand(I64, 0)
        if name == "str":
            arg = self._emit_expr(expr.args[0])
            result = self._inst("call", [arg], result_type=ptr_str(), type=ptr_str(), callee="str_i64")
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
        if isinstance(expr, CallNode) and expr.name == "str":
            return ptr_str()
        if isinstance(expr, BinaryNode) and expr.op in ("==", "!=", "<", ">", "<=", ">="):
            return BOOL
        return I64


def ptr_str():
    from mir import I8, struct

    return ptr(struct("str"))


def ast_to_mir(ast):
    return MirCodegen().emit_program(ast)

