#!/usr/bin/env python3
"""Smoke tests for the Python MIR prototype."""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "bootstrap"))

from lexer import lex
from mir import BOOL, I32, I64, Br, CondBr, MirBlock, MirFunction, MirInst, MirParam
from mir import MirProgram, MirValue, Ret, ValueOperand, ConstIntOperand, ConstNullOperand
from mir import MirValidationError, validate, ptr, struct as mir_struct
from mir_codegen import ast_to_mir
from mir_runtime_helpers import IMPLEMENTED_MIR_HELPERS
from parser import Parser
import sema


def build_smoke_program():
    x_addr = MirValue("%x.addr", ptr(I64))
    x0 = MirValue("%x0", I64)
    c0 = MirValue("%c0", BOOL)
    x1 = MirValue("%x1", I64)
    r = MirValue("%r", I64)

    entry = MirBlock(
        "entry",
        [
            MirInst("alloca", result=x_addr, type=I64),
            MirInst("store", [ConstIntOperand(I64, 0), ValueOperand(x_addr)]),
        ],
        Br("loop"),
    )
    loop = MirBlock(
        "loop",
        [
            MirInst("load", [ValueOperand(x_addr)], result=x0, type=I64),
            MirInst("icmp.lt", [ValueOperand(x0), ConstIntOperand(I64, 3)], result=c0),
        ],
        CondBr(ValueOperand(c0), "body", "done"),
    )
    body = MirBlock(
        "body",
        [
            MirInst("add", [ValueOperand(x0), ConstIntOperand(I64, 1)], result=x1),
            MirInst("store", [ValueOperand(x1), ValueOperand(x_addr)]),
        ],
        Br("loop"),
    )
    done = MirBlock(
        "done",
        [
            MirInst("load", [ValueOperand(x_addr)], result=r, type=I64),
        ],
        Ret(ValueOperand(r)),
    )
    main = MirFunction("@main", [], I64, [entry, loop, body, done])
    return MirProgram(functions=[main])


def test_smoke_text_and_validation():
    program = build_smoke_program()
    validate(program)
    expected = """fn @main() -> i64 {
entry:
  %x.addr: ptr = alloca i64
  store i64 0, ptr %x.addr
  br label %loop

loop:
  %x0: i64 = load i64, ptr %x.addr
  %c0: bool = icmp.lt i64 %x0, i64 3
  condbr bool %c0, label %body, label %done

body:
  %x1: i64 = add i64 %x0, i64 1
  store i64 %x1, ptr %x.addr
  br label %loop

done:
  %r: i64 = load i64, ptr %x.addr
  ret i64 %r
}"""
    assert program.text() == expected


def assert_mir_invalid(program, message):
    try:
        validate(program)
    except MirValidationError as e:
        assert message in str(e), str(e)
        return
    raise AssertionError("expected MirValidationError")


def test_gep_null_and_ptrtoint_text_and_validation():
    size_ptr = MirValue("%size.ptr", ptr())
    size = MirValue("%size", I64)
    field_ptr = MirValue("%field.ptr", ptr(I64))
    block = MirBlock(
        "entry",
        [
            MirInst("gep", [ConstNullOperand(), ConstIntOperand(I64, 1)], result=size_ptr, type=mir_struct("Pair")),
            MirInst("ptrtoint", [ValueOperand(size_ptr)], result=size, type=I64),
            MirInst(
                "gep",
                [ConstNullOperand(), ConstIntOperand(I64, 0), ConstIntOperand(I32, 1)],
                result=field_ptr,
                type=mir_struct("Pair"),
            ),
        ],
        Ret(ValueOperand(size)),
    )
    program = MirProgram(
        functions=[MirFunction("@main", [], I64, [block])],
        structs={"Pair": {"fields": {"left": {"type": I64, "offset": 0}, "right": {"type": I64, "offset": 8}}, "size": 16}},
    )
    validate(program)
    expected = """fn @main() -> i64 {
entry:
  %size.ptr: ptr = gep struct Pair, ptr null, i64 1
  %size: i64 = ptrtoint ptr %size.ptr to i64
  %field.ptr: ptr = gep struct Pair, ptr null, i64 0, i32 1
  ret i64 %size
}"""
    assert program.text() == expected


def test_validator_rejects_unknown_and_high_level_ops():
    result = MirValue("%x", I64)
    unknown = MirProgram(functions=[MirFunction("@main", [], I64, [MirBlock("entry", [MirInst("mystery", result=result)], Ret(ValueOperand(result)))])])
    assert_mir_invalid(unknown, "unknown MIR op: mystery")

    high = MirProgram(functions=[MirFunction("@main", [], I64, [MirBlock("entry", [MirInst("field.load", [ConstNullOperand()], result=result, type=I64, callee="x")], Ret(ValueOperand(result)))])])
    assert_mir_invalid(high, "high-level MIR op is not allowed: field.load")


