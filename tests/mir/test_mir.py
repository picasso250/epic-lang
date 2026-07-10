#!/usr/bin/env python3
"""Smoke tests for the Python MIR prototype."""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "bootstrap"))

from backend_abi import BackendAbiError, validate_backend_abi
from lexer import lex
from mir import BOOL, I32, I64, I8, Br, CondBr, MirBlock, MirField, MirFunction, MirInst, MirParam
from mir import MirGlobal, MirProgram, MirStruct, MirValue, Ret, SymbolOperand, ValueOperand, ConstIntOperand, ConstNullOperand
from mir import MirValidationError, validate, ptr, struct as mir_struct
from ast_to_mir import ast_to_mir
from mir_runtime_helpers import inject_all_mir_helpers
from mir_prune import prune_unreachable_functions
from mir_parser import parse_mir_file, parse_mir_text
from parser import Parser
import sema


def build_smoke_program():
    x_addr = MirValue(1, ptr())
    x0 = MirValue(2, I64)
    c0 = MirValue(3, BOOL)
    x1 = MirValue(4, I64)
    r = MirValue(5, I64)

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
  %1: ptr = alloca i64
  store i64 0, ptr %1
  br label %loop

loop:
  %2: i64 = load i64, ptr %1
  %3: bool = icmp.slt i64 %2, i64 3
  condbr bool %3, label %body, label %done

body:
  %4: i64 = add i64 %2, i64 1
  store i64 %4, ptr %1
  br label %loop

done:
  %5: i64 = load i64, ptr %1
  ret i64 %5
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
    size_ptr = MirValue(1, ptr())
    size = MirValue(2, I64)
    field_ptr = MirValue(3, ptr())
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
    expected = """type Pair = struct { i64, i64 }

define i64 @main() {
entry:
  %1: ptr = gep struct Pair, ptr null, i64 1
  %2: i64 = ptrtoint ptr %1 to i64
  %3: ptr = gep struct Pair, ptr null, i64 0, i32 1
  ret i64 %2
}"""
    assert program.text() == expected


def test_validator_rejects_non_positive_local_ids():
    bad_param_program = MirProgram(functions=[MirFunction("main", [MirParam(0, I64)], I64, [MirBlock("entry", [], Ret(ValueOperand(MirValue(0, I64))))])])
    assert_mir_invalid(bad_param_program, "local value id must be a positive integer")


def test_validator_rejects_text_sigils_in_module_symbols():
    value = MirValue(1, I64)
    bad_fn = MirProgram(functions=[MirFunction("@main", [], I64, [MirBlock("entry", [], Ret(ConstIntOperand(I64, 0)))])])
    assert_mir_invalid(bad_fn, "module symbol must be raw")

    block = MirBlock("entry", [MirInst("ptrtoint", [SymbolOperand(ptr(), "@g")], result=value, type=I64)], Ret(ValueOperand(value)))
    bad_operand = MirProgram(globals=[MirGlobal("g", ptr(), "x")], functions=[MirFunction("main", [], I64, [block])])
    assert_mir_invalid(bad_operand, "symbol operand must be raw")


def test_validator_rejects_unknown_and_high_level_ops():
    result = MirValue(1, I64)
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


def test_struct_type_text_round_trip_and_v0_slot_layout():
    source = """type Zed = struct { ptr }

type Unused = struct { i64 }

type Data = struct { i8, i64 }

define i64 @main() {
entry:
  %1: ptr = gep struct Zed, ptr null, i64 1
  %2: ptr = gep struct Data, ptr null, i64 1
  ret i64 0
}
"""
    program = parse_mir_text(source)
    layout = program.structs["Data"]
    assert [field.type for field in layout.fields] == [I8, I64]
    assert [field.offset for field in layout.fields] == [0, 8]
    assert layout.size == 16
    expected = """type Data = struct { i8, i64 }

type Zed = struct { ptr }

define i64 @main() {
entry:
  %1: ptr = gep struct Zed, ptr null, i64 1
  %2: ptr = gep struct Data, ptr null, i64 1
  ret i64 0
}"""
    assert program.text() == expected


def test_global_text_round_trip_uses_canonical_bytes_literals():
    source = (
        "global @argv: ptr\n\n"
        "global @counter: i64 = 42\n\n"
        'global @str.0: ptr = bytes "A\\n\\\"\\\\\\x00\\xFF//tail"\n\n'
        "define i64 @main() {\n"
        "entry:\n"
        "  ret i64 0\n"
        "}\n"
    )
    program = parse_mir_text(source)
    assert program.globals[0].init is None
    assert program.globals[1].init == "42"
    assert program.globals[2].init == 'A\n"\\\x00\xff//tail'
    assert program.text() == source.rstrip()

def test_mir_parser_rejects_unsigned_integer_types():
    for typ in ("u64", "u8"):
        source = f"""define {typ} @main({typ} %1) {{
entry:
  ret {typ} %1
}}
"""
        try:
            parse_mir_text(source)
        except Exception as exc:
            assert "unknown type" in str(exc)
        else:
            raise AssertionError(f"MIR parser accepted unsigned integer type: {typ}")


