#!/usr/bin/env python3
"""
tests/sema/run.py — Semantic analysis tests.

Default mode checks:
  - Python sema typed AST golden for tests/sema/pass/all.ep
  - existing Python reference compiler negative tests under tests/sema/fail/*.ep

Regenerate typed AST golden:
  python tests/sema/run.py --regen
"""

import argparse
import difflib
import os
import re
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))
EPICC = os.path.join(ROOT_DIR, "bootstrap", "epic.py")
UTIL_EP = os.path.join(ROOT_DIR, "src", "util.ep")
LEXER_EP = os.path.join(ROOT_DIR, "src", "lexer.ep")
PARSER_EP = os.path.join(ROOT_DIR, "src", "parser.ep")
SEMA_EP = os.path.join(ROOT_DIR, "src", "sema.ep")
SEMA_BUILD_DIR = os.path.join(ROOT_DIR, "build", "sema-bootstrap")
SEMA_EXE = os.path.join(SEMA_BUILD_DIR, "src", "sema.exe")

FAIL_DIR = os.path.join(SCRIPT_DIR, "fail")
PASS_DIR = os.path.join(SCRIPT_DIR, "pass")
ALL_EP = os.path.join(PASS_DIR, "all.ep")
TYPED_AST_DUMP = os.path.join(PASS_DIR, "typed_ast_dump.txt")

sys.path.insert(0, os.path.join(ROOT_DIR, "bootstrap"))
from ast_nodes import *
from lexer import lex
from parser import Parser
from sema import analyze_program


def line(depth, text):
    return f"{'  ' * depth}{text}"


def type_suffix(node):
    typ = getattr(node, "resolved_type", None)
    return f" : {typ}" if typ is not None else ""


