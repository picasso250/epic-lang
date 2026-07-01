#!/usr/bin/env python3
"""Smoke tests for the Python MIR prototype."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "bootstrap"))

from mir import BOOL, I64, Br, CondBr, MirBlock, MirFunction, MirInst, MirParam
from mir import MirProgram, MirValue, Ret, ValueOperand, ConstIntOperand, validate, ptr


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
  %x.addr: ptr i64 = alloca i64
  store i64 0, ptr i64 %x.addr
  br label %loop

loop:
  %x0: i64 = load i64, ptr i64 %x.addr
  %c0: bool = icmp.lt i64 %x0, i64 3
  condbr bool %c0, label %body, label %done

body:
  %x1: i64 = add i64 %x0, i64 1
  store i64 %x1, ptr i64 %x.addr
  br label %loop

done:
  %r: i64 = load i64, ptr i64 %x.addr
  ret i64 %r
}"""
    assert program.text() == expected


def main():
    test_smoke_text_and_validation()
    print("PASS test_smoke_text_and_validation")


if __name__ == "__main__":
    main()
