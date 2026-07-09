#!/usr/bin/env python3
"""Smoke tests for the Python MIR prototype."""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "bootstrap"))

from lexer import lex
from mir import BOOL, I32, I64, Br, CondBr, MirBlock, MirField, MirFunction, MirInst, MirParam
from mir import MirProgram, MirStruct, MirValue, Ret, ValueOperand, ConstIntOperand, ConstNullOperand
from mir import MirValidationError, validate, ptr, struct as mir_struct
from ast_to_mir import ast_to_mir
from mir_runtime_helpers import IMPLEMENTED_MIR_HELPERS
from mir_parser import parse_mir_file, parse_mir_text
from parser import Parser
import sema


def build_smoke_program():
    x_addr = MirValue("x.addr", ptr())
    x0 = MirValue("x0", I64)
    c0 = MirValue("c0", BOOL)
    x1 = MirValue("x1", I64)
    r = MirValue("r", I64)

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
            MirInst("icmp.slt", [ValueOperand(x0), ConstIntOperand(I64, 3)], result=c0),
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
    main = MirFunction("main", [], I64, [entry, loop, body, done])
    return MirProgram(functions=[main])


def test_smoke_text_and_validation():
    program = build_smoke_program()
    validate(program)
    expected = """define i64 @main() {
entry:
  %x.addr: ptr = alloca i64
  store i64 0, ptr %x.addr
  br label %loop

loop:
  %x0: i64 = load i64, ptr %x.addr
  %c0: bool = icmp.slt i64 %x0, i64 3
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
    size_ptr = MirValue("size.ptr", ptr())
    size = MirValue("size", I64)
    field_ptr = MirValue("field.ptr", ptr())
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
        functions=[MirFunction("main", [], I64, [block])],
        structs={"Pair": MirStruct("Pair", [MirField("left", I64, 0), MirField("right", I64, 8)], 16)},
    )
    validate(program)
    expected = """define i64 @main() {
entry:
  %size.ptr: ptr = gep struct Pair, ptr null, i64 1
  %size: i64 = ptrtoint ptr %size.ptr to i64
  %field.ptr: ptr = gep struct Pair, ptr null, i64 0, i32 1
  ret i64 %size
}"""
    assert program.text() == expected


def test_validator_rejects_text_sigils_in_local_names():
    bad_value = MirValue("%x", I64)
    bad_value_program = MirProgram(functions=[MirFunction("main", [], I64, [MirBlock("entry", [], Ret(ValueOperand(bad_value)))])])
    assert_mir_invalid(bad_value_program, "local value name must be raw")

    bad_param_program = MirProgram(functions=[MirFunction("main", [MirParam("%p", I64)], I64, [MirBlock("entry", [], Ret(ValueOperand(MirValue("%p", I64))))])])
    assert_mir_invalid(bad_param_program, "local value name must be raw")


def test_validator_rejects_text_sigils_in_module_symbols():
    value = MirValue("x", I64)
    bad_fn = MirProgram(functions=[MirFunction("@main", [], I64, [MirBlock("entry", [], Ret(ConstIntOperand(I64, 0)))])])
    assert_mir_invalid(bad_fn, "module symbol must be raw")

    block = MirBlock("entry", [MirInst("ptrtoint", [SymbolOperand(ptr(), "@g")], result=value, type=I64)], Ret(ValueOperand(value)))
    bad_operand = MirProgram(globals=[MirGlobal("g", ptr(), "x")], functions=[MirFunction("main", [], I64, [block])])
    assert_mir_invalid(bad_operand, "symbol operand must be raw")


def test_validator_rejects_unknown_and_high_level_ops():
    result = MirValue("x", I64)
    unknown = MirProgram(functions=[MirFunction("main", [], I64, [MirBlock("entry", [MirInst("mystery", result=result)], Ret(ValueOperand(result)))])])
    assert_mir_invalid(unknown, "unknown MIR op: mystery")

    high = MirProgram(functions=[MirFunction("main", [], I64, [MirBlock("entry", [MirInst("field.load", [ConstNullOperand()], result=result, type=I64, callee="x")], Ret(ValueOperand(result)))])])
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
    xs.push(5)
    ret xs[0]
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


def test_mir_parser_rejects_unsigned_integer_types():
    for typ in ("u64", "u8"):
        source = f"""define {typ} @main({typ} %x) {{
entry:
  ret {typ} %x
}}
"""
        try:
            parse_mir_text(source)
        except Exception as exc:
            assert "unknown type" in str(exc)
        else:
            raise AssertionError(f"MIR parser accepted unsigned integer type: {typ}")


def test_mir_parser_strips_text_sigils():
    source = """declare ptr @helper(ptr)