def test_codegen_emits_target_mir_only_for_aggregates():
    source = """
struct Point {
    x: i64
    y: i64
}

fun main(): i64 {
    let p = new Point { y: 2, x: 1 }
    let xs = new i64[] { 4 }
    push(xs, 5)
    return xs[0]
}
"""
    program = ast_to_mir(sema.analyze_program(Parser(lex(source)).parse_program()))
    text = program.text()
    for op in (
        "struct.new",
        "field.load",
        "field.store",
        "array.new",
        "array.push",
        "array.extend",
        "array.index.load",
        "ptr.index.load",
        "ptr.i8.get",
        "ptr.i64.get",
    ):
        assert op not in text


def test_mir_helper_injection():
    """Verify all implemented MIR runtime helpers are always injected."""

    assert "__ep_slice_u8_slice" in IMPLEMENTED_MIR_HELPERS
    assert "__ep_slice_i64_new" in IMPLEMENTED_MIR_HELPERS
    assert "__ep_slice_i64_get" in IMPLEMENTED_MIR_HELPERS
    assert "__ep_slice_i64_set" in IMPLEMENTED_MIR_HELPERS
    assert "__ep_slice_i64_push" in IMPLEMENTED_MIR_HELPERS
    assert "__ep_slice_ptr_new" in IMPLEMENTED_MIR_HELPERS
    assert "__ep_slice_ptr_get" in IMPLEMENTED_MIR_HELPERS
    assert "__ep_slice_ptr_set" in IMPLEMENTED_MIR_HELPERS
    assert "__ep_slice_ptr_push" in IMPLEMENTED_MIR_HELPERS
    assert "__ep_slice_u8_extend" in IMPLEMENTED_MIR_HELPERS
    assert "__ep_str_eq" not in IMPLEMENTED_MIR_HELPERS
    assert "__ep_str_from_bool" not in IMPLEMENTED_MIR_HELPERS
    assert "__ep_str_cat" in IMPLEMENTED_MIR_HELPERS
    assert "__ep_str_slice" in IMPLEMENTED_MIR_HELPERS
    assert "__ep_str_starts_with" not in IMPLEMENTED_MIR_HELPERS
    assert "__ep_str_get" in IMPLEMENTED_MIR_HELPERS
    assert "__ep_str_find" not in IMPLEMENTED_MIR_HELPERS
    assert "__ep_str_replace_char" not in IMPLEMENTED_MIR_HELPERS
    assert "__ep_str_trim" not in IMPLEMENTED_MIR_HELPERS

    # i64[] reads use __ep_slice_i64_get, not __epic_slice_i64_get
    src_i64 = """fun main(): i64 {
    let xs = new i64[] { 10, 20 }
    return xs[1]
}"""
    ast_i64 = sema.analyze_program(Parser(lex(src_i64)).parse_program())
    prog_i64 = ast_to_mir(ast_i64)
    text_i64 = prog_i64.text()
    assert "call i64 __ep_slice_i64_get" in text_i64, \
        f"expected call i64 __ep_slice_i64_get, got:\n{text_i64}"
    assert "__epic_slice_i64_get" not in text_i64, \
        f"unexpected __epic_slice_i64_get:\n{text_i64}"
    old_qword_new = "__epx_slice_" + "qword_new"
    old_i64_push = "__epx_slice_" + "i64_push"
    assert old_qword_new not in text_i64, \
        f"unexpected {old_qword_new}:\n{text_i64}"
    assert old_i64_push not in text_i64, \
        f"unexpected {old_i64_push}:\n{text_i64}"

    # i64[] writes use __ep_slice_i64_set
    src_i64_set = """fun main(): i64 {
    let xs = new i64[] { 10, 20 }
    xs[0] = 99
    return xs[0]
}"""
    ast_i64_set = sema.analyze_program(Parser(lex(src_i64_set)).parse_program())
    prog_i64_set = ast_to_mir(ast_i64_set)
    text_i64_set = prog_i64_set.text()
    assert "call void __ep_slice_i64_set" in text_i64_set, \
        f"expected call void __ep_slice_i64_set, got:\n{text_i64_set}"

    def check(source):
        ast = sema.analyze_program(Parser(lex(source)).parse_program())
        prog = ast_to_mir(ast)
        injected = {fn.name for fn in prog.functions}
        externs = {ext.name for ext in prog.externs}
        global_names = [glob.name for glob in prog.globals]
        assert global_names.count("@str.runtime.bool.true") == 1
        assert global_names.count("@str.runtime.bool.false") == 1
        for name in IMPLEMENTED_MIR_HELPERS:
            assert name in injected, f"{name} should be injected as MirFunction, got injected={injected}"
            assert name not in externs, f"{name} should be removed from externs, got externs={externs}"
        return prog

    check(
        """fun main(): i64 {
    let b = bytes("AB")
    return 0
}"""
    )

    check(
        """fun main(): i64 {
    let a = new u8[] { 65 }
    println(str(a))
    return 0
}"""
    )

    check(
        """fun main(): i64 {
    let a = new u8[] { 1, 2 }
    return 0
}"""
    )

    check(
        """fun main(): i64 {
    let b = new u8[] { 1, 2 }
    return b[0]
}"""
    )

    check(
        """fun main(): i64 {
    let b = new u8[] { 1, 2 }
    push(b, 3)
    return len(b)
}"""
    )

    check(
        """fun main(): i64 {
    let b = new u8[] { 1, 2, 3 }
    let c = b[1:3]
    return len(c)
}"""
    )

    check(
        """fun main(): i64 {
    let a = new u8[] { 1, 2 }
    let b = new u8[] { 3, 4 }
    extend(a, b)
    return len(a)
}"""
    )

    check(
        """fun main(): i64 {
    if "epic" == "epic" {
        return 1
    }
    return 0
}"""
    )

    check(
        """fun main(): i64 {
    println(str(true))
    println(str(false))
    return 0
}"""
    )

    check(
        """fun main(): i64 {
    let s = "epic-lang"
    let t = s[5:9]
    return len(t)
}"""
    )

    check(
        """fun main(): i64 {
    let s = "epic"
    return s[1]
}"""
    )

    # Deterministic order: running twice gives same injection list
    src = """fun main(): i64 {
    let b = new u8[] { 65, 66 }
    b[0] = 99
    return b[0]
}"""
    ast = sema.analyze_program(Parser(lex(src)).parse_program())
    prog1 = ast_to_mir(ast)
    prog2 = ast_to_mir(ast)
    helper_names = set(IMPLEMENTED_MIR_HELPERS)
    order1 = [fn.name for fn in prog1.functions if fn.name in helper_names]
    order2 = [fn.name for fn in prog2.functions if fn.name in helper_names]
    assert order1 == order2, f"helper order differs between runs: {order1} != {order2}"
    assert order1 == list(IMPLEMENTED_MIR_HELPERS), f"unexpected helper order: {order1}"


