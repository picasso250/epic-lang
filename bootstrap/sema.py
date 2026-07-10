"""Semantic analysis for the Python reference compiler."""

from __future__ import annotations

from dataclasses import dataclass

from ast_nodes import *
from epic_builtins import BUILTIN_FUNCTIONS, PSEUDO_BUILTINS
from epic_types import ARRAY, BOOL, I32, I64, I8, NAMED, PTR, STR, U32, U64, U8, VOID, EpicType
from parser import dump_ast_text


class SemanticError(RuntimeError):
    pass


@dataclass
class ExprInfo:
    type: EpicType
    literal_int: int | None = None


class SemanticAnalyzer:
    INT_RANGES = {
        "u8": (0, 255),
        "i32": (-2147483648, 2147483647),
        "u32": (0, 4294967295),
        "i64": (-9223372036854775808, 9223372036854775807),
        "u64": (0, 18446744073709551615),
    }

    EXTERN_ABI_TYPES = {I32, U32, I64, U64}

    INTEGER_CONVERSIONS = {
        "i64": I64,
        "u64": U64,
        "i32": I32,
        "u32": U32,
        "u8": U8,
    }

    def __init__(self, program):
        self.program = program
        self.struct_names = {s.name for s in program.structs}
        self.union_defs = {u.name: u.members for u in program.unions}
        self.union_names = set(self.union_defs)
        self.union_tags = {}
        self.struct_fields = {}
        self.func_sigs = {}
        self.scopes = []
        self.fn_name = None
        self.loop_depth = 0

    def analyze(self):
        self._build_types()
        self._build_unions()
        self._build_functions()
        for ext in self.program.externs:
            if not ext.library:
                self._fail_global(f"extern {ext.name} requires a non-empty library")
            if "$" in ext.library or "\0" in ext.library:
                self._fail_global(f"extern {ext.name} library contains an unsupported character")
            if ext.name in BUILTIN_FUNCTIONS or ext.name in PSEUDO_BUILTINS:
                self._fail_global(f"reserved builtin function name: {ext.name}")
            params = []
            for param in ext.params:
                param.resolved_type = self._type_name(param.type)
                if param.resolved_type not in self.EXTERN_ABI_TYPES:
                    self._fail_global(f"extern {ext.name} parameter {param.name} has unsupported ABI type {param.resolved_type}")
                params.append(param.resolved_type)
            ext.resolved_type = self._type_name(ext.ret_type)
            if ext.resolved_type != VOID and ext.resolved_type not in self.EXTERN_ABI_TYPES:
                self._fail_global(f"extern {ext.name} has unsupported ABI return type {ext.resolved_type}")
            if ext.name in self.func_sigs:
                self._fail_global(f"duplicate function {ext.name}")
            self.func_sigs[ext.name] = (params, ext.resolved_type)
        for fn in self.program.funcs:
            self._analyze_function(fn)
        assert_typed_program(self.program)
        return self.program

    def _build_types(self):
        for struct in self.program.structs:
            fields = {}
            for field in struct.fields:
                if field.name in fields:
                    self._fail_global(f"duplicate field {struct.name}.{field.name}")
                field.resolved_type = self._type_name(field.type)
                fields[field.name] = field.resolved_type
            self.struct_fields[struct.name] = fields

    def _build_unions(self):
        for union in self.program.unions:
            if union.name in self.struct_names:
                self._fail_global(f"type {union.name} conflicts with struct {union.name}")
            if not union.members:
                self._fail_global(f"union {union.name} requires at least one member")
            seen = set()
            tags = {}
            for idx, member in enumerate(union.members, start=1):
                if member in seen:
                    self._fail_global(f"duplicate union member {union.name}.{member}")
                seen.add(member)
                if member not in self.struct_names:
                    self._fail_global(f"union member {union.name}.{member} must be a struct")
                tags[member] = idx
            self.union_tags[union.name] = tags

    def _build_functions(self):
        for fn in self.program.funcs:
            if fn.name in self.func_sigs:
                self._fail_global(f"duplicate function {fn.name}")
            if fn.method_name:
                if fn.receiver_type.kind != "named" or fn.receiver_type.name not in self.struct_names:
                    self._fail_global(f"method receiver must be a user-defined struct, got {fn.receiver_type}")
            params = []
            for param in fn.params:
                param.resolved_type = self._type_name(param.type)
                typ = param.resolved_type
                if typ == VOID:
                    self._fail_global(f"function {fn.name} parameter {param.name} cannot have type void")
                params.append(typ)
            if fn.method_name:
                if not params or params[0] != fn.receiver_type:
                    self._fail_global(f"method {fn.receiver_type}.{fn.method_name} receiver mismatch")
            if fn.name in BUILTIN_FUNCTIONS or fn.name in PSEUDO_BUILTINS:
                self._fail_global(f"reserved builtin function name: {fn.name}")
            fn.resolved_type = self._type_name(fn.ret_type)
            self.func_sigs[fn.name] = (params, fn.resolved_type)


    def _analyze_function(self, fn):
        self.fn_name = fn.name
        self.scopes = [{"argv": ARRAY(STR)}]
        self.loop_depth = 0
        for param in fn.params:
            self._define_local(param.name, param.resolved_type)

        tail_info = self._analyze_function_body(fn.body)
        ret_type = fn.resolved_type
        if self._block_returns(fn.body):
            return
        if tail_info is not None:
            self._check_assign(ret_type, tail_info, "function tail")
            return
        if ret_type != VOID:
            self._fail(f"function must return {ret_type} on all paths")

    def _analyze_function_body(self, block):
        tail_info = None
        self._push_scope()
        try:
            for stmt in block.stmts:
                self._analyze_stmt(stmt)
            if block.value_expr is not None:
                tail_info = self._expr(block.value_expr)
        finally:
            self._pop_scope()
        return tail_info

    def _analyze_block(self, block):
        self._push_scope()
        try:
            for stmt in block.stmts:
                self._analyze_stmt(stmt)
            if block.value_expr is not None:
                self._expr(block.value_expr)
        finally:
            self._pop_scope()

    def _analyze_stmt(self, stmt):
        if isinstance(stmt, ExprStmtNode):
            self._expr(stmt.expr)
            return
        if isinstance(stmt, LetNode):
            self._analyze_let(stmt)
            return
        if isinstance(stmt, AssignNode):
            target = self._lookup(stmt.name)
            self._check_assign(target, self._expr(stmt.value), f"assignment to {stmt.name}")
            return
        if isinstance(stmt, FieldSetNode):
            target = self._field_access_type(stmt.object, stmt.field)
            self._check_assign(target, self._expr(stmt.value), f"assignment to field {stmt.field}")
            return
        if isinstance(stmt, SubscriptAssignNode):
            target = self._subscript_type(stmt.base, stmt.index)
            self._check_assign(target, self._expr(stmt.value), "subscript assignment")
            return
        if isinstance(stmt, AssignOpNode):
            self._analyze_assign_op(stmt)
            return
        if isinstance(stmt, IfNode):
            self._expect_bool(self._expr(stmt.cond), "if condition")
            self._analyze_block(stmt.then_block)
            if stmt.else_block is not None:
                self._analyze_block(stmt.else_block)
            return
        if isinstance(stmt, WhileNode):
            self._expect_bool(self._expr(stmt.cond), "for condition")
            self.loop_depth += 1
            self._analyze_block(stmt.body)
            self.loop_depth -= 1
            return
        if isinstance(stmt, ForRangeNode):
            self._expect_integer(self._expr(stmt.start), "for range start")
            self._expect_integer(self._expr(stmt.end), "for range end")
            stmt.resolved_type = I64
            self._push_scope()
            self._define_local(stmt.name, I64)
            self.loop_depth += 1
            try:
                self._analyze_block(stmt.body)
            finally:
                self.loop_depth -= 1
                self._pop_scope()
            return
        if isinstance(stmt, ForInNode):
            source = self._expr(stmt.source)
            if source.type.kind == "array":
                stmt.resolved_type = I64
            elif source.type == STR:
                self._fail("for-in over str is not supported; use bytes(s) to iterate bytes")
            else:
                self._fail(f"for-in expected array, got {source.type}")
            self._push_scope()
            self._define_local(stmt.name, stmt.resolved_type)
            self.loop_depth += 1
            try:
                self._analyze_block(stmt.body)
            finally:
                self.loop_depth -= 1
                self._pop_scope()
            return
        if isinstance(stmt, BreakNode):
            if self.loop_depth == 0:
                self._fail("break outside loop")
            return
        if isinstance(stmt, ContinueNode):
            if self.loop_depth == 0:
                self._fail("continue outside loop")
            return
        if isinstance(stmt, ReturnNode):
            self._analyze_return(stmt)
            return
        if isinstance(stmt, PanicNode):
            self._expr(stmt.message)
            return
        if isinstance(stmt, AssertNode):
            self._expect_bool(self._expr(stmt.cond), "assert condition")
            if stmt.message is not None:
                self._expr(stmt.message)
            return
        if isinstance(stmt, MatchNode):
            self._analyze_match(stmt)
            return
        self._fail(f"unsupported statement: {type(stmt).__name__}")

    def _analyze_let(self, stmt):
        if stmt.value is None:
            self._fail(f"let {stmt.name} requires an initializer")
        target = self._type_name(stmt.var_type) if stmt.var_type is not None else None
        value = self._expr(stmt.value)
        if target is None:
            target = value.type
            if target == VOID:
                self._fail(f"let {stmt.name} cannot infer void")
        elif target == VOID:
            self._fail(f"let {stmt.name} cannot have type void")
        self._check_assign(target, value, f"let {stmt.name}")
        stmt.resolved_type = target
        self._define_local(stmt.name, target)

    def _analyze_assign_op(self, stmt):
        target_type = self._lvalue_type(stmt.target)
        rhs = self._expr(stmt.value)
        if stmt.op == "+" and target_type == STR:
            self._fail("string += is not supported; use s = s + rhs")
            return
        if not self._is_integer(target_type):
            self._fail(f"compound assignment expected integer target, got {target_type}")
        self._expect_integer(rhs, "compound assignment value")
        if target_type != rhs.type:
            self._fail(f"compound assignment expected matching integer types, got {target_type} and {rhs.type}; use an explicit conversion")

    def _analyze_return(self, stmt):
        ret_type = self.func_sigs[self.fn_name][1]
        if ret_type == VOID:
            if stmt.expr is not None:
                self._check_assign(VOID, self._expr(stmt.expr), "return")
            return
        if stmt.expr is None:
            self._fail(f"return expected {ret_type}, got void")
        self._check_assign(ret_type, self._expr(stmt.expr), "return")

    def _analyze_match(self, stmt):
        scrutinee = self._expr(stmt.expr)
        if scrutinee.type.kind == "named" and scrutinee.type.name in self.union_names:
            self._analyze_union_match(stmt, scrutinee.type.name)
            return
        seen_else = False
        for idx, case in enumerate(stmt.cases):
            if seen_else:
                self._fail("match else must be the final case")
            if case.is_else:
                seen_else = True
                self._analyze_block(case.body)
                continue
            if case.variant_name or case.binding_name:
                self._fail("ADT match case requires union scrutinee")
            self._analyze_match_case(scrutinee.type, case)

    def _analyze_union_match(self, stmt, union_name):
        stmt.union_name = union_name
        members = set(self.union_defs[union_name])
        seen = set()
        seen_else = False
        for case in stmt.cases:
            if seen_else:
                self._fail("match _ must be the final case")
            if case.is_else:
                seen_else = True
                self._analyze_block(case.body)
                continue
            if case.pattern is not None:
                self._fail(f"ADT match on {union_name} requires variant binding cases")
            if not case.variant_name or not case.binding_name:
                self._fail(f"ADT match on {union_name} requires variant binding cases")
            if case.variant_name not in members:
                self._fail(f"{case.variant_name} is not a member of {union_name}")
            if case.variant_name in seen:
                self._fail(f"duplicate match case {case.variant_name}")
            seen.add(case.variant_name)
            case.binding_type = NAMED(case.variant_name)
            self._push_scope()
            self._define_local(case.binding_name, case.binding_type)
            try:
                self._analyze_block(case.body)
            finally:
                self._pop_scope()
        if not seen_else:
            missing = [member for member in self.union_defs[union_name] if member not in seen]
            if missing:
                self._fail(f"non-exhaustive match for {union_name}; missing {', '.join(missing)}")

    def _analyze_match_case(self, scrutinee_type, case):
        if case.bindings:
            self._fail("match bindings are not supported")
        self._check_assign(scrutinee_type, self._expr(case.pattern), "match pattern")
        self._analyze_block(case.body)

    def _expr(self, expr):
        if expr is None:
            self._fail("missing expression")
        info = self._expr_info(expr)
        expr.resolved_type = info.type
        return info

    def _expr_info(self, expr):
        if expr is None:
            self._fail("missing expression")
        if isinstance(expr, LiteralNode):
            if expr.value > self.INT_RANGES["i64"][1]:
                self._fail(f"integer literal {expr.value} out of range for i64")
            return ExprInfo(I64, expr.value)
        if isinstance(expr, CharNode):
            return ExprInfo(U8, expr.value)
        if isinstance(expr, BoolNode):
            return ExprInfo(BOOL, expr.value)
        if isinstance(expr, StringNode):
            return ExprInfo(STR)
        if isinstance(expr, FStringNode):
            for part in expr.parts:
                if isinstance(part, FStringExprPart):
                    self._check_str_convertible(self._expr(part.expr), "f-string expression")
            return ExprInfo(STR)
        if isinstance(expr, VarNode):
            return ExprInfo(self._lookup(expr.name))
        if isinstance(expr, UnaryNode):
            return self._unary_expr(expr)
        if isinstance(expr, BinaryNode):
            return self._binary_expr(expr)
        if isinstance(expr, CallNode):
            return self._call_expr(expr)
        if isinstance(expr, DotCallNode):
            return self._dot_call_expr(expr)
        if isinstance(expr, FieldAccessNode):
            return ExprInfo(self._field_access_type(expr.object, expr.field))
        if isinstance(expr, NullCheckNode):
            return ExprInfo(self._null_check_type(expr))
        if isinstance(expr, SubscriptNode):
            return ExprInfo(self._subscript_type(expr.base, expr.index))
        if isinstance(expr, SliceNode):
            base = self._expr(expr.base)
            if base.type != STR and not (base.type.kind == "array" and base.type.elem == U8):
                self._fail("slice only supports str and u8[]")
            self._expect_integer(self._expr(expr.start), "slice start")
            self._expect_integer(self._expr(expr.end), "slice end")
            return ExprInfo(base.type)
        if isinstance(expr, NewArrayNode):
            elem = self._type_name(expr.elem_type)
            if elem == VOID:
                self._fail("array element type cannot be void")
            if expr.count is not None:
                self._expect_integer(self._expr(expr.count), "array length")
            return ExprInfo(ARRAY(elem))
        if isinstance(expr, ArrayLiteralNode):
            elem = self._type_name(expr.elem_type)
            if elem == VOID:
                self._fail("array element type cannot be void")
            for value in expr.values:
                self._check_assign(elem, self._expr(value), "array literal element")
            return ExprInfo(ARRAY(elem))
        if isinstance(expr, StructInitNode):
            return self._struct_init_expr(expr)
        if isinstance(expr, UnionInitNode):
            return self._union_init_expr(expr)
        self._fail(f"unsupported expression: {type(expr).__name__}")

    def _unary_expr(self, expr):
        inner = self._expr(expr.expr)
        if expr.op == "!":
            self._expect_bool(inner, "unary !")
            return ExprInfo(BOOL)
        if expr.op in ("-", "~"):
            self._expect_integer(inner, f"unary {expr.op}")
            literal = None
            if inner.literal_int is not None:
                literal = -inner.literal_int if expr.op == "-" else ~inner.literal_int
            return ExprInfo(I64, literal)
        self._fail(f"unsupported unary operator {expr.op}")

    def _binary_expr(self, expr):
        left = self._expr(expr.left)
        right = self._expr(expr.right)
        if expr.op in ("&&", "||"):
            self._expect_bool(left, expr.op)
            self._expect_bool(right, expr.op)
            return ExprInfo(BOOL)
        if expr.op == "+" and (left.type == STR or right.type == STR):
            if left.type != STR or right.type != STR:
                self._fail(f"string concatenation requires str operands, got {left.type} and {right.type}")
            return ExprInfo(STR)
        if expr.op in ("<", ">", "<=", ">=") and (left.type == STR or right.type == STR):
            self._fail(f"string ordering comparison {expr.op} is not supported")
        if expr.op in ("==", "!=", "<", ">", "<=", ">="):
            if self._is_integer(left.type) and self._is_integer(right.type):
                if left.type != right.type:
                    self._fail(f"comparison {expr.op} expected {left.type}, got {right.type}; use an explicit conversion")
                return ExprInfo(BOOL)
            if left.type != right.type:
                self._fail(f"comparison {expr.op} expected {left.type}, got {right.type}")
            return ExprInfo(BOOL)
        if expr.op in ("<<", ">>", ">>>"):
            self._expect_integer(left, f"operator {expr.op} left")
            self._expect_integer(right, f"operator {expr.op} count")
            literal = self._fold_binary_literal(expr.op, left.literal_int, right.literal_int)
            return ExprInfo(left.type, literal)
        if expr.op in ("+", "-", "*", "/", "%", "&", "|", "^"):
            self._expect_integer(left, f"operator {expr.op} left")
            self._expect_integer(right, f"operator {expr.op} right")
            if left.type != right.type:
                self._fail(f"operator {expr.op} expected matching integer types, got {left.type} and {right.type}; use an explicit conversion")
            literal = self._fold_binary_literal(expr.op, left.literal_int, right.literal_int)
            return ExprInfo(left.type, literal)
        self._fail(f"unsupported binary operator {expr.op}")

    def _call_expr(self, expr):
        name = expr.name
        if name == "print":
            if len(expr.args) != 1:
                self._fail("print expects 1 argument")
            arg = self._expr(expr.args[0])
            if arg.type != STR:
                self._fail(f"print expected str, got {arg.type}")
            return ExprInfo(VOID)
        if name == "println":
            if len(expr.args) > 1:
                self._fail("println expects at most one argument")
            if expr.args:
                arg = self._expr(expr.args[0])
                if arg.type != STR:
                    self._fail(f"println expected str, got {arg.type}")
            return ExprInfo(VOID)
        if name == "exit":
            self._check_call_args(name, [I64], expr.args)
            return ExprInfo(VOID)
        if name == "str":
            self._check_arity(name, 1, expr.args)
            self._check_str_convertible(self._expr(expr.args[0]), "str")
            return ExprInfo(STR)
        if name == "cstr":
            self._check_call_args(name, [STR], expr.args)
            return ExprInfo(U64)
        if name in self.INTEGER_CONVERSIONS:
            self._check_arity(name, 1, expr.args)
            arg = self._expr(expr.args[0])
            self._expect_integer(arg, f"{name} argument")
            return ExprInfo(self.INTEGER_CONVERSIONS[name])
        if name == "bool":
            self._check_arity(name, 1, expr.args)
            arg = self._expr(expr.args[0])
            if arg.type != BOOL and not self._is_integer(arg.type):
                self._fail(f"bool expected integer or bool, got {arg.type}")
            return ExprInfo(BOOL)
        if name == "bytes":
            self._check_call_args(name, [STR], expr.args)
            return ExprInfo(ARRAY(U8))
        if name == "read_file":
            self._check_call_args(name, [STR], expr.args)
            return ExprInfo(ARRAY(U8))
        if name == "write_file":
            self._check_call_args(name, [STR, ARRAY(U8)], expr.args)
            return ExprInfo(I64)
        if name == "push":
            self._fail("push is removed from function-call surface; use xs.push(x)")
        if name == "pop":
            self._fail("pop is removed from function-call surface; use xs.pop()")
        if name == "extend":
            self._fail("extend is removed from function-call surface; use dst.extend(src)")
        if name == "len":
            self._check_arity(name, 1, expr.args)
            arg = self._expr(expr.args[0])
            if arg.type != STR and arg.type.kind != "array":
                self._fail(f"len expected str or array, got {arg.type}")
            return ExprInfo(I64)
        if name == "cap":
            self._check_arity(name, 1, expr.args)
            arg = self._expr(expr.args[0])
            if arg.type.kind != "array":
                self._fail(f"cap expected array, got {arg.type}")
            return ExprInfo(I64)

        if name not in self.func_sigs:
            self._fail(f"unknown function {name}")
        params, ret = self.func_sigs[name]
        self._check_call_args(name, params, expr.args)
        return ExprInfo(ret)

    def _dot_call_expr(self, expr):
        receiver = self._expr(expr.object)
        if receiver.type.kind == "array":
            if expr.name == "push":
                self._check_arity("push", 1, expr.args)
                self._check_assign(receiver.type.elem, self._expr(expr.args[0]), "push value")
                return ExprInfo(VOID)
            if expr.name == "pop":
                self._check_arity("pop", 0, expr.args)
                return ExprInfo(receiver.type.elem)
            if expr.name == "extend":
                self._check_arity("extend", 1, expr.args)
                src = self._expr(expr.args[0])
                if src.type.kind != "array" or src.type.elem != receiver.type.elem:
                    self._fail("extend expects an array with the same element type")
                return ExprInfo(VOID)
            self._fail(f"array type {receiver.type} has no method {expr.name}")
        if receiver.type.kind == "named":
            method_symbol = f"{receiver.type.name}__{expr.name}"
            if method_symbol not in self.func_sigs:
                self._fail(f"type {receiver.type.name} has no method {expr.name}; expected function {method_symbol}")
            params, ret = self.func_sigs[method_symbol]
            self._check_call_args(method_symbol, params, [expr.object] + expr.args)
            return ExprInfo(ret)
        self._fail("method calls are only supported for arrays and user structs")
        return ExprInfo(VOID)

    def _struct_init_expr(self, expr):
        if expr.type_name not in self.struct_fields:
            self._fail(f"unknown struct {expr.type_name}")
        self._check_named_fields(self.struct_fields[expr.type_name], expr.fields, expr.type_name)
        return ExprInfo(NAMED(expr.type_name))

    def _union_init_expr(self, expr):
        if expr.type_name not in self.union_names:
            self._fail(f"unknown union {expr.type_name}")
        payload = self._expr(expr.payload)
        if payload.type.kind != "named" or payload.type.name not in self.struct_names:
            self._fail(f"new {expr.type_name}(...) expected struct payload, got {payload.type}")
        if payload.type.name not in self.union_defs[expr.type_name]:
            self._fail(f"new {expr.type_name}(...) expected one of {', '.join(self.union_defs[expr.type_name])}, got {payload.type.name}")
        return ExprInfo(NAMED(expr.type_name))

    def _check_named_fields(self, fields, supplied_fields, owner):
        seen = set()
        for name, value in supplied_fields:
            if name in seen:
                self._fail(f"duplicate field initializer {owner}.{name}")
            seen.add(name)
            if name not in fields:
                self._fail(f"unknown field {owner}.{name}")
            self._check_assign(fields[name], self._expr(value), f"field {owner}.{name}")

    def _lvalue_type(self, target):
        if isinstance(target, VarNode):
            target.resolved_type = self._lookup(target.name)
            return target.resolved_type
        if isinstance(target, FieldAccessNode):
            return self._expr(target).type
        if isinstance(target, SubscriptNode):
            return self._expr(target).type
        self._fail(f"unsupported assignment target {type(target).__name__}")

    def _subscript_type(self, base_expr, index_expr):
        base = self._expr(base_expr)
        self._expect_integer(self._expr(index_expr), "subscript index")
        if base.type == STR:
            self._fail("str subscript is removed; use bytes(s)[i]")
        if base.type.kind == "array":
            return base.type.elem
        if base.type.kind == "ptr":
            return base.type.elem
        self._fail(f"subscript expected array or pointer, got {base.type}")

    def _direct_field_type(self, struct_name, field):
        fields = self.struct_fields.get(struct_name)
        if fields is None or field not in fields:
            self._fail(f"unknown field {struct_name}.{field}")
        return fields[field]

    def _union_common_field_type(self, union_name, field):
        found = None
        for member in self.union_defs[union_name]:
            fields = self.struct_fields[member]
            if field not in fields:
                self._fail(f"union {union_name} has no common field {field}")
            candidate = fields[field]
            if found is not None and candidate != found:
                self._fail(f"union {union_name} field {field} has inconsistent types")
            found = candidate
        if found is None:
            self._fail(f"union {union_name} has no common field {field}")
        return found

    def _field_guard_key(self, object_expr, field):
        if isinstance(object_expr, VarNode):
            return f"{object_expr.name}.{field}"
        return None

    def _is_reference_type(self, typ):
        return typ == STR or typ.kind in ("array", "named")

    def _null_check_type(self, expr):
        inner = self._expr(expr.expr).type
        if not self._is_reference_type(inner):
            self._fail(f"null check expected reference, got {inner}")
        return BOOL

    def _field_access_type(self, object_expr, field):
        return self._field_type(self._expr(object_expr).type, field)

    def _field_type(self, base_type, field):
        if base_type == STR:
            self._fail(f"unknown field str.{field}")
        if base_type.kind == "array":
            self._fail(f"unknown field {base_type}.{field}")
        if base_type.kind == "named":
            fields = self.struct_fields.get(base_type.name)
            if fields is None:
                if base_type.name in self.union_names:
                    return self._union_common_field_type(base_type.name, field)
                self._fail(f"field access expected struct, got {base_type}")
            if field in fields:
                return fields[field]
            self._fail(f"unknown field {base_type.name}.{field}")
        self._fail(f"field access expected aggregate, got {base_type}")

    def _type_name(self, name):
        if name is None:
            return VOID
        if not isinstance(name, EpicType):
            self._fail_global(f"internal parser produced non-EpicType type: {name}")
        if name.kind == "array":
            elem = self._type_name(name.elem)
            if elem == VOID:
                self._fail_global("array element type cannot be void")
            return ARRAY(elem)
        if name.kind == "ptr":
            return PTR(self._type_name(name.elem))
        if name.kind == "named":
            if name.name in self.struct_names or name.name in self.union_names:
                return name
            self._fail_global(f"unknown type {name}")
        if name in (I64, U64, I32, U32, I8, U8, BOOL, VOID, STR):
            return name
        self._fail_global(f"unknown type {name}")

    def _check_str_convertible(self, info, context):
        if info.type == STR or info.type == BOOL or info.type == ARRAY(U8):
            return
        if self._is_integer(info.type):
            if info.literal_int is not None:
                self._check_int_literal_range(info.type, info.literal_int, context)
            return
        if info.type == VOID:
            self._fail(f"{context} argument cannot be void")
        self._fail(f"{context} expected str, integer, bool, or u8[], got {info.type}")

    def _check_call_args(self, name, params, args):
        if len(params) != len(args):
            self._fail(f"{name} expected {len(params)} arguments, got {len(args)}")
        for idx, (expected, arg) in enumerate(zip(params, args)):
            self._check_assign(expected, self._expr(arg), f"{name} argument {idx + 1}")

    def _check_arity(self, name, expected, args):
        if len(args) != expected:
            self._fail(f"{name} expected {expected} arguments, got {len(args)}")

    def _check_assign(self, target, value, context):
        if target == VOID:
            if value.type == VOID:
                return
            self._fail(f"{context} expected void, got {value.type}")
        if value.type == VOID:
            self._fail(f"{context} expected {target}, got void")
        if target == value.type:
            if self._is_integer(target) and value.literal_int is not None:
                self._check_int_literal_range(target, value.literal_int, context)
            return
        if self._is_integer(target) and self._is_integer(value.type):
            self._fail(f"{context} expected {target}, got {value.type}; use {target}(... ) for an explicit conversion")
        self._fail(f"{context} expected {target}, got {value.type}")

    def _check_int_literal_range(self, target, value, context):
        if target.kind not in self.INT_RANGES:
            return
        lo, hi = self.INT_RANGES[target.kind]
        if not lo <= value <= hi:
            self._fail(f"{context} literal {value} out of range for {target}")

    def _expect_bool(self, info, context):
        if info.type != BOOL:
            self._fail(f"{context} expected bool, got {info.type}")

    def _expect_integer(self, info, context):
        if not self._is_integer(info.type):
            self._fail(f"{context} expected integer, got {info.type}")

    def _lookup(self, name):
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        self._fail(f"undefined variable {name}")

    def _push_scope(self):
        self.scopes.append({})

    def _pop_scope(self):
        self.scopes.pop()

    def _define_local(self, name, typ):
        if not self.scopes:
            self._fail("internal: no active local scope")
        self.scopes[-1][name] = typ

    def _block_returns(self, block):
        for stmt in block.stmts:
            if self._stmt_returns(stmt):
                return True
        if block.value_expr is not None and self._is_terminating_call(block.value_expr):
            return True
        return False

    def _stmt_returns(self, stmt):
        if isinstance(stmt, ReturnNode):
            return True
        if isinstance(stmt, PanicNode):
            return True
        if isinstance(stmt, ExprStmtNode) and self._is_terminating_call(stmt.expr):
            return True
        if isinstance(stmt, IfNode):
            return (
                stmt.else_block is not None
                and self._block_returns(stmt.then_block)
                and self._block_returns(stmt.else_block)
            )
        if isinstance(stmt, MatchNode):
            if not stmt.cases or not any(case.is_else for case in stmt.cases):
                return False
            return all(self._block_returns(case.body) for case in stmt.cases)
        return False

    def _is_terminating_call(self, expr):
        return isinstance(expr, CallNode) and expr.name == "exit"

    def _is_integer(self, typ):
        return typ.kind in self.INT_RANGES

    def _fold_binary_literal(self, op, left, right):
        if left is None or right is None:
            return None
        try:
            if op == "+":
                return left + right
            if op == "-":
                return left - right
            if op == "*":
                return left * right
            if op == "/":
                return None if right == 0 else int(left / right)
            if op == "%":
                return None if right == 0 else left % right
            if op == "&":
                return left & right
            if op == "|":
                return left | right
            if op == "^":
                return left ^ right
            if op == "<<":
                return left << right
            if op in (">>", ">>>"):
                return left >> right
        except ValueError:
            return None
        return None

    def _fail(self, message):
        if self.fn_name:
            raise SemanticError(f"Semantic error in {self.fn_name}: {message}")
        raise SemanticError(f"Semantic error: {message}")

    def _fail_global(self, message):
        raise SemanticError(f"Semantic error: {message}")


