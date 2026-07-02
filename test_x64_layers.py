#!/usr/bin/env python3
"""Layered golden tests for Epic's X64IR and machine backend."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "bootstrap"))

from machine import MachineObjectBuilder
from mir import I64, ConstIntOperand, MirBlock, MirFunction, MirInst, MirParam
from mir import MirProgram, MirValue, Ret, ValueOperand
from mir_lower import MirLower
from x64 import I, M, MS, R, LabelRef, Symbol, X64Program


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
    param = MirParam("%x", I64)
    result = MirValue("%r", I64)
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
    sub rsp, 112
    mov qword [rbp-8], rcx
add1.entry:
    mov rax, qword [rbp-8]
    mov rcx, 1
    add rax, rcx
    mov qword [rbp-16], rax
    mov rax, qword [rbp-16]
    jmp add1.__return
add1.__return:
    add rsp, 112
    pop rbp
    ret
"""
    assert lower.x64.text() == expected


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


def main():
    test_x64_pretty_print_golden()
    test_mir_function_to_x64_golden()
    test_x64_to_machine_bytes_and_fixups_golden()
    print("PASS test_x64_layers")


if __name__ == "__main__":
    main()

