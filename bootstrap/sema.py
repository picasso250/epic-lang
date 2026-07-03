"""Semantic analysis for the Python reference compiler."""

from __future__ import annotations

from dataclasses import dataclass

from ast_nodes import *
from epic_builtins import BUILTIN_FUNCTIONS, PSEUDO_BUILTINS
from epic_types import ARRAY, BOOL, I32, I64, I8, MAP, NAMED, PTR, STR, U32, U64, U8, VOID, EpicType


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

    OS_SIGNATURES = {
        ("kernel32", "ExitProcess"): ([I64], VOID),
        ("kernel32", "Sleep"): ([I64], VOID),
        ("kernel32", "GetTickCount64"): ([], I64),
        ("kernel32", "lstrlenA"): ([I64], I64),
        ("kernel32", "lstrcmpA"): ([I64, I64], I64),
        ("kernel32", "GetStdHandle"): ([I64], I64),
        ("kernel32", "GetProcessHeap"): ([], I64),
        ("kernel32", "HeapAlloc"): ([I64, I64, I64], I64),
        ("kernel32", "CreateFileA"): ([I64, I64, I64, I64, I64, I64, I64], I64),
        ("kernel32", "GetFileSize"): ([I64, I64], I64),
        ("kernel32", "ReadFile"): ([I64, I64, I64, I64, I64], I64),
        ("kernel32", "WriteFile"): ([I64, I64, I64, I64, I64], I64),
        ("kernel32", "CloseHandle"): ([I64], I64),
        ("kernel32", "CreateProcessA"): ([], I64),
        ("kernel32", "WaitForSingleObject"): ([I64, I64], I64),
        ("kernel32", "GetExitCodeProcess"): ([I64, I64], I64),
        ("kernel32", "GetCommandLineA"): ([], I64),
        ("user32", "MessageBoxA"): ([I64, I64, I64, I64], I64),
    }

    def __init__(self, program):
        self.program = program
        self.struct_names = {s.name for s in program.structs}
        self.struct_fields = {}
        self.func_sigs = {}
        self.locals = {}
        self.fn_name = None
        self.loop_depth = 0

    def analyze(self):
        self._build_types()
        self._build_functions()
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

    def _build_functions(self):
        for fn in self.program.funcs:
            params = []
            for param in fn.params:
                param.resolved_type = self._type_name(param.type)
                typ = param.resolved_type
                if typ == VOID:
                    self._fail_global(f"function {fn.name} parameter {param.name} cannot have type void")
                params.append(typ)
            if fn.name in BUILTIN_FUNCTIONS or fn.name in PSEUDO_BUILTINS:
                self._fail_global(f"reserved builtin function name: {fn.name}")
            fn.resolved_type = self._type_name(fn.ret_type)
            self.func_sigs[fn.name] = (params, fn.resolved_type)

    def _analyze_function(self, fn):
        self.fn_name = fn.name
        self.locals = {"argv": ARRAY(STR)}
        self.loop_depth = 0
        for param in fn.params:
            self.locals[param.name] = param.resolved_type

        self._analyze_block(fn.body)
        ret_type = fn.resolved_type
        if ret_type != VOID and not self._block_returns(fn.body):
            self._fail(f"function must return {ret_type} on all paths")

    def _analyze_block(self, block):
        for stmt in block.stmts:
            self._analyze_stmt(stmt)

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
            target = self._field_type(self._expr(stmt.object).type, stmt.field)
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
            self._expect_bool(self._expr(stmt.cond), "while condition")
            self.loop_depth += 1
            self._analyze_block(stmt.body)
            self.loop_depth -= 1
            return
        if isinstance(stmt, ForRangeNode):
            self._expect_integer(self._expr(stmt.start), "for range start")
            self._expect_integer(self._expr(stmt.end), "for range end")
            stmt.resolved_type = I64
            self.locals[stmt.name] = I64
            self.loop_depth += 1
            self._analyze_block(stmt.body)
            self.loop_depth -= 1
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
        if stmt.var_type is None and stmt.value is None:
            self._fail(f"let {stmt.name} needs a type annotation or initializer")
        target = self._type_name(stmt.var_type) if stmt.var_type is not None else None
        value = self._expr(stmt.value) if stmt.value is not None else None
        if target is None:
            target = value.type
            if target == VOID:
                self._fail(f"let {stmt.name} cannot infer void")
        elif target == VOID:
            self._fail(f"let {stmt.name} cannot have type void")
        if value is None and target is not None and target.kind == "named":
            self._fail(f"let {stmt.name}: struct variable requires explicit initialization, use `new`")
        if value is not None:
            self._check_assign(target, value, f"let {stmt.name}")
        stmt.resolved_type = target
        self.locals[stmt.name] = target

    def _analyze_assign_op(self, stmt):
        target_type = self._lvalue_type(stmt.target)
        rhs = self._expr(stmt.value)
        if stmt.op == "+" and target_type == STR:
            self._fail("string += is removed; use u8[] + extend instead")
            return
        if not self._is_integer(target_type):
            self._fail(f"compound assignment expected integer target, got {target_type}")
        self._expect_integer(rhs, "compound assignment value")
        result = ExprInfo(self._binary_int_result(target_type, rhs.type))
        self._check_assign(target_type, result, "compound assignment")

    def _analyze_return(self, stmt):
        ret_type = self.func_sigs[self.fn_name][1]
        if ret_type == VOID:
            if stmt.expr is not None:
                actual = self._expr(stmt.expr).type
                self._fail(f"return expected void, got {actual}")
            return
        if stmt.expr is None:
            self._fail(f"return expected {ret_type}, got void")
        self._check_assign(ret_type, self._expr(stmt.expr), "return")

    def _analyze_match(self, stmt):
        scrutinee = self._expr(stmt.expr)
        seen_else = False
        for idx, case in enumerate(stmt.cases):
            if seen_else:
                self._fail("match else must be the final case")
            if case.is_else:
                seen_else = True
                self._analyze_block(case.body)
                continue
            self._analyze_match_case(scrutinee.type, case)

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
            return ExprInfo(I64, expr.value)
        if isinstance(expr, CharNode):
            return ExprInfo(U8, expr.value)
        if isinstance(expr, BoolNode):
            return ExprInfo(BOOL, expr.value)
        if isinstance(expr, StringNode):
            return ExprInfo(STR)
        if isinstance(expr, FStringNode):
            for kind, value in expr.parts:
                if kind == "expr":
                    self._expr(value)
            return ExprInfo(STR)
        if isinstance(expr, VarNode):
            return ExprInfo(self._lookup(expr.name))
        if isinstance(expr, UnaryNode):
            return self._unary_expr(expr)
        if isinstance(expr, BinaryNode):
            return self._binary_expr(expr)
        if isinstance(expr, CallNode):
            return self._call_expr(expr)
        if isinstance(expr, FieldAccessNode):
            return ExprInfo(self._field_type(self._expr(expr.object).type, expr.field))
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
        if isinstance(expr, NewNode):
            return self._new_expr(expr)
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
        if expr.op == "+" and left.type == STR and right.type == STR:
            self._fail("string concatenation is removed; use u8[] + extend + str(bytes)")
        if expr.op in ("==", "!=", "<", ">", "<=", ">="):
            if self._is_integer(left.type) and self._is_integer(right.type):
                return ExprInfo(BOOL)
            if left.type != right.type:
                self._fail(f"comparison expected {left.type}, got {right.type}")
            return ExprInfo(BOOL)
        if expr.op in ("+", "-", "*", "/", "%", "&", "|", "^", "<<", ">>", ">>>"):
            self._expect_integer(left, f"operator {expr.op} left")
            self._expect_integer(right, f"operator {expr.op} right")
            literal = self._fold_binary_literal(expr.op, left.literal_int, right.literal_int)
            return ExprInfo(self._binary_int_result(left.type, right.type), literal)
        self._fail(f"unsupported binary operator {expr.op}")

    def _call_expr(self, expr):
        if expr.namespace == "os":
            return self._os_call(expr)
        if expr.namespace:
            self._fail(f"unsupported namespaced call {expr.namespace}.{expr.name}")

        name = expr.name
        if name in ("print", "println"):
            if len(expr.args) > 1:
                self._fail(f"{name} expects at most one argument")
            if expr.args:
                self._expr(expr.args[0])
            return ExprInfo(VOID)
        if name == "exit":
            self._check_call_args(name, [I64], expr.args)
            return ExprInfo(VOID)
        if name == "str":
            self._check_arity(name, 1, expr.args)
            arg = self._expr(expr.args[0])
            if arg.type == VOID:
                self._fail("str argument cannot be void")
            return ExprInfo(STR)
        if name == "cstr":
            self._check_call_args(name, [STR], expr.args)
            return ExprInfo(I64)
        if name in ("i64", "u64", "i32", "u32", "u8"):
            self._check_arity(name, 1, expr.args)
            self._expect_integer(self._expr(expr.args[0]), f"{name} argument")
            return ExprInfo(self._type_name(name))
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
        if name == "system":
            self._check_call_args(name, [STR], expr.args)
            return ExprInfo(I64)
        if name == "push":
            self._check_arity(name, 2, expr.args)
            arr = self._expr(expr.args[0])
            if arr.type.kind != "array":
                self._fail(f"push expected array, got {arr.type}")
            self._check_assign(arr.type.elem, self._expr(expr.args[1]), "push value")
            return ExprInfo(VOID)
        if name == "extend":
            self._check_arity(name, 2, expr.args)
            dst = self._expr(expr.args[0])
            src = self._expr(expr.args[1])
            if dst.type.kind != "array" or dst.type.elem != U8:
                self._fail("extend only supports u8[]")
            if src.type.kind != "array" or src.type.elem != U8:
                self._fail("extend only supports u8[]")
            return ExprInfo(VOID)
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
        if name in ("map_has", "map_del"):
            self._check_arity(name, 2, expr.args)
            map_arg = self._expr(expr.args[0])
            if map_arg.type.kind != "map":
                self._fail(f"{name} expects map")
            self._check_assign(STR, self._expr(expr.args[1]), f"{name} key")
            return ExprInfo(BOOL)

        if name not in self.func_sigs:
            self._fail(f"unknown function {name}")
        params, ret = self.func_sigs[name]
        self._check_call_args(name, params, expr.args)
        return ExprInfo(ret)

    def _os_call(self, expr):
        key = (expr.dll, expr.name)
        if expr.dll not in {"kernel32", "user32"}:
            self._fail(f"unsupported os dll os.{expr.dll}")
        if key not in self.OS_SIGNATURES:
            self._fail(f"unsupported os call os.{expr.dll}.{expr.name}")
        params, ret = self.OS_SIGNATURES[key]
        self._check_call_args(f"os.{expr.dll}.{expr.name}", params, expr.args)
        return ExprInfo(ret)

    def _struct_init_expr(self, expr):
        if expr.type_name not in self.struct_fields:
            self._fail(f"unknown struct {expr.type_name}")
        self._check_named_fields(self.struct_fields[expr.type_name], expr.fields, expr.type_name)
        return ExprInfo(NAMED(expr.type_name))

    def _new_expr(self, expr):
        typ = self._type_name(expr.struct_name)
        if typ.kind == "map":
            return ExprInfo(typ)
        if typ.kind != "named" or typ.name not in self.struct_fields:
            self._fail(f"new expected struct or map, got {typ}")
        return ExprInfo(typ)

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
        if base.type.kind == "map":
            self._check_assign(STR, self._expr(index_expr), "map key")
            return base.type.elem
        self._expect_integer(self._expr(index_expr), "subscript index")
        if base.type == STR:
            return U8
        if base.type.kind == "array":
            return base.type.elem
        if base.type.kind == "ptr":
            return base.type.elem
        self._fail(f"subscript expected array, str, map, or pointer, got {base.type}")

    def _field_type(self, base_type, field):
        if base_type == STR:
            self._fail(f"unknown field str.{field}")
        if base_type.kind == "array":
            self._fail(f"unknown field {base_type}.{field}")
        if base_type.kind == "named":
            fields = self.struct_fields.get(base_type.name)
            if fields is None:
                self._fail(f"field access expected struct, got {base_type}")
            if field not in fields:
                self._fail(f"unknown field {base_type.name}.{field}")
            return fields[field]
        self._fail(f"field access expected aggregate, got {base_type}")

    def _type_name(self, name):
        if isinstance(name, EpicType):
            return name
        if name is None:
            return VOID
        if name.endswith("[]"):
            return ARRAY(self._type_name(name[:-2]))
        if name.startswith("map[str]"):
            value = self._type_name(name[len("map[str]"):])
            if value not in (I64, BOOL, STR):
                self._fail_global(f"only map[str]i64, map[str]bool, and map[str]str are supported, got {name}")
            return MAP(value)
        if name == "i64":
            return I64
        if name == "u64":
            return U64
        if name == "i32":
            return I32
        if name == "u32":
            return U32
        if name == "u8":
            return U8
        if name == "bool":
            return BOOL
        if name == "void":
            return VOID
        if name == "str":
            return STR
        if name in self.struct_names:
            return NAMED(name)
        self._fail_global(f"unknown type {name}")

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
            self._fail(f"{context} expected non-void target, got void")
        if value.type == VOID:
            self._fail(f"{context} expected {target}, got void")
        if target == value.type:
            if target in (I32, U32) and value.literal_int is not None:
                self._check_int_literal_range(target, value.literal_int, context)
            return
        if self._is_integer(target) and self._is_integer(value.type):
            if target in (I32, U32):
                if value.literal_int is None:
                    self._fail(
                        f"{context} expected {target}, got {value.type}; "
                        f"use {target}(... ) for an explicit checked conversion"
                    )
                self._check_int_literal_range(target, value.literal_int, context)
            elif value.literal_int is not None:
                self._check_int_literal_range(target, value.literal_int, context)
            return
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
        if name not in self.locals:
            self._fail(f"undefined variable {name}")
        return self.locals[name]

    def _block_returns(self, block):
        for stmt in block.stmts:
            if self._stmt_returns(stmt):
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
        if not isinstance(expr, CallNode):
            return False
        if not expr.namespace and expr.name == "exit":
            return True
        return expr.namespace == "os" and expr.dll == "kernel32" and expr.name == "ExitProcess"

    def _is_integer(self, typ):
        return typ.kind in self.INT_RANGES

    def _binary_int_result(self, left, right):
        if left in (I32, U32) or right in (I32, U32):
            return I64
        if left == U64 or right == U64:
            return U64
        if left in (I64, U64):
            return left
        return I64

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
        if isinstance(node, (LiteralNode, CharNode, BoolNode, StringNode, VarNode, NewNode)):
            return
        if isinstance(node, FStringNode):
            for idx, (kind, value) in enumerate(node.parts):
                if kind == "expr":
                    expr(value, f"{path}.parts[{idx}]")
            return
        if isinstance(node, CallNode):
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
        if isinstance(node, ArrayLiteralNode):
            for idx, value in enumerate(node.values):
                expr(value, f"{path}.values[{idx}]")
            return
        fail(path)

    def block(node, path):
        for idx, stmt in enumerate(node.stmts):
            statement(stmt, f"{path}.stmts[{idx}]")

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
                if not case.is_else:
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
