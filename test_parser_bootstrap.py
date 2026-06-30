#!/usr/bin/env python3
"""
Compare the self-hosted parser against the Python parser on examples/*.ep.
"""

import difflib
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "bootstrap"))
from ast_nodes import *
from lexer import lex
from parser import Parser


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EPICC = os.path.join(SCRIPT_DIR, "bootstrap", "epic.py")
EXAMPLES_DIR = os.path.join(SCRIPT_DIR, "examples")
PARSER_EP = os.path.join(SCRIPT_DIR, "src", "parser.ep")
LEXER_EP = os.path.join(SCRIPT_DIR, "src", "lexer.ep")
PARSER_EXE = os.path.join(SCRIPT_DIR, "build", "src", "parser.exe")


def line(depth, text):
    return f"{'  ' * depth}{text}"


def py_dump(node, depth=0):
    out = []

    def emit(text):
        out.append(line(depth, text))

    if isinstance(node, ProgramNode):
        emit("Program")
        for struct in node.structs:
            out.extend(py_dump(struct, depth + 1))
        for typ in getattr(node, "types", []):
            out.extend(py_dump(typ, depth + 1))
        for func in node.funcs:
            out.extend(py_dump(func, depth + 1))
    elif isinstance(node, StructDefNode):
        emit(f"StructDef {node.name}")
        for field in node.fields:
            out.extend(py_dump(field, depth + 1))
    elif isinstance(node, StructField):
        emit(f"StructField {node.name} : {node.type}")
    elif isinstance(node, FunDefNode):
        emit(f"FunDef {node.name} : {node.ret_type}")
        for param in node.params:
            out.extend(py_dump(param, depth + 1))
        out.extend(py_dump(node.body, depth + 1))
    elif isinstance(node, Param):
        emit(f"Param {node.name} : {node.type}")
    elif isinstance(node, BlockNode):
        emit("Block")
        for stmt in node.stmts:
            out.extend(py_dump(stmt, depth + 1))
    elif isinstance(node, ReturnNode):
        emit("Return")
        if node.expr is not None:
            out.extend(py_dump(node.expr, depth + 1))
    elif isinstance(node, LetNode):
        suffix = f" : {node.var_type}" if node.var_type else ""
        emit(f"Let {node.name}{suffix}")
        if node.value is not None:
            out.extend(py_dump(node.value, depth + 1))
    elif isinstance(node, AssignNode):
        emit(f"Assign {node.name}")
        out.extend(py_dump(node.value, depth + 1))
    elif isinstance(node, AssignOpNode):
        emit(f"AssignOp {node.op}")
        out.extend(py_dump(node.target, depth + 1))
        out.extend(py_dump(node.value, depth + 1))
    elif isinstance(node, FieldSetNode):
        emit(f"FieldSet {node.field}")
        out.extend(py_dump(node.value, depth + 1))
        out.extend(py_dump(node.object, depth + 1))
    elif isinstance(node, SubscriptAssignNode):
        emit("SubscriptAssign")
        out.extend(py_dump(node.value, depth + 1))
        out.extend(py_dump(node.base, depth + 1))
        out.extend(py_dump(node.index, depth + 1))
    elif isinstance(node, IfNode):
        emit("If")
        out.extend(py_dump(node.then_block, depth + 1))
        if node.else_block is not None:
            out.extend(py_dump(node.else_block, depth + 1))
        out.extend(py_dump(node.cond, depth + 1))
    elif isinstance(node, WhileNode):
        emit("While")
        out.extend(py_dump(node.body, depth + 1))
        out.extend(py_dump(node.cond, depth + 1))
    elif isinstance(node, BreakNode):
        emit("Break")
    elif isinstance(node, ContinueNode):
        emit("Continue")
    elif isinstance(node, ForRangeNode):
        emit(f"For {node.name}")
        out.extend(py_dump(node.body, depth + 1))
        out.extend(py_dump(node.start, depth + 1))
        out.extend(py_dump(node.end, depth + 1))
    elif isinstance(node, PanicNode):
        emit("Panic")
        out.extend(py_dump(node.message, depth + 1))
    elif isinstance(node, AssertNode):
        emit("Assert")
        out.extend(py_dump(node.cond, depth + 1))
        if node.message is not None:
            out.extend(py_dump(node.message, depth + 1))
    elif isinstance(node, MatchNode):
        emit("Match")
        out.extend(py_dump(node.expr, depth + 1))
        for case in node.cases:
            out.extend(py_dump(case, depth + 1))
    elif isinstance(node, MatchCase):
        emit("MatchCase")
        if node.pattern is not None:
            out.extend(py_dump(node.pattern, depth + 1))
        for field, bind in node.bindings:
            emit(f"  MatchBinding {field} : {bind}")
        out.extend(py_dump(node.body, depth + 1))
    elif isinstance(node, ExprStmtNode):
        emit("ExprStmt")
        out.extend(py_dump(node.expr, depth + 1))
    elif isinstance(node, LiteralNode):
        emit(f"Literal {node.value}")
    elif isinstance(node, CharNode):
        emit(f"Char {node.value}")
    elif isinstance(node, BoolNode):
        emit(f"Bool {node.value}")
    elif isinstance(node, StringNode):
        emit(f"String {node.value}")
    elif isinstance(node, FStringNode):
        emit("FString")
        for kind, value in node.parts:
            if kind == "text":
                emit(f"  FStringText {value}")
            else:
                out.extend(py_dump(value, depth + 1))
    elif isinstance(node, VarNode):
        emit(f"Var {node.name}")
    elif isinstance(node, CallNode):
        suffix = f" : {node.namespace}" if node.namespace else ""
        emit(f"Call {node.name}{suffix}")
        for arg in node.args:
            out.extend(py_dump(arg, depth + 1))
    elif isinstance(node, BinaryNode):
        emit(f"Binary {node.op}")
        out.extend(py_dump(node.left, depth + 1))
        out.extend(py_dump(node.right, depth + 1))
    elif isinstance(node, UnaryNode):
        emit(f"Unary {node.op}")
        out.extend(py_dump(node.expr, depth + 1))
    elif isinstance(node, FieldAccessNode):
        emit(f"FieldAccess {node.field}")
        out.extend(py_dump(node.object, depth + 1))
    elif isinstance(node, SubscriptNode):
        emit("Subscript")
        out.extend(py_dump(node.base, depth + 1))
        out.extend(py_dump(node.index, depth + 1))
    elif isinstance(node, SliceNode):
        emit("Slice")
        out.extend(py_dump(node.base, depth + 1))
        if node.start is not None:
            out.extend(py_dump(node.start, depth + 1))
        if node.end is not None:
            out.extend(py_dump(node.end, depth + 1))
    elif isinstance(node, NewNode):
        emit(f"New {node.struct_name}")
    elif isinstance(node, NewArrayNode):
        emit(f"NewArray : {node.elem_type}")
        if node.count is not None:
            out.extend(py_dump(node.count, depth + 1))
    elif isinstance(node, StructInitNode):
        kind = "VariantInit" if node.variant else "StructInit"
        name = node.variant if node.variant else node.type_name
        suffix = f" : {node.type_name}" if node.variant else ""
        emit(f"{kind} {name}{suffix}")
        for field, value in node.fields:
            out.append(line(depth + 1, f"InitField {field}"))
            out.extend(py_dump(value, depth + 2))
    elif isinstance(node, ArrayLiteralNode):
        emit(f"ArrayLiteral : {node.elem_type}")
        for value in node.values:
            out.extend(py_dump(value, depth + 1))
    elif isinstance(node, TypeDefNode):
        emit(f"TypeDef {node.name}")
        for variant in node.variants:
            out.extend(py_dump(variant, depth + 1))
    elif isinstance(node, TypeVariant):
        emit(f"VariantDef {node.name}")
        for field in node.fields:
            out.extend(py_dump(field, depth + 1))
    else:
        raise TypeError(f"unsupported AST node: {type(node).__name__}")

    return out