def sema_dump(node, depth=0):
    out = []

    def emit(text):
        out.append(line(depth, text))

    if isinstance(node, ProgramNode):
        emit("Program")
        for struct in node.structs:
            out.extend(sema_dump(struct, depth + 1))
        for func in node.funcs:
            out.extend(sema_dump(func, depth + 1))
    elif isinstance(node, StructDefNode):
        emit(f"StructDef {node.name}")
        for field in node.fields:
            out.extend(sema_dump(field, depth + 1))
    elif isinstance(node, StructField):
        emit(f"StructField {node.name}{type_suffix(node)}")
    elif isinstance(node, FunDefNode):
        emit(f"FunDef {node.name}{type_suffix(node)}")
        for param in node.params:
            out.extend(sema_dump(param, depth + 1))
        out.extend(sema_dump(node.body, depth + 1))
    elif isinstance(node, Param):
        emit(f"Param {node.name}{type_suffix(node)}")
    elif isinstance(node, BlockNode):
        emit("Block")
        for stmt in node.stmts:
            out.extend(sema_dump(stmt, depth + 1))
    elif isinstance(node, ReturnNode):
        emit("Return")
        if node.expr is not None:
            out.extend(sema_dump(node.expr, depth + 1))
    elif isinstance(node, LetNode):
        emit(f"Let {node.name}{type_suffix(node)}")
        if node.value is not None:
            out.extend(sema_dump(node.value, depth + 1))
    elif isinstance(node, AssignNode):
        emit(f"Assign {node.name}")
        out.extend(sema_dump(node.value, depth + 1))
    elif isinstance(node, AssignOpNode):
        emit(f"AssignOp {node.op}")
        out.extend(sema_dump(node.target, depth + 1))
        out.extend(sema_dump(node.value, depth + 1))
    elif isinstance(node, FieldSetNode):
        emit(f"FieldSet {node.field}")
        out.extend(sema_dump(node.value, depth + 1))
        out.extend(sema_dump(node.object, depth + 1))
    elif isinstance(node, SubscriptAssignNode):
        emit("SubscriptAssign")
        out.extend(sema_dump(node.value, depth + 1))
        out.extend(sema_dump(node.base, depth + 1))
        out.extend(sema_dump(node.index, depth + 1))
    elif isinstance(node, IfNode):
        emit("If")
        out.extend(sema_dump(node.then_block, depth + 1))
        if node.else_block is not None:
            out.extend(sema_dump(node.else_block, depth + 1))
        out.extend(sema_dump(node.cond, depth + 1))
    elif isinstance(node, WhileNode):
        emit("While")
        out.extend(sema_dump(node.body, depth + 1))
        out.extend(sema_dump(node.cond, depth + 1))
    elif isinstance(node, BreakNode):
        emit("Break")
    elif isinstance(node, ContinueNode):
        emit("Continue")
    elif isinstance(node, ForRangeNode):
        emit(f"For {node.name}{type_suffix(node)}")
        out.extend(sema_dump(node.body, depth + 1))
        out.extend(sema_dump(node.start, depth + 1))
        out.extend(sema_dump(node.end, depth + 1))
    elif isinstance(node, PanicNode):
        emit("Panic")
        out.extend(sema_dump(node.message, depth + 1))
    elif isinstance(node, AssertNode):
        emit("Assert")
        out.extend(sema_dump(node.cond, depth + 1))
        if node.message is not None:
            out.extend(sema_dump(node.message, depth + 1))
    elif isinstance(node, MatchNode):
        emit("Match")
        out.extend(sema_dump(node.expr, depth + 1))
        for case in node.cases:
            out.extend(sema_dump(case, depth + 1))
    elif isinstance(node, MatchCase):
        emit("MatchCase")
        if node.pattern is not None:
            out.extend(sema_dump(node.pattern, depth + 1))
        out.extend(sema_dump(node.body, depth + 1))
    elif isinstance(node, ExprStmtNode):
        emit("ExprStmt")
        out.extend(sema_dump(node.expr, depth + 1))
    elif isinstance(node, LiteralNode):
        emit(f"Literal {node.value}{type_suffix(node)}")
    elif isinstance(node, CharNode):
        emit(f"Char {node.value}{type_suffix(node)}")
    elif isinstance(node, BoolNode):
        emit(f"Bool {node.value}{type_suffix(node)}")
    elif isinstance(node, StringNode):
        emit(f"String {node.value}{type_suffix(node)}")
    elif isinstance(node, FStringNode):
        emit(f"FString{type_suffix(node)}")
        for kind, value in node.parts:
            if kind == "text":
                emit(f"  FStringText {value}")
            else:
                out.extend(sema_dump(value, depth + 1))
    elif isinstance(node, VarNode):
        emit(f"Var {node.name}{type_suffix(node)}")
    elif isinstance(node, CallNode):
        suffix = f" : {node.namespace}" if node.namespace else ""
        emit(f"Call {node.name}{suffix}{type_suffix(node)}")
        for arg in node.args:
            out.extend(sema_dump(arg, depth + 1))
    elif isinstance(node, BinaryNode):
        emit(f"Binary {node.op}{type_suffix(node)}")
        out.extend(sema_dump(node.left, depth + 1))
        out.extend(sema_dump(node.right, depth + 1))
    elif isinstance(node, UnaryNode):
        emit(f"Unary {node.op}{type_suffix(node)}")
        out.extend(sema_dump(node.expr, depth + 1))
    elif isinstance(node, FieldAccessNode):
        emit(f"FieldAccess {node.field}{type_suffix(node)}")
        out.extend(sema_dump(node.object, depth + 1))
    elif isinstance(node, SubscriptNode):
        emit(f"Subscript{type_suffix(node)}")
        out.extend(sema_dump(node.base, depth + 1))
        out.extend(sema_dump(node.index, depth + 1))
    elif isinstance(node, SliceNode):
        emit(f"Slice{type_suffix(node)}")
        out.extend(sema_dump(node.base, depth + 1))
        if node.start is not None:
            out.extend(sema_dump(node.start, depth + 1))
        if node.end is not None:
            out.extend(sema_dump(node.end, depth + 1))
    elif isinstance(node, NewNode):
        emit(f"New {node.struct_name}{type_suffix(node)}")
    elif isinstance(node, NewArrayNode):
        emit(f"NewArray : {node.elem_type}{type_suffix(node)}")
        if node.count is not None:
            out.extend(sema_dump(node.count, depth + 1))
    elif isinstance(node, StructInitNode):
        emit(f"StructInit {node.type_name}{type_suffix(node)}")
        for field, value in node.fields:
            out.append(line(depth + 1, f"InitField {field}"))
            out.extend(sema_dump(value, depth + 2))
    elif isinstance(node, ArrayLiteralNode):
        emit(f"ArrayLiteral : {node.elem_type}{type_suffix(node)}")
        for value in node.values:
            out.extend(sema_dump(value, depth + 1))
    else:
        raise TypeError(f"unsupported AST node: {type(node).__name__}")

    return out


def python_sema_dump_source(source):
    ast = Parser(lex(source)).parse_program()
    typed = analyze_program(ast)
    return "\n".join(sema_dump(typed)) + "\n"


def python_sema_dump(path):
    with open(path, "r", encoding="utf-8") as f:
        return python_sema_dump_source(f.read())


def print_diff(expected, actual, expected_label, actual_label):
    diff = difflib.unified_diff(
        expected.splitlines(),
        actual.splitlines(),
        fromfile=expected_label,
        tofile=actual_label,
        lineterm="",
    )
    for i, diff_line in enumerate(diff):
        if i >= 120:
            print("  ... diff truncated ...")
            break
        print(diff_line)


