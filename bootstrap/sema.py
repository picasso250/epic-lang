"""Semantic analysis for the Python reference compiler."""

from __future__ import annotations

from dataclasses import dataclass

from ast_nodes import *
from epic_builtins import BUILTIN_FUNCTIONS, PSEUDO_BUILTINS


class SemanticError(RuntimeError):
    pass


@dataclass(frozen=True)
class SemType:
    kind: str
    elem: "SemType | None" = None
    name: str = ""

    def __str__(self):
        if self.kind == "array":
            return f"{self.elem}[]"
        if self.kind == "map":
            return f"map[str]{self.elem}"
        if self.kind == "ptr":
            return f"&{self.elem}"
        if self.kind == "named":
            return self.name
        return self.kind


I64 = SemType("i64")
U64 = SemType("u64")
I32 = SemType("i32")
U32 = SemType("u32")
I8 = SemType("i8")
U8 = SemType("u8")
BOOL = SemType("bool")
VOID = SemType("void")
STR = SemType("str")


def ARRAY(elem):
    return SemType("array", elem=elem)


def MAP(value):
    return SemType("map", elem=value)


def PTR(elem):
    return SemType("ptr", elem=elem)


def NAMED(name):
    return SemType("named", name=name)


@dataclass
class ExprInfo:
    type: SemType
    literal_int: int | None = None