define ptr @main(ptr %arg) {
entry:
  %tmp: ptr = call ptr @helper(ptr %arg)
  ret ptr %tmp
}
"""
    program = parse_mir_text(source)
    assert program.externs[0].name == "helper"
    fn = program.functions[0]
    assert fn.name == "main"
    assert fn.params[0].name == "arg"
    inst = fn.blocks[0].instructions[0]
    assert inst.result.name == "tmp"
    assert inst.callee == "helper"
    assert fn.text().startswith("define ptr @main(ptr %arg)")


def test_runtime_mir_bundle_parses_without_local_validation():
    runtime_mir_dir = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "runtime", "mir"))
    path = runtime_mir_dir / "helpers.mir"
    assert sorted(p.name for p in runtime_mir_dir.glob("*.mir")) == ["helpers.mir"]
    text = path.read_text(encoding="utf-8")
    try:
        parse_mir_text(text, filename=str(path))
    except MirValidationError as exc:
        assert "callee is not callable" in str(exc), str(exc)
    else:
        raise AssertionError("runtime helper bundle should not need local extern declarations")

    program = parse_mir_file(path, validate_program=False)
    assert [fn.name for fn in program.functions] == list(IMPLEMENTED_MIR_HELPERS)
    parsed_fn = next(fn for fn in program.functions if fn.name == "__ep_slice_i64_get")
    assert parsed_fn.text() in text


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
    assert "__ep_str_slice" not in IMPLEMENTED_MIR_HELPERS
    assert "__ep_str_starts_with" not in IMPLEMENTED_MIR_HELPERS
    assert "__ep_str_get" not in IMPLEMENTED_MIR_HELPERS
    assert "__ep_str_find" not in IMPLEMENTED_MIR_HELPERS
    assert "__ep_str_replace_char" not in IMPLEMENTED_MIR_HELPERS
    assert "__ep_str_trim" not in IMPLEMENTED_MIR_HELPERS

    # i64[] reads use __ep_slice_i64_get, not __epic_slice_i64_get
    src_i64 = """fun main(): i64 {
    let xs = new i64[] { 10, 20 }
    ret xs[1]
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
    ret xs[0]
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
        assert global_names.count("str.runtime.bool.true") == 1
        assert global_names.count("str.runtime.bool.false") == 1
        for name in IMPLEMENTED_MIR_HELPERS:
            assert name in injected, f"{name} should be injected as MirFunction, got injected={injected}"
            assert name not in externs, f"{name} should be removed from externs, got externs={externs}"
        return prog

    check(
        """fun main(): i64 {
    let b = bytes("AB")
    ret 0
}"""
    )

    parsed_helper_path = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "runtime", "mir", "helpers.mir"))
    parsed_helper_program = parse_mir_file(parsed_helper_path, validate_program=False)
    parsed_helper_text = next(fn for fn in parsed_helper_program.functions if fn.name == "__ep_slice_i64_get").text()
    parsed_prog = check(
        """fun main(): i64 {
    let xs = new i64[] { 10, 20 }
    ret xs[1]
}"""
    )
    parsed_fn = next(fn for fn in parsed_prog.functions if fn.name == "__ep_slice_i64_get")
    assert parsed_fn.text() == parsed_helper_text

    check(
        """fun main(): i64 {
    let a = new u8[] { u8(65) }
    println(str(a))
    ret 0
}"""
    )

    check(
        """fun main(): i64 {
    let a = new u8[] { u8(1), u8(2) }
    ret 0
}"""
    )

    check(
        """fun main(): i64 {
    let b = new u8[] { u8(1), u8(2) }
    ret i64(b[0])
}"""
    )

    check(
        """fun main(): i64 {
    let b = new u8[] { u8(1), u8(2) }
    b.push(u8(3))
    ret len(b)
}"""
    )

    check(
        """fun main(): i64 {
    let b = new u8[] { u8(1), u8(2), u8(3) }
    let c = b[1:3]
    ret len(c)
}"""
    )

    check(
        """fun main(): i64 {
    let a = new u8[] { u8(1), u8(2) }
    let b = new u8[] { u8(3), u8(4) }
    a.extend(b)
    ret len(a)
}"""
    )

    check(
        """fun main(): i64 {
    if "epic" == "epic" {
        ret 1
    }
    ret 0
}"""
    )

    check(
        """fun main(): i64 {
    println(str(true))
    println(str(false))
    ret 0
}"""
    )

    check(
        """fun main(): i64 {
    let s = "epic-lang"
    let t = s[5:9]
    ret len(t)
}"""
    )

    # Deterministic order: running twice gives same injection list
    src = """fun main(): i64 {
    let b = new u8[] { u8(65), u8(66) }
    b[0] = u8(99)
    ret i64(b[0])
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
        ret 1
    }
    if "epic" != "lang" {
        ret 2
    }
    ret 0
}"""
    ast = Parser(lex(runtime_src + "\n" + user_src)).parse_program()
    prog = ast_to_mir(sema.analyze_program(ast))
    text = prog.text()
    function_names = {fn.name for fn in prog.functions}
    extern_names = {ext.name for ext in prog.externs}
    assert "__ep_str_eq" in function_names
    assert "__ep_str_eq" not in extern_names
    assert "call bool __ep_str_eq" in text
    assert "define bool @__ep_str_eq(ptr %left, ptr %right)" in text
    assert "define bool @__ep_str_eq" in text


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
    assert "define ptr @__ep_str_from_bool(bool %value)" in text