def python_parser_dump(path):
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    ast = Parser(lex(source)).parse_program()
    return "\n".join(py_dump(ast)) + "\n"


def ensure_bootstrap_parser():
    result = subprocess.run(
        [sys.executable, EPICC, "--main", PARSER_EP, PARSER_EP, LEXER_EP],
        cwd=SCRIPT_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "failed to compile parser.ep:\n"
            + result.stdout[-2000:]
            + result.stderr[-2000:]
        )


def bootstrap_parser_dump(path):
    result = subprocess.run(
        [PARSER_EXE, path],
        cwd=SCRIPT_DIR,
        capture_output=True,
    )
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(
            f"self-hosted parser failed for {path}:\n"
            + stdout[-2000:]
            + stderr[-2000:]
        )
    return stdout


def main():
    ensure_bootstrap_parser()
    examples = sorted(
        os.path.join(EXAMPLES_DIR, name)
        for name in os.listdir(EXAMPLES_DIR)
        if name.endswith(".ep")
    )

    failed = 0
    print(f"Comparing parser dumps for {len(examples)} examples...\n")
    for path in examples:
        rel = os.path.relpath(path, SCRIPT_DIR)
        expected = python_parser_dump(path)
        actual = bootstrap_parser_dump(path)
        if actual == expected:
            print(f"  PASS   {rel}")
            continue

        failed += 1
        print(f"  FAIL   {rel}")
        diff = difflib.unified_diff(
            expected.splitlines(),
            actual.splitlines(),
            fromfile=f"python/{rel}",
            tofile=f"bootstrap/{rel}",
            lineterm="",
        )
        for i, diff_line in enumerate(diff):
            if i >= 80:
                print("  ... diff truncated ...")
                break
            print(diff_line)

    print(f"\n{len(examples) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
