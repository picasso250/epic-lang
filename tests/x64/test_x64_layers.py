#!/usr/bin/env python3
"""Layered golden tests for Epic's X64IR and machine backend."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "bootstrap"))

from machine import MachineObjectBuilder
from mir import I64, ConstIntOperand, ConstNullOperand, MirBlock, MirExtern, MirField
from mir import MirFunction, MirInst, MirParam, MirProgram, MirSignature, MirStruct
from mir import MirValue, Ret, ValueOperand, ptr, struct as mir_struct
from mir_to_x64 import MirLower
from x64 import I, M, MS, R, LabelRef, Symbol, X64Program
from x64 import X64ValidationError, validate_x64_program
from x64_runtime import append_runtime_helpers, emit_startup_hook_call


def build_x64_fixture():
    program = X64Program()
    program.global_("_start")
    program.extern("ExitProcess")
    program.section(".data")
    program.data_bytes("msg", [65, 0])
    program.data_zero("scratch", 8)
    program.section(".text")
    program.label("_start")
    program.inst("mov", R("rax"), I(1))
    program.inst("cmp", R("rax"), I(1))
    program.inst("jz", LabelRef("done"))
    program.inst("mov", R("rax"), I(2))
    program.label("done")
    program.inst("lea", R("rdx"), MS("msg"))
    program.inst("mov", R("rcx"), R("rax"))
    program.inst("call", Symbol("ExitProcess"))
    program.inst("ret")
    return program


def build_machine_state(program):
    builder = MachineObjectBuilder(program)
    builder._emit_program()
    builder._patch_internal_fixups()
    return builder


def assert_x64_invalid(program, message):
    try:
        validate_x64_program(program)
    except X64ValidationError as e:
        assert message in str(e), str(e)
        return
    raise AssertionError("expected X64ValidationError")


def test_x64_pretty_print_golden():
    expected = """global _start
extern ExitProcess
section .data
msg: db 65, 0
scratch: times 8 db 0
section .text
_start:
    mov rax, 1
    cmp rax, 1
    jz done
    mov rax, 2
done:
    lea rdx, qword [msg]
    mov rcx, rax
    call ExitProcess
    ret
"""
    assert build_x64_fixture().text() == expected


def test_mir_function_to_x64_golden():
    param = MirParam(1, I64)
    result = MirValue(2, I64)
    block = MirBlock(
        "entry",
        [
            MirInst(
                "add",
                [ValueOperand(param.value), ConstIntOperand(I64, 1)],
                result=result,
            )
        ],
        Ret(ValueOperand(result)),
    )
    fn = MirFunction("add1", [param], I64, [block])
    lower = MirLower(MirProgram(functions=[fn]))
    lower.x64.section(".text")
    lower._lower_function(fn)

    expected = """section .text
add1:
    push rbp
    mov rbp, rsp
    sub rsp, 80
    mov qword [rbp-8], rcx
add1.entry:
    mov rax, qword [rbp-8]
    mov rcx, 1
    add rax, rcx
    mov qword [rbp-16], rax
    mov rax, qword [rbp-16]
    jmp add1.__return
add1.__return:
    add rsp, 80
    pop rbp
    ret
"""
    assert lower.x64.text() == expected


def test_target_mir_memory_ops_to_x64_golden():
    size_ptr = MirValue(1, ptr())
    size = MirValue(2, I64)
    obj = MirValue(3, ptr())
    field_ptr = MirValue(4, ptr())
    loaded = MirValue(5, I64)
    block = MirBlock(
        "entry",
        [
            MirInst("gep", [ConstNullOperand(), ConstIntOperand(I64, 1)], result=size_ptr, type=mir_struct("Pair")),
            MirInst("ptrtoint", [ValueOperand(size_ptr)], result=size, type=I64),
            MirInst("call", [ValueOperand(size)], result=obj, type=ptr(), callee="__epx_alloc"),
            MirInst(
                "gep",
                [ValueOperand(obj), ConstIntOperand(I64, 0), ConstIntOperand(I64, 1)],
                result=field_ptr,
                type=mir_struct("Pair"),
            ),
            MirInst("store", [ConstIntOperand(I64, 42), ValueOperand(field_ptr)]),
            MirInst("load", [ValueOperand(field_ptr)], result=loaded, type=I64),
        ],
        Ret(ValueOperand(loaded)),
    )
    fn = MirFunction("pair_field", [], I64, [block])
    program = MirProgram(
        externs=[MirExtern("__epx_alloc", MirSignature([I64], ptr()))],
        functions=[fn],
        structs={"Pair": MirStruct("Pair", [MirField("left", I64, 0), MirField("right", I64, 8)], 16)},
    )
    lower = MirLower(program)
    lower.x64.section(".text")
    lower._lower_function(fn)

    expected = """section .text
