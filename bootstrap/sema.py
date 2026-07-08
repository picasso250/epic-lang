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
        self.globals = {}
        self.locals = {}
        self.fn_name = None
        self.loop_depth = 0

    def analyze(self):
        self._build_types()
        self._build_functions()
        self._build_globals()
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

    def _is_global_literal_init(self, node):
        if isinstance(node, (LiteralNode, CharNode, BoolNode, StringNode)):
            return True
        if isinstance(node, CallNode):
            return node.name in {"u8", "i64", "u64", "i32", "u32", "bool"} and len(node.args) == 1 and self._is_global_literal_init(node.args[0])
        if isinstance(node, ArrayLiteralNode):
            return all(self._is_global_literal_init(value) for value in node.values)
        if isinstance(node, MapInitNode):
            return all(self._is_global_literal_init(key) and self._is_global_literal_init(value) for key, value in node.entries)
        if isinstance(node, StructInitNode):
            return all(self._is_global_literal_init(value) for _, value in node.fields)
        return False

    def _build_globals(self):
        for glob in self.program.globals:
            if glob.value is None:
                self._fail_global(f"global let {glob.name} requires an initializer")
            target = self._type_name(glob.var_type) if glob.var_type else None
            value_info = self._expr(glob.value)
            if target is None:
                target = value_info.type
            else:
                self._check_assign(target, value_info, f"global let {glob.name}")
            if not self._is_global_literal_init(glob.value):
                self._fail_global(f"global let {glob.name} requires a literal initializer")
            glob.resolved_type = target
            self.globals[glob.name] = target

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
            self._expect_bool(self._expr(stmt.cond), "for condition")
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
        if target_type != rhs.type:
            self._fail(f"compound assignment expected matching integer types, got {target_type} and {rhs.type}; use an explicit conversion")

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
            for kind, value in expr.parts:
                if kind == "expr":
                    self._check_str_convertible(self._expr(value), "f-string expression")
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
        if isinstance(expr, MapInitNode):
            return self._map_init_expr(expr)
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
        if expr.namespace == "os":
            return self._os_call(expr)
        if expr.namespace:
            self._fail(f"unsupported namespaced call {expr.namespace}.{expr.name}")

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
            return ExprInfo(I64)
        if name in ("i64", "u64", "i32", "u32", "u8"):
            self._check_arity(name, 1, expr.args)
            arg = self._expr(expr.args[0])
            self._expect_integer(arg, f"{name} argument")
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
            self._fail("push is removed from function-call surface; use xs.push(x)")
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
        if name == "map_has":
            self._fail("map_has is removed from public surface; use m.has(key)")
        if name == "map_del":
            self._fail("map_del is removed from public surface; use m.del(key)")

        if name not in self.func_sigs:
            self._fail(f"unknown function {name}")
        params, ret = self.func_sigs[name]
        self._check_call_args(name, params, expr.args)
        return ExprInfo(ret)

    def _dot_call_expr(self, expr):
        if (
            isinstance(expr.object, FieldAccessNode)
            and isinstance(expr.object.object, VarNode)
            and expr.object.object.name == "os"
        ):
            call = CallNode(name=expr.name, args=expr.args, namespace="os", dll=expr.object.field, line=expr.line)
            return self._os_call(call)
        receiver = self._expr(expr.object)
        if receiver.type.kind == "array":
            if expr.name == "push":
                self._check_arity("push", 1, expr.args)
                self._check_assign(receiver.type.elem, self._expr(expr.args[0]), "push value")
                return ExprInfo(VOID)
            if expr.name == "extend":
                self._check_arity("extend", 1, expr.args)
                src = self._expr(expr.args[0])
                if receiver.type.elem != U8 or src.type.kind != "array" or src.type.elem != U8:
                    self._fail("extend only supports u8[]")
                return ExprInfo(VOID)
            self._fail(f"array type {receiver.type} has no method {expr.name}")
        if receiver.type.kind == "map":
            if expr.name == "has" or expr.name == "del":
                self._check_arity(expr.name, 1, expr.args)
                self._check_assign(STR, self._expr(expr.args[0]), f"{expr.name} key")
                return ExprInfo(BOOL)
            self._fail(f"map type {receiver.type} has no method {expr.name}")
        self._fail("method calls are only supported for os.*, slices, and maps for now")
        return ExprInfo(VOID)

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

    def _map_init_expr(self, expr):
        typ = self._type_name(expr.type_name)
        if typ.kind == "map":
            for key, value in expr.entries:
                self._check_assign(STR, self._expr(key), "map init key")
                self._check_assign(typ.elem, self._expr(value), "map init value")
            return ExprInfo(typ)
        self._fail(f"new expected map, got {typ}")

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
            self._fail("str subscript is removed; use bytes(s)[i]")
        if base.type.kind == "array":
            return base.type.elem
        if base.type.kind == "ptr":
            return base.type.elem
        self._fail(f"subscript expected array, map, or pointer, got {base.type}")

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
            self._fail(f"{context} expected non-void target, got void")
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
        if name in self.locals:
            return self.locals[name]
        if name in self.globals:
            return self.globals[name]
        self._fail(f"undefined variable {name}")

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
        if isinstance(expr, CallNode):
            if not expr.namespace and expr.name == "exit":
                return True
            return expr.namespace == "os" and expr.dll == "kernel32" and expr.name == "ExitProcess"
        if isinstance(expr, DotCallNode):
            return (
                expr.name == "ExitProcess"
                and isinstance(expr.object, FieldAccessNode)
                and expr.object.field == "kernel32"
                and isinstance(expr.object.object, VarNode)
                and expr.object.object.name == "os"
            )
        return False

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
            for idx, (kind, value) in enumerate(node.parts):
                if kind == "expr":
                    expr(value, f"{path}.parts[{idx}]")
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
        if isinstance(node, MapInitNode):
            for idx, (key, value) in enumerate(node.entries):
                expr(key, f"{path}.entries[{idx}].key")
                expr(value, f"{path}.entries[{idx}].value")
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


