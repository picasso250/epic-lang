#!/usr/bin/env python3
"""
tests/parser/run.py - Compare the self-hosted parser against the Python
parser on examples/*.ep.
"""

import argparse
import difflib
import os
import re
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))

sys.path.insert(0, os.path.join(ROOT_DIR, "bootstrap"))
from ast_nodes import *
from lexer import lex
from parser import ParseError, Parser


EPICC = os.path.join(ROOT_DIR, "bootstrap", "epic.py")
EXAMPLES_DIR = os.path.join(ROOT_DIR, "examples")
PARSER_FAIL_DIR = os.path.join(SCRIPT_DIR, "fail")
PARSER_PASS_DIR = os.path.join(SCRIPT_DIR, "pass")
ALL_EP = os.path.join(PARSER_PASS_DIR, "all.ep")
AST_DUMP = os.path.join(PARSER_PASS_DIR, "ast_dump.txt")
UTIL_EP = os.path.join(ROOT_DIR, "src", "util.ep")
LEXER_EP = os.path.join(ROOT_DIR, "src", "lexer.ep")
PARSER_EP = os.path.join(ROOT_DIR, "src", "parser.ep")
PARSER_EXE = os.path.join(ROOT_DIR, "build", "src", "parser.exe")
SELF_HOSTED_PARSER_SOURCES = [LEXER_EP, PARSER_EP]
CRLF_SAMPLE_LF = """# parser line ending contract\nfun main(): i64 {\n    # comment before CRLF\n    let x = 1\n    if x == 1 {\n        return 0\n    }\n    return 1\n}\n"""


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
    elif isinstance(node, NewArrayNode):
        emit(f"NewArray : {node.elem_type}")
        if node.count is not None:
            out.extend(py_dump(node.count, depth + 1))
    elif isinstance(node, StructInitNode):
        emit(f"StructInit {node.type_name}")
        for field, value in node.fields:
            out.append(line(depth + 1, f"InitField {field}"))
            out.extend(py_dump(value, depth + 2))
    elif isinstance(node, ArrayLiteralNode):
        emit(f"ArrayLiteral : {node.elem_type}")
        for value in node.values:
            out.extend(py_dump(value, depth + 1))
    elif isinstance(node, MapInitNode):
        if not node.entries:
            emit(f"New {node.type_name}")
            return out
        emit(f"MapInit : {node.type_name}")
        for key, value in node.entries:
            out.append(line(depth + 1, "Key"))
            out.extend(py_dump(key, depth + 2))
            out.append(line(depth + 1, "Value"))
            out.extend(py_dump(value, depth + 2))
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


def python_parser_dump_source(source):
    ast = Parser(lex(source)).parse_program()
    return "\n".join(py_dump(ast)) + "\n"


def python_parser_dump(path):
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    return python_parser_dump_source(source)


def read_golden():
    with open(AST_DUMP, "r", encoding="utf-8") as f:
        return f.read()


def check_golden():
    if not os.path.isfile(ALL_EP):
        print(f"  FAIL   missing parser fixture: {ALL_EP}")
        return False
    if not os.path.isfile(AST_DUMP):
        print(f"  FAIL   missing parser golden: {AST_DUMP}")
        return False

    expected = read_golden()
    actual = python_parser_dump(ALL_EP)
    if actual == expected:
        print("  PASS   parser/pass/all.ep matches ast_dump.txt")
        return True

    print("  FAIL   parser/pass/all.ep matches ast_dump.txt")
    print_diff(expected, actual, "golden/ast_dump.txt", "python/parser/pass/all.ep")
    return False


def regen_golden():
    os.makedirs(PARSER_PASS_DIR, exist_ok=True)
    with open(AST_DUMP, "w", encoding="utf-8", newline="\n") as f:
        f.write(python_parser_dump(ALL_EP))
    print(f"Regenerated {os.path.relpath(AST_DUMP, ROOT_DIR)}")