def test_runtime_source_str_eq_lowers_as_epic_function():
    runtime_src = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "runtime", "str.ep")).read_text(encoding="utf-8")
    user_src = """fun main(): i64 {
    if "epic" == "epic" {
        return 1
    }
    if "epic" != "lang" {
        return 2
    }
    return 0
}"""
    ast = Parser(lex(runtime_src + "\n" + user_src)).parse_program()
    prog = ast_to_mir(sema.analyze_program(ast))
    text = prog.text()
    function_names = {fn.name for fn in prog.functions}
    extern_names = {ext.name for ext in prog.externs}
    assert "__ep_str_eq" in function_names
    assert "__ep_str_eq" not in extern_names
    assert "call bool __ep_str_eq" in text
    assert "fn __ep_str_eq(ptr left, ptr right) -> bool" in text
    assert "fn __ep_str_eq" in text


def test_runtime_source_str_from_bool_lowers_as_epic_function():
    runtime_src = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "runtime", "str.ep")).read_text(encoding="utf-8")
    user_src = """fun main(): void {
    println(str(true))
    println(str(false))
}"""
    ast = Parser(lex(runtime_src + "\n" + user_src)).parse_program()
    prog = ast_to_mir(sema.analyze_program(ast))
    text = prog.text()
    function_names = {fn.name for fn in prog.functions}
    extern_names = {ext.name for ext in prog.externs}
    assert "__ep_str_from_bool" in function_names
    assert "__ep_str_from_bool" not in extern_names
    assert "call ptr __ep_str_from_bool" in text
    assert "fn __ep_str_from_bool(bool value) -> ptr" in text


def main():
    test_smoke_text_and_validation()
    test_gep_null_and_ptrtoint_text_and_validation()
    test_validator_rejects_unknown_and_high_level_ops()
    test_codegen_emits_target_mir_only_for_aggregates()
    test_mir_helper_injection()
    test_runtime_source_str_eq_lowers_as_epic_function()
    test_runtime_source_str_from_bool_lowers_as_epic_function()
    print("PASS test_mir")


if __name__ == "__main__":
    main()