def assert_typed_program(program):

    def fail(path):
        raise SemanticError(f"Semantic error: internal typed AST missing resolved_type for {path}")

    def require(node, path):
        if getattr(node, "resolved_type", None) is None:
            fail(path)

    def expr(node, path):
        require(node, path)
        if isinstance(node, (LiteralNode, CharNode, BoolNode, StringNode, VarNode)):
            return
        if isinstance(node, FStringNode):
            for idx, part in enumerate(node.parts):
                if isinstance(part, FStringExprPart):
                    expr(part.expr, f"{path}.parts[{idx}]")
            return
        if isinstance(node, CallNode):
            for idx, arg in enumerate(node.args):
                expr(arg, f"{path}.args[{idx}]")
            return
        if isinstance(node, DotCallNode):
            if not (
                isinstance(node.object, FieldAccessNode)
                and isinstance(node.object.object, VarNode)
                and node.object.object.name == "os"
            ):
                expr(node.object, f"{path}.object")
            for idx, arg in enumerate(node.args):
                expr(arg, f"{path}.args[{idx}]")
            return
        if isinstance(node, BinaryNode):
            expr(node.left, f"{path}.left")
            expr(node.right, f"{path}.right")
            return
        if isinstance(node, UnaryNode):
            expr(node.expr, f"{path}.expr")
            return
        if isinstance(node, FieldAccessNode):
            expr(node.object, f"{path}.object")
            return
        if isinstance(node, NullCheckNode):
            expr(node.expr, f"{path}.expr")
            return
        if isinstance(node, SubscriptNode):
            expr(node.base, f"{path}.base")
            expr(node.index, f"{path}.index")
            return
        if isinstance(node, SliceNode):
            expr(node.base, f"{path}.base")
            if node.start is not None:
                expr(node.start, f"{path}.start")
            if node.end is not None:
                expr(node.end, f"{path}.end")
            return
        if isinstance(node, NewArrayNode):
            if node.count is not None:
                expr(node.count, f"{path}.count")
            return
        if isinstance(node, StructInitNode):
            for idx, (_, value) in enumerate(node.fields):
                expr(value, f"{path}.fields[{idx}]")
            return
        if isinstance(node, UnionInitNode):
            expr(node.payload, f"{path}.payload")
            return
        if isinstance(node, ArrayLiteralNode):
            for idx, value in enumerate(node.values):
                expr(value, f"{path}.values[{idx}]")
            return
        fail(path)

    def block(node, path):
        for idx, stmt in enumerate(node.stmts):
            statement(stmt, f"{path}.stmts[{idx}]")
        if node.value_expr is not None:
            expr(node.value_expr, f"{path}.value")

    def statement(node, path):
        if isinstance(node, ExprStmtNode):
            expr(node.expr, f"{path}.expr")
            return
        if isinstance(node, LetNode):
            require(node, path)
            if node.value is not None:
                expr(node.value, f"{path}.value")
            return
        if isinstance(node, AssignNode):
            expr(node.value, f"{path}.value")
            return
        if isinstance(node, FieldSetNode):
            expr(node.object, f"{path}.object")
            expr(node.value, f"{path}.value")
            return
        if isinstance(node, SubscriptAssignNode):
            expr(node.base, f"{path}.base")
            expr(node.index, f"{path}.index")
            expr(node.value, f"{path}.value")
            return
        if isinstance(node, AssignOpNode):
            expr(node.target, f"{path}.target")
            expr(node.value, f"{path}.value")
            return
        if isinstance(node, IfNode):
            expr(node.cond, f"{path}.cond")
            block(node.then_block, f"{path}.then")
            if node.else_block is not None:
                block(node.else_block, f"{path}.else")
            return
        if isinstance(node, WhileNode):
            expr(node.cond, f"{path}.cond")
            block(node.body, f"{path}.body")
            return
        if isinstance(node, ForRangeNode):
            require(node, path)
            expr(node.start, f"{path}.start")
            expr(node.end, f"{path}.end")
            block(node.body, f"{path}.body")
            return
        if isinstance(node, ForInNode):
            require(node, path)
            expr(node.source, f"{path}.source")
            block(node.body, f"{path}.body")
            return
        if isinstance(node, (BreakNode, ContinueNode)):
            return
        if isinstance(node, ReturnNode):
            if node.expr is not None:
                expr(node.expr, f"{path}.expr")
            return
        if isinstance(node, PanicNode):
            expr(node.message, f"{path}.message")
            return
        if isinstance(node, AssertNode):
            expr(node.cond, f"{path}.cond")
            if node.message is not None:
                expr(node.message, f"{path}.message")
            return
        if isinstance(node, MatchNode):
            expr(node.expr, f"{path}.expr")
            for idx, case in enumerate(node.cases):
                if not case.is_else and case.pattern is not None:
                    expr(case.pattern, f"{path}.cases[{idx}].pattern")
                block(case.body, f"{path}.cases[{idx}].body")
            return
        fail(path)

    for idx, struct in enumerate(program.structs):
        for field_idx, field in enumerate(struct.fields):
            require(field, f"program.structs[{idx}].fields[{field_idx}]")

    for fn_idx, fn in enumerate(program.funcs):
        require(fn, f"program.funcs[{fn_idx}]")
        for param_idx, param in enumerate(fn.params):
            require(param, f"program.funcs[{fn_idx}].params[{param_idx}]")
        block(fn.body, f"program.funcs[{fn_idx}].body")


def analyze_program(program):
    return SemanticAnalyzer(program).analyze()

def dump_typed_ast_text(node):
    return dump_ast_text(node)