def test_mir_parser_reads_numeric_local_ids():
    source = """define ptr @helper(ptr %1) {
entry:
  ret ptr %1
}

define ptr @main(ptr %1) {
entry:
  %2: ptr = call ptr @helper(ptr %1)
  ret ptr %2
}
"""
    program = parse_mir_text(source)
    fn = program.functions[1]
    assert fn.name == "main"
    assert fn.params[0].id == 1
    inst = fn.blocks[0].instructions[0]
    assert inst.result.id == 2
    assert inst.callee == "helper"
    assert fn.text().startswith("define ptr @main(ptr %1)")


def test_mir_parser_rejects_named_local_values():
    source = """define i64 @main(i64 %value) {
entry:
  ret i64 %value
}
"""
    try:
        parse_mir_text(source)
    except Exception as exc:
        assert "local value id must be a positive integer" in str(exc), str(exc)
    else:
        raise AssertionError("MIR parser accepted a named local value")


def test_text_mir_uses_target_neutral_extern_contracts():
    source = """extern void @ExitProcess(i64)

define void @main() {
entry:
  call void ExitProcess(i64 0)
  ret void
}
"""
    program = parse_mir_text(source)
    assert program.externs[0].name == "ExitProcess"
    assert program.text() == source.rstrip()

    for directive in ("import void @ExitProcess(i64)", "declare ptr @__epx_alloc(i64)"):
        try:
            parse_mir_text(directive)
        except Exception as exc:
            assert "expected extern, type, global, or define" in str(exc), str(exc)
        else:
            raise AssertionError(f"text MIR accepted non-canonical directive: {directive}")


def test_undeclared_calls_are_rejected():
    source = """define void @main() {
entry:
  call void ExitProcess(i64 0)
  ret void
}
"""
    try:
        parse_mir_text(source)
    except MirValidationError as exc:
        assert "undeclared callee: ExitProcess" in str(exc), str(exc)
    else:
        raise AssertionError("MIR accepted an undeclared callee")


def test_backend_abi_rejects_unsupported_extern():
    program = parse_mir_text("""extern void @ExitProces(i64)

define void @main() {
entry:
  call void ExitProces(i64 0)
  ret void
}
""")
    try:
        validate_backend_abi(program)
    except BackendAbiError as exc:
        assert "unsupported backend extern: ExitProces" in str(exc), str(exc)
    else:
        raise AssertionError("backend ABI accepted an unsupported extern")


def test_runtime_mir_bundle_declares_external_contracts():
    runtime_mir_dir = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "runtime", "mir"))
    path = runtime_mir_dir / "helpers.mir"
    assert sorted(p.name for p in runtime_mir_dir.glob("*.mir")) == ["helpers.mir"]
    text = path.read_text(encoding="utf-8")
    assert "import " not in text
    assert "declare " not in text
    program = parse_mir_text(text, filename=str(path), validate_program=False)
    assert {ext.name for ext in program.externs} == {
        "ExitProcess", "GetStdHandle", "WriteFile",
        "__ep_print_newline", "__ep_print_str", "__epx_alloc",
    }
    parsed_fn = next(fn for fn in program.functions if fn.name == "__ep_slice_i64_get")
    assert parsed_fn.text() in text


def test_backend_preparation_replaces_runtime_extern_with_definition():
    source = """fun main(): i64 {
    let xs = new i64[] { 10, 20 }
    ret xs[1]
}"""
    typed = sema.analyze_program(Parser(lex(source)).parse_program())
    program = ast_to_mir(typed)

    assert "__ep_slice_i64_get" in {ext.name for ext in program.externs}
    assert "__ep_slice_i64_get" not in {fn.name for fn in program.functions}

    inject_all_mir_helpers(program)
    prune_unreachable_functions(program)
    validate(program)
    validate_backend_abi(program)

    assert "__ep_slice_i64_get" not in {ext.name for ext in program.externs}
    assert "__ep_slice_i64_get" in {fn.name for fn in program.functions}



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
    assert "define i64 @Counter__add(ptr %1, i64 %2)" in text
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

def main():
    test_smoke_text_and_validation()
    test_gep_null_and_ptrtoint_text_and_validation()
    test_validator_rejects_non_positive_local_ids()
    test_validator_rejects_text_sigils_in_module_symbols()
    test_validator_rejects_unknown_and_high_level_ops()
    test_codegen_emits_target_mir_only_for_aggregates()
    test_struct_type_text_round_trip_and_v0_slot_layout()
    test_global_text_round_trip_uses_canonical_bytes_literals()
    test_mir_parser_rejects_unsigned_integer_types()
    test_mir_parser_reads_numeric_local_ids()
    test_mir_parser_rejects_named_local_values()
    test_text_mir_uses_target_neutral_extern_contracts()
    test_undeclared_calls_are_rejected()
    test_backend_abi_rejects_unsupported_extern()
    test_runtime_mir_bundle_declares_external_contracts()
    test_backend_preparation_replaces_runtime_extern_with_definition()
    test_user_method_lowers_to_mangled_function_call()
    test_user_method_conflicts_with_mangled_function_name()
    print("PASS test_mir")


if __name__ == "__main__":
    main()
