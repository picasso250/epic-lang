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
from lexer import lex
from parser import ParseError, Parser, dump_ast_text


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


def python_parser_dump_source(source):
    ast = Parser(lex(source)).parse_program()
    return dump_ast_text(ast)


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