def test_runtime_source_str_from_i64_lowers_as_epic_function():
    runtime_src = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "runtime", "str.ep")).read_text(encoding="utf-8")
    user_src = """fun main(): void {
    println(str(0 - 9223372036854775807 - 1))
}"""
    ast = Parser(lex(runtime_src + "\n" + user_src)).parse_program()
    prog = ast_to_mir(sema.analyze_program(ast))
    text = prog.text()
    function_names = {fn.name for fn in prog.functions}
    extern_names = {ext.name for ext in prog.externs}
    assert "__ep_str_from_i64" in function_names
    assert "__ep_str_from_i64" not in extern_names
    assert "call ptr __ep_str_from_i64" in text
    assert "define ptr @__ep_str_from_i64(i64 %value)" in text
    assert "-9223372036854775808" in text


def test_runtime_source_str_from_u64_lowers_as_epic_function():
    runtime_src = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "runtime", "str.ep")).read_text(encoding="utf-8")
    user_src = """fun main(): void {
    println(str((u64(0) - u64(1))))
}"""
    ast = Parser(lex(runtime_src + "\n" + user_src)).parse_program()
    prog = ast_to_mir(sema.analyze_program(ast))
    text = prog.text()
    function_names = {fn.name for fn in prog.functions}
    extern_names = {ext.name for ext in prog.externs}
    assert "__ep_str_from_u64" in function_names
    assert "__ep_str_from_u64" not in extern_names
    assert "call ptr __ep_str_from_u64" in text
    assert "define ptr @__ep_str_from_u64(i64 %value)" in text


def test_runtime_source_str_slice_lowers_as_epic_function():
    runtime_src = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "runtime", "str.ep")).read_text(encoding="utf-8")
    user_src = """fun main(): void {
    let s = "Epic"
    print(s[1:4])
}"""
    ast = Parser(lex(runtime_src + "\n" + user_src)).parse_program()
    prog = ast_to_mir(sema.analyze_program(ast))
    text = prog.text()
    function_names = {fn.name for fn in prog.functions}
    extern_names = {ext.name for ext in prog.externs}
    assert "__ep_str_slice" in function_names
    assert "__ep_str_slice" not in extern_names
    assert "call ptr __ep_str_slice" in text
    assert "define ptr @__ep_str_slice(ptr %s, i64 %start, i64 %end)" in text
    assert "invalid string slice" in text



def test_user_method_lowers_to_mangled_function_call():
    source = """struct Counter {
    value: i64
}

fun (c: Counter) add(delta: i64): i64 {
    ret c.value + delta
}

fun main(): i64 {
    let c = new Counter { value: 40 }
    ret c.add(2)
}
"""
    ast = Parser(lex(source)).parse_program()
    method = ast.funcs[0]
    assert method.name == "Counter__add"
    assert method.method_name == "add"
    assert method.receiver_name == "c"
    assert method.receiver_type.kind == "named"
    assert method.receiver_type.name == "Counter"
    typed = sema.analyze_program(ast)
    prog = ast_to_mir(typed)
    text = prog.text()
    assert "define i64 @Counter__add(ptr %c, i64 %delta)" in text
    assert "call i64 Counter__add" in text