def _dump_line(depth, text):
    return f"{'  ' * depth}{text}"


def _type_suffix(node):
    typ = getattr(node, "resolved_type", None)
    return f" : {typ}" if typ is not None else ""


def dump_typed_ast_lines(node, depth=0):
    out = []

    def emit(text):
        out.append(_dump_line(depth, text))

    if isinstance(node, ProgramNode):
        emit("Program")
        for struct in node.structs:
            out.extend(dump_typed_ast_lines(struct, depth + 1))
        for glob in node.globals:
            out.extend(dump_typed_ast_lines(glob, depth + 1))
        for func in node.funcs:
            out.extend(dump_typed_ast_lines(func, depth + 1))
    elif isinstance(node, StructDefNode):
        emit(f"StructDef {node.name}")
        for field in node.fields:
            out.extend(dump_typed_ast_lines(field, depth + 1))
    elif isinstance(node, StructField):
        emit(f"StructField {node.name}{_type_suffix(node)}")
    elif isinstance(node, FunDefNode):
        emit(f"FunDef {node.name}{_type_suffix(node)}")
        for param in node.params:
            out.extend(dump_typed_ast_lines(param, depth + 1))
        out.extend(dump_typed_ast_lines(node.body, depth + 1))
    elif isinstance(node, Param):
        emit(f"Param {node.name}{_type_suffix(node)}")
    elif isinstance(node, BlockNode):
        emit("Block")
        for stmt in node.stmts:
            out.extend(dump_typed_ast_lines(stmt, depth + 1))
    elif isinstance(node, ReturnNode):
        emit("Return")
        if node.expr is not None:
            out.extend(dump_typed_ast_lines(node.expr, depth + 1))
    elif isinstance(node, LetNode):
        emit(f"Let {node.name}{_type_suffix(node)}")
        if node.value is not None:
            out.extend(dump_typed_ast_lines(node.value, depth + 1))
    elif isinstance(node, AssignNode):
        emit(f"Assign {node.name}")
        out.extend(dump_typed_ast_lines(node.value, depth + 1))
    elif isinstance(node, AssignOpNode):
        emit(f"AssignOp {node.op}")
        out.extend(dump_typed_ast_lines(node.target, depth + 1))
        out.extend(dump_typed_ast_lines(node.value, depth + 1))
    elif isinstance(node, FieldSetNode):
        emit(f"FieldSet {node.field}")
        out.extend(dump_typed_ast_lines(node.value, depth + 1))
        out.extend(dump_typed_ast_lines(node.object, depth + 1))
    elif isinstance(node, SubscriptAssignNode):
        emit("SubscriptAssign")
        out.extend(dump_typed_ast_lines(node.value, depth + 1))
        out.extend(dump_typed_ast_lines(node.base, depth + 1))
        out.extend(dump_typed_ast_lines(node.index, depth + 1))
    elif isinstance(node, IfNode):
        emit("If")
        out.extend(dump_typed_ast_lines(node.then_block, depth + 1))
        if node.else_block is not None:
            out.extend(dump_typed_ast_lines(node.else_block, depth + 1))
        out.extend(dump_typed_ast_lines(node.cond, depth + 1))
    elif isinstance(node, WhileNode):
        emit("While")
        out.extend(dump_typed_ast_lines(node.body, depth + 1))
        out.extend(dump_typed_ast_lines(node.cond, depth + 1))
    elif isinstance(node, BreakNode):
        emit("Break")
    elif isinstance(node, ContinueNode):
        emit("Continue")
    elif isinstance(node, ForRangeNode):
        emit(f"For {node.name}{_type_suffix(node)}")
        out.extend(dump_typed_ast_lines(node.body, depth + 1))
        out.extend(dump_typed_ast_lines(node.start, depth + 1))
        out.extend(dump_typed_ast_lines(node.end, depth + 1))
    elif isinstance(node, PanicNode):
        emit("Panic")
        out.extend(dump_typed_ast_lines(node.message, depth + 1))
    elif isinstance(node, AssertNode):
        emit("Assert")
        out.extend(dump_typed_ast_lines(node.cond, depth + 1))
        if node.message is not None:
            out.extend(dump_typed_ast_lines(node.message, depth + 1))
    elif isinstance(node, MatchNode):
        emit("Match")
        out.extend(dump_typed_ast_lines(node.expr, depth + 1))
        for case in node.cases:
            out.extend(dump_typed_ast_lines(case, depth + 1))
    elif isinstance(node, MatchCase):
        emit("MatchCase")
        if node.pattern is not None:
            out.extend(dump_typed_ast_lines(node.pattern, depth + 1))
        out.extend(dump_typed_ast_lines(node.body, depth + 1))
    elif isinstance(node, ExprStmtNode):
        emit("ExprStmt")
        out.extend(dump_typed_ast_lines(node.expr, depth + 1))
    elif isinstance(node, LiteralNode):
        emit(f"Literal {node.value}{_type_suffix(node)}")
    elif isinstance(node, CharNode):
        emit(f"Char {node.value}{_type_suffix(node)}")
    elif isinstance(node, BoolNode):
        emit(f"Bool {node.value}{_type_suffix(node)}")
    elif isinstance(node, StringNode):
        emit(f"String {node.value}{_type_suffix(node)}")
    elif isinstance(node, FStringNode):
        emit(f"FString{_type_suffix(node)}")
        for kind, value in node.parts:
            if kind == "text":
                emit(f"  FStringText {value}")
            else:
                out.extend(dump_typed_ast_lines(value, depth + 1))
    elif isinstance(node, VarNode):
        emit(f"Var {node.name}{_type_suffix(node)}")
    elif isinstance(node, CallNode):
        suffix = f" : {node.namespace}" if node.namespace else ""
        emit(f"Call {node.name}{suffix}{_type_suffix(node)}")
        for arg in node.args:
            out.extend(dump_typed_ast_lines(arg, depth + 1))
    elif isinstance(node, DotCallNode):
        emit(f"DotCall {node.name}{_type_suffix(node)}")
        out.extend(dump_typed_ast_lines(node.object, depth + 1))
        for arg in node.args:
            out.extend(dump_typed_ast_lines(arg, depth + 1))
    elif isinstance(node, BinaryNode):
        emit(f"Binary {node.op}{_type_suffix(node)}")
        out.extend(dump_typed_ast_lines(node.left, depth + 1))
        out.extend(dump_typed_ast_lines(node.right, depth + 1))
    elif isinstance(node, UnaryNode):
        emit(f"Unary {node.op}{_type_suffix(node)}")
        out.extend(dump_typed_ast_lines(node.expr, depth + 1))
    elif isinstance(node, FieldAccessNode):
        emit(f"FieldAccess {node.field}{_type_suffix(node)}")
        out.extend(dump_typed_ast_lines(node.object, depth + 1))
    elif isinstance(node, SubscriptNode):
        emit(f"Subscript{_type_suffix(node)}")
        out.extend(dump_typed_ast_lines(node.base, depth + 1))
        out.extend(dump_typed_ast_lines(node.index, depth + 1))
    elif isinstance(node, SliceNode):
        emit(f"Slice{_type_suffix(node)}")
        out.extend(dump_typed_ast_lines(node.base, depth + 1))
        if node.start is not None:
            out.extend(dump_typed_ast_lines(node.start, depth + 1))
        if node.end is not None:
            out.extend(dump_typed_ast_lines(node.end, depth + 1))
    elif isinstance(node, NewArrayNode):
        emit(f"NewArray : {node.elem_type}{_type_suffix(node)}")
        if node.count is not None:
            out.extend(dump_typed_ast_lines(node.count, depth + 1))
    elif isinstance(node, StructInitNode):
        emit(f"StructInit {node.type_name}{_type_suffix(node)}")
        for field, value in node.fields:
            out.append(_dump_line(depth + 1, f"InitField {field}"))
            out.extend(dump_typed_ast_lines(value, depth + 2))
    elif isinstance(node, ArrayLiteralNode):
        emit(f"ArrayLiteral : {node.elem_type}{_type_suffix(node)}")
        for value in node.values:
            out.extend(dump_typed_ast_lines(value, depth + 1))
    elif isinstance(node, MapInitNode):
        emit(f"MapInit : {node.type_name}{_type_suffix(node)}")
        for key, value in node.entries:
            out.append(_dump_line(depth + 1, "Key"))
            out.extend(dump_typed_ast_lines(key, depth + 2))
            out.append(_dump_line(depth + 1, "Value"))
            out.extend(dump_typed_ast_lines(value, depth + 2))
    else:
        raise TypeError(f"unsupported AST node: {type(node).__name__}")

    return out


def dump_typed_ast_text(node):
    return "\n".join(dump_typed_ast_lines(node)) + "\n"