def ensure_bootstrap_parser():
    result = subprocess.run(
        [sys.executable, EPICC, "--main", PARSER_EP, UTIL_EP, LEXER_EP, PARSER_EP],
        cwd=ROOT_DIR,
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
        cwd=ROOT_DIR,
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


def expected_compile_fail(path):
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    m = re.search(r'#\s*COMPILE_FAIL:\s*(.*)$', source, re.MULTILINE)
    if m is None:
        return ""
    return m.group(1).strip()


def run_python_parser_fail(path, expected):
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    try:
        python_parser_dump_source(source)
    except ParseError as e:
        return expected == "" or expected in str(e)
    return False


def run_bootstrap_parser_fail(path, expected):
    result = subprocess.run(
        [PARSER_EXE, path],
        cwd=ROOT_DIR,
        capture_output=True,
    )
    output = (
        result.stdout.decode("utf-8", errors="replace")
        + result.stderr.decode("utf-8", errors="replace")
    )
    if result.returncode == 0:
        return False
    return expected == "" or expected in output


def run_parser_fail_tests():
    if not os.path.isdir(PARSER_FAIL_DIR):
        return 0

    failed = 0
    cases = sorted(
        os.path.join(PARSER_FAIL_DIR, name)
        for name in os.listdir(PARSER_FAIL_DIR)
        if name.endswith(".ep")
    )
    if not cases:
        return 0

    print(f"\nChecking parser fail cases ({len(cases)})...\n")
    for path in cases:
        rel = os.path.relpath(path, ROOT_DIR)
        expected = expected_compile_fail(path)
        if expected == "":
            failed += 1
            print(f"  FAIL   {rel}  missing # COMPILE_FAIL annotation")
            continue
        python_ok = run_python_parser_fail(path, expected)
        bootstrap_ok = run_bootstrap_parser_fail(path, expected)
        if python_ok and bootstrap_ok:
            print(f"  PASS   {rel}")
            continue
        failed += 1
        if not python_ok:
            print(f"  FAIL   {rel}  Python parser did not fail with {expected!r}")
        if not bootstrap_ok:
            print(f"  FAIL   {rel}  self-hosted parser did not fail with {expected!r}")
    return failed


def write_crlf_sample():
    path = os.path.join(ROOT_DIR, "build", "tests", "parser_crlf.ep")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(CRLF_SAMPLE_LF.replace("\n", "\r\n").encode("utf-8"))
    return path


def print_diff(expected, actual, expected_label, actual_label):
    diff = difflib.unified_diff(
        expected.splitlines(),
        actual.splitlines(),
        fromfile=expected_label,
        tofile=actual_label,
        lineterm="",
    )
    for i, diff_line in enumerate(diff):
        if i >= 80:
            print("  ... diff truncated ...")
            break
        print(diff_line)


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Parser oracle and self-hosted comparison tests")
    parser.add_argument("--regen", action="store_true", help="regenerate tests/parser/pass/ast_dump.txt")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.regen:
        regen_golden()
        return 0

    ensure_bootstrap_parser()
    examples = sorted(
        os.path.join(EXAMPLES_DIR, name)
        for name in os.listdir(EXAMPLES_DIR)
        if name.endswith(".ep")
    )
    parser_pass = sorted(
        os.path.join(PARSER_PASS_DIR, name)
        for name in os.listdir(PARSER_PASS_DIR)
        if name.endswith(".ep")
    )

    failed = 0
    print("Checking parser golden...\n")
    if not check_golden():
        failed += 1

    print(f"\nComparing parser dumps for {len(examples)} examples and {len(parser_pass)} parser pass sample(s)...\n")
    for path in [*examples, *parser_pass]:
        rel = os.path.relpath(path, ROOT_DIR)
        expected = python_parser_dump(path)
        actual = bootstrap_parser_dump(path)
        if actual == expected:
            print(f"  PASS   {rel}")
            continue

        failed += 1
        print(f"  FAIL   {rel}")
        print_diff(expected, actual, f"python/{rel}", f"bootstrap/{rel}")

    for path in SELF_HOSTED_PARSER_SOURCES:
        rel = os.path.relpath(path, ROOT_DIR)
        expected = python_parser_dump(path)
        actual = bootstrap_parser_dump(path)
        if actual == expected:
            print(f"  PASS   {rel}")
            continue

        failed += 1
        print(f"  FAIL   {rel}")
        print_diff(expected, actual, f"python/{rel}", f"bootstrap/{rel}")

    crlf_path = write_crlf_sample()
    expected = python_parser_dump_source(CRLF_SAMPLE_LF.replace("\n", "\r\n"))
    actual = bootstrap_parser_dump(crlf_path)
    if actual == expected:
        print("  PASS   dynamic CRLF sample")
    else:
        failed += 1
        print("  FAIL   dynamic CRLF sample")
        print_diff(expected, actual, "python/dynamic CRLF sample", "bootstrap/dynamic CRLF sample")

    failed += run_parser_fail_tests()

    fail_count = len([name for name in os.listdir(PARSER_FAIL_DIR) if name.endswith(".ep")])
    total = 1 + len(examples) + len(parser_pass) + len(SELF_HOSTED_PARSER_SOURCES) + 1 + fail_count
    print(f"\n{total - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