def test_user_method_conflicts_with_mangled_function_name():
    source = """struct Counter {
    value: i64
}

fun Counter__add(c: Counter, delta: i64): i64 {
    ret c.value + delta
}

fun (c: Counter) add(delta: i64): i64 {
    ret c.value + delta
}

fun main(): i64 {
    let c = new Counter { value: 1 }
    ret c.add(2)
}
"""
    try:
        sema.analyze_program(Parser(lex(source)).parse_program())
    except sema.SemanticError as exc:
        assert "duplicate function Counter__add" in str(exc)
        return
    raise AssertionError("expected duplicate method symbol error")


def test_adt_struct_union_lowers_to_wrapper_and_payload_match():
    source = """struct LiteralExpr {
    value: str
    line: i64
}

struct BinaryExpr {
    op: str
    left: Expr
    right: Expr
    line: i64
}

type Expr = LiteralExpr | BinaryExpr

fun literal_value(x: LiteralExpr): str {
    ret x.value
}

fun main(): void {
    let e: Expr = new Expr(new LiteralExpr { value: "1", line: 1 })
    match e {
        LiteralExpr lit: {
            print(literal_value(lit))
        }
        BinaryExpr b: {
            print(b.op)
        }
    }
}
"""
    ast = Parser(lex(source)).parse_program()
    assert ast.unions[0].name == "Expr"
    assert ast.unions[0].members == ["LiteralExpr", "BinaryExpr"]
    typed = sema.analyze_program(ast)
    prog = ast_to_mir(typed)
    text = prog.text()
    assert "gep struct Expr" in text
    assert "call ptr __epx_alloc" in text
    assert "i64 1" in text
    assert "call ptr literal_value" in text


def test_adt_match_must_be_exhaustive_without_default():
    source = """struct LiteralExpr {
    value: str
}

struct BinaryExpr {
    op: str
}

type Expr = LiteralExpr | BinaryExpr

fun main(): void {
    let e: Expr = new Expr(new LiteralExpr { value: "1" })
    match e {
        LiteralExpr lit: {
            print(lit.value)
        }
    }
}
"""
    try:
        sema.analyze_program(Parser(lex(source)).parse_program())
    except sema.SemanticError as exc:
        assert "non-exhaustive match for Expr; missing BinaryExpr" in str(exc)
        return
    raise AssertionError("expected non-exhaustive ADT match error")


def test_adt_requires_explicit_wrapper_construction():
    source = """struct LiteralExpr {
    value: str
}

type Expr = LiteralExpr

fun main(): void {
    let e: Expr = new LiteralExpr { value: "1" }
}
"""
    try:
        sema.analyze_program(Parser(lex(source)).parse_program())
    except sema.SemanticError as exc:
        assert "let e expected Expr, got LiteralExpr" in str(exc)
        return
    raise AssertionError("expected explicit ADT wrapper construction error")


def test_adt_single_wildcard_match_is_allowed():
    source = """struct LiteralExpr {
    value: str
}

type Expr = LiteralExpr

fun main(): void {
    let e: Expr = new Expr(new LiteralExpr { value: "1" })
    match e {
        _: {
            print("ok")
        }
    }
}
"""
    typed = sema.analyze_program(Parser(lex(source)).parse_program())
    prog = ast_to_mir(typed)
    text = prog.text()
    assert "gep struct Expr" in text
    assert "call void __ep_print_str" in text

def main():
    test_smoke_text_and_validation()
    test_gep_null_and_ptrtoint_text_and_validation()
    test_validator_rejects_unknown_and_high_level_ops()
    test_codegen_emits_target_mir_only_for_aggregates()
    test_mir_parser_rejects_unsigned_integer_types()
    test_mir_parser_strips_text_sigils()
    test_runtime_mir_bundle_parses_without_local_validation()
    test_mir_helper_injection()
    test_runtime_source_str_eq_lowers_as_epic_function()
    test_runtime_source_str_from_bool_lowers_as_epic_function()
    test_runtime_source_str_from_i64_lowers_as_epic_function()
    test_runtime_source_str_from_u64_lowers_as_epic_function()
    test_runtime_source_str_slice_lowers_as_epic_function()
    test_user_method_lowers_to_mangled_function_call()
    test_user_method_conflicts_with_mangled_function_name()
    test_adt_struct_union_lowers_to_wrapper_and_payload_match()
    test_adt_match_must_be_exhaustive_without_default()
    test_adt_requires_explicit_wrapper_construction()
    test_adt_single_wildcard_match_is_allowed()
    print("PASS test_mir")


if __name__ == "__main__":
    main()