class SemanticAnalyzer:
    INT_RANGES = {
        "i8": (-128, 127),
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
        self.adt_names = {t.name for t in getattr(program, "types", [])}
        self.struct_fields = {}
        self.adt_variants = {}
        self.func_sigs = {}
        self.locals = {}
        self.fn_name = None
        self.loop_depth = 0

    def analyze(self):
        self._build_types()
        self._build_functions()
        for fn in self.program.funcs:
            self._analyze_function(fn)
        return self.program

    def _build_types(self):
        for struct in self.program.structs:
            fields = {}
            for field in struct.fields:
                if field.name in fields:
                    self._fail_global(f"duplicate field {struct.name}.{field.name}")
                fields[field.name] = self._type_name(field.type)
            self.struct_fields[struct.name] = fields

        for typ in getattr(self.program, "types", []):
            variants = {}
            for variant in typ.variants:
                if variant.name in variants:
                    self._fail_global(f"duplicate variant {typ.name}.{variant.name}")
                fields = {}
                for field in variant.fields:
                    if field.name in fields:
                        self._fail_global(f"duplicate field {typ.name}.{variant.name}.{field.name}")
                    fields[field.name] = self._type_name(field.type)
                variants[variant.name] = fields
            self.adt_variants[typ.name] = variants

    def _build_functions(self):
        for fn in self.program.funcs:
            params = []
            for param in fn.params:
                typ = self._type_name(param.type)
                if typ == VOID:
                    self._fail_global(f"function {fn.name} parameter {param.name} cannot have type void")
                params.append(typ)
            if fn.name in BUILTIN_FUNCTIONS or fn.name in PSEUDO_BUILTINS:
                self._fail_global(f"reserved builtin function name: {fn.name}")
            self.func_sigs[fn.name] = (params, self._type_name(fn.ret_type))

    def _analyze_function(self, fn):
        self.fn_name = fn.name
        self.locals = {"argv": ARRAY(STR)}
        self.loop_depth = 0
        for param in fn.params:
            self.locals[param.name] = self._type_name(param.type)

        self._analyze_block(fn.body)
        ret_type = self._type_name(fn.ret_type)
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
        if value is not None:
            self._check_assign(target, value, f"let {stmt.name}")
        self.locals[stmt.name] = target

    def _analyze_assign_op(self, stmt):
        target_type = self._lvalue_type(stmt.target)
        rhs = self._expr(stmt.value)
        if stmt.op == "+" and target_type == STR:
            self._check_assign(STR, rhs, "string +=")
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
        if self._is_adt_pattern(case.pattern):
            type_name = case.pattern.object.name
            variant = case.pattern.field
            if scrutinee_type != NAMED(type_name):
                self._fail(f"match pattern expected {scrutinee_type}, got {type_name}.{variant}")
            variants = self.adt_variants.get(type_name)
            if variants is None or variant not in variants:
                self._fail(f"unknown ADT variant {type_name}.{variant}")
            fields = variants[variant]
            seen = set()
            for field, bind_name in case.bindings:
                if field in seen:
                    self._fail(f"duplicate match binding {type_name}.{variant}.{field}")
                seen.add(field)
                if field not in fields:
                    self._fail(f"unknown match binding {type_name}.{variant}.{field}")
                self.locals[bind_name] = fields[field]
        else:
            if case.bindings:
                self._fail("match bindings require an ADT variant pattern")
            self._check_assign(scrutinee_type, self._expr(case.pattern), "match pattern")
        self._analyze_block(case.body)

    def _expr(self, expr):
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
            if base.type != STR and base.type.kind != "array":
                self._fail(f"slice expected str or array, got {base.type}")
            if expr.start is not None:
                self._expect_integer(self._expr(expr.start), "slice start")
            if expr.end is not None:
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
            return ExprInfo(STR)
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
        if name == "str_new":
            self._check_arity(name, 2, expr.args)
            data = self._expr(expr.args[0])
            if data.type.kind != "ptr" and not self._is_integer(data.type):
                self._fail(f"str_new data expected pointer or integer, got {data.type}")
            self._expect_integer(self._expr(expr.args[1]), "str_new length")
            return ExprInfo(STR)
        if name in ("str_slice", "str_replace_char"):
            self._check_call_args(name, [STR, I64, I64], expr.args)
            return ExprInfo(STR)
        if name in ("str_starts_with", "str_find"):
            self._check_call_args(name, [STR, STR], expr.args)
            return ExprInfo(I64)
        if name == "str_trim":
            self._check_call_args(name, [STR], expr.args)
            return ExprInfo(STR)
        if name == "itoa":
            self._check_arity(name, 1, expr.args)
            self._expect_integer(self._expr(expr.args[0]), "itoa argument")
            return ExprInfo(STR)
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
            if dst.type.kind != "array" or src.type.kind != "array" or dst.type.elem != src.type.elem:
                self._fail(f"extend expected matching arrays, got {dst.type} and {src.type}")
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
        if name == "map_has":
            self._check_call_args(name, [MAP(I64), STR], expr.args)
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
        if expr.variant:
            if expr.type_name not in self.adt_variants:
                self._fail(f"unknown ADT {expr.type_name}")
            variants = self.adt_variants[expr.type_name]
            if expr.variant not in variants:
                self._fail(f"unknown ADT variant {expr.type_name}.{expr.variant}")
            self._check_named_fields(variants[expr.variant], expr.fields, f"{expr.type_name}.{expr.variant}")
            return ExprInfo(NAMED(expr.type_name))
        if expr.type_name not in self.struct_fields:
            if expr.type_name in self.adt_variants:
                self._fail(f"ADT construction requires a variant: {expr.type_name}")
            self._fail(f"unknown struct {expr.type_name}")
        self._check_named_fields(self.struct_fields[expr.type_name], expr.fields, expr.type_name)
        return ExprInfo(NAMED(expr.type_name))

    def _new_expr(self, expr):
        typ = self._type_name(expr.struct_name)
        if typ.kind == "map":
            return ExprInfo(typ)
        if typ.kind != "named" or typ.name not in self.struct_fields:
            if typ.kind == "named" and typ.name in self.adt_variants:
                self._fail(f"ADT construction requires a variant: {typ.name}")
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
            return self._lookup(target.name)
        if isinstance(target, FieldAccessNode):
            return self._field_type(self._expr(target.object).type, target.field)
        if isinstance(target, SubscriptNode):
            return self._subscript_type(target.base, target.index)
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
            if field == "data":
                return PTR(U8)
            if field == "len":
                return I64
            self._fail(f"unknown field str.{field}")
        if base_type.kind == "array":
            if field == "data":
                return PTR(base_type.elem)
            if field in ("len", "cap"):
                return I64
            self._fail(f"unknown field {base_type}.{field}")
        if base_type.kind == "named":
            if base_type.name in self.adt_variants:
                if field == "tag":
                    return I64
                if field == "data":
                    return PTR(I64)
                self._fail(f"unknown field {base_type.name}.{field}")
            fields = self.struct_fields.get(base_type.name)
            if fields is None:
                self._fail(f"field access expected struct, got {base_type}")
            if field not in fields:
                self._fail(f"unknown field {base_type.name}.{field}")
            return fields[field]
        self._fail(f"field access expected aggregate, got {base_type}")

    def _type_name(self, name):
        if isinstance(name, SemType):
            return name
        if name is None:
            return VOID
        if name.endswith("[]"):
            return ARRAY(self._type_name(name[:-2]))
        if name.startswith("map[str]"):
            value = self._type_name(name[len("map[str]"):])
            if value != I64:
                self._fail_global(f"only map[str]i64 is supported, got {name}")
            return MAP(value)
        if name == "i64":
            return I64
        if name == "u64":
            return U64
        if name == "i32":
            return I32
        if name == "u32":
            return U32
        if name == "i8":
            return I8
        if name == "u8":
            return U8
        if name == "bool":
            return BOOL
        if name == "void":
            return VOID
        if name == "str":
            return STR
        if name in self.struct_names or name in self.adt_names:
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

    def _is_adt_pattern(self, pattern):
        return (
            isinstance(pattern, FieldAccessNode)
            and isinstance(pattern.object, VarNode)
            and pattern.object.name in self.adt_variants
        )

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


def analyze_program(program):
    return SemanticAnalyzer(program).analyze()