def regen_golden():
    os.makedirs(PASS_DIR, exist_ok=True)
    with open(TYPED_AST_DUMP, "w", encoding="utf-8", newline="\n") as f:
        f.write(python_sema_dump(ALL_EP))
    print(f"Regenerated {os.path.relpath(TYPED_AST_DUMP, ROOT_DIR)}")


def run_pass_tests():
    if not os.path.isfile(ALL_EP):
        print(f"  FAIL  missing sema fixture: {ALL_EP}")
        return 0, 1, 0
    if not os.path.isfile(TYPED_AST_DUMP):
        print(f"  FAIL  missing sema golden: {TYPED_AST_DUMP}")
        return 0, 1, 0

    with open(TYPED_AST_DUMP, "r", encoding="utf-8") as f:
        expected = f.read()
    actual = python_sema_dump(ALL_EP)
    if actual == expected:
        print("  PASS  pass/all.ep typed AST golden")
        return 1, 0, 0

    print("  FAIL  pass/all.ep typed AST golden")
    print_diff(expected, actual, "golden/typed_ast_dump.txt", "python/sema/pass/all.ep")
    return 0, 1, 0


def ensure_self_hosted_sema():
    os.makedirs(SEMA_BUILD_DIR, exist_ok=True)
    result = subprocess.run(
        [
            sys.executable,
            EPICC,
            "--main",
            SEMA_EP,
            UTIL_EP,
            LEXER_EP,
            PARSER_EP,
            SEMA_EP,
            "--out-dir",
            SEMA_BUILD_DIR,
        ],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError("failed to compile src/sema.ep:\n" + result.stdout[-2000:] + result.stderr[-2000:])
    if not os.path.isfile(SEMA_EXE):
        raise RuntimeError(f"expected sema.exe at {SEMA_EXE}")


def run_self_hosted_pass_tests():
    ensure_self_hosted_sema()
    expected = python_sema_dump(ALL_EP)
    result = subprocess.run(
        [SEMA_EXE, ALL_EP],
        cwd=ROOT_DIR,
        capture_output=True,
    )
    actual = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")
    if result.returncode != 0:
        print("  FAIL  self-hosted sema pass/all.ep failed")
        print((actual + stderr)[-2000:])
        return 0, 1, 0
    if actual == expected:
        print("  PASS  self-hosted sema pass/all.ep")
        return 1, 0, 0
    print("  FAIL  self-hosted sema pass/all.ep")
    print_diff(expected, actual, "python/sema/pass/all.ep", "self-hosted/sema/pass/all.ep")
    return 0, 1, 0


def run_fail_tests():
    if not os.path.isdir(FAIL_DIR):
        return 0, 0, 0

    passed = 0
    failed = 0
    skipped = 0

    for ep_name in sorted(os.listdir(FAIL_DIR)):
        if not ep_name.endswith(".ep"):
            continue

        ep_path = os.path.join(FAIL_DIR, ep_name)

        with open(ep_path, "r", encoding="utf-8") as f:
            source = f.read()

        m = re.search(r'#\s*COMPILE_FAIL:\s*(.*)$', source, re.MULTILINE)
        if not m:
            print(f"  SKIP  {ep_name:30s}  no # COMPILE_FAIL annotation")
            skipped += 1
            continue

        expected_text = m.group(1).strip()

        result = subprocess.run(
            [sys.executable, EPICC, ep_path],
            capture_output=True,
            text=True,
            cwd=ROOT_DIR,
            timeout=30,
        )

        output = result.stdout + result.stderr
        if result.returncode == 0:
            print(f"  FAIL  {ep_name:30s}  compile succeeded, expected failure")
            failed += 1
            continue

        if expected_text and expected_text not in output:
            print(f"  FAIL  {ep_name:30s}  expected {expected_text!r} not in:\n{output[:500]}")
            failed += 1
            continue

        passed += 1
        print(f"  PASS  {ep_name:30s}")

    return passed, failed, skipped


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Sema typed AST golden and fail tests")
    parser.add_argument("--regen", action="store_true", help="regenerate tests/sema/pass/typed_ast_dump.txt")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.regen:
        regen_golden()
        return 0

    total_passed = 0
    total_failed = 0
    total_skipped = 0

    p, f, s = run_pass_tests()
    total_passed += p
    total_failed += f
    total_skipped += s

    p, f, s = run_self_hosted_pass_tests()
    total_passed += p
    total_failed += f
    total_skipped += s

    p, f, s = run_fail_tests()
    total_passed += p
    total_failed += f
    total_skipped += s

    print(f"\nsema: {total_passed} passed, {total_failed} failed, {total_skipped} skipped")
    return 1 if total_failed > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