pair_field:
    push rbp
    mov rbp, rsp
    sub rsp, 80
pair_field.entry:
    mov rax, 0
    add rax, 16
    mov qword [rbp-8], rax
    mov rax, qword [rbp-8]
    mov qword [rbp-8], rax
    mov rcx, qword [rbp-8]
    sub rsp, 32
    call __epx_alloc
    add rsp, 32
    mov qword [rbp-8], rax
    mov rax, qword [rbp-8]
    test rax, rax
    jz __epx_null_deref
    add rax, 8
    mov qword [rbp-8], rax
    mov rax, 42
    mov rcx, qword [rbp-8]
    test rcx, rcx
    jz __epx_null_deref
    mov qword [rcx], rax
    mov rax, qword [rbp-8]
    test rax, rax
    jz __epx_null_deref
    mov rax, qword [rax]
    mov qword [rbp-8], rax
    mov rax, qword [rbp-8]
    jmp pair_field.__return
pair_field.__return:
    add rsp, 80
    pop rbp
    ret
"""
    assert lower.x64.text() == expected


def test_startup_hook_call_golden():
    program = X64Program()
    program.section(".text")
    emit_startup_hook_call(program)
    expected = """section .text
    sub rsp, 32
    call __epx_runtime_start
    add rsp, 32
"""
    assert program.text() == expected


def test_runtime_start_helper_golden():
    program = X64Program()
    program.section(".text")
    append_runtime_helpers(program)
    expected = """section .text
__epx_runtime_start:
    push rbp
    mov rbp, rsp
    sub rsp, 32
    call GetProcessHeap
    add rsp, 32
    mov qword [_heap], rax
    sub rsp, 32
    call __epx_argv_init
    add rsp, 32
    mov qword [_argv], rax
    pop rbp
    ret
"""
    text = program.text()
    assert text.startswith(expected)
    assert "__ep_cstr:\n" in text
    assert "__epx_cstr" not in text


def test_x64_to_machine_bytes_and_fixups_golden():
    builder = build_machine_state(build_x64_fixture())

    assert builder.text.hex(" ") == (
        "48 c7 c0 01 00 00 00 "
        "48 83 f8 01 "
        "0f 84 07 00 00 00 "
        "48 c7 c0 02 00 00 00 "
        "48 8d 15 00 00 00 00 "
        "48 89 c1 "
        "e8 00 00 00 00 "
        "c3"
    )
    assert builder.data.hex(" ") == "41 00 00 00 00 00 00 00 00 00"
    assert builder.text_labels == {"_start": 0, "done": 24}
    assert builder.data_labels == {"msg": 0, "scratch": 2}
    assert builder.internal_fixups == [(13, "done")]
    assert builder.text_relocs == [(27, "msg"), (35, "ExitProcess")]


def test_x64_validator_rejects_bad_forms():
    validate_x64_program(build_x64_fixture())

    program = X64Program()
    program.section(".text")
    program.inst("test", R("rax"), R("rcx"))
    assert_x64_invalid(program, "test requires identical operands")

    program = X64Program()
    program.section(".text")
    program.inst("add", R("rax"), I(128))
    assert_x64_invalid(program, "signed imm8")

    program = X64Program()
    program.section(".text")
    program.inst("call", Symbol("Missing"))
    assert_x64_invalid(program, "undefined symbol: Missing")


def main():
    test_x64_pretty_print_golden()
    test_mir_function_to_x64_golden()
    test_target_mir_memory_ops_to_x64_golden()
    test_startup_hook_call_golden()
    test_runtime_start_helper_golden()
    test_x64_to_machine_bytes_and_fixups_golden()
    test_x64_validator_rejects_bad_forms()
    print("PASS test_x64_layers")


if __name__ == "__main__":
    main()
