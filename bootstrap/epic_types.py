"""Epic frontend type model shared by sema, AST annotations, and codegen."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EpicType:
    kind: str
    elem: "EpicType | None" = None
    name: str = ""

    def __str__(self):
        if self.kind == "array":
            return f"{self.elem}[]"
        if self.kind == "ptr":
            return f"&{self.elem}"
        if self.kind == "named":
            return self.name
        return self.kind


I64 = EpicType("i64")
U64 = EpicType("u64")
I8 = EpicType("i8")
U8 = EpicType("u8")
BOOL = EpicType("bool")
VOID = EpicType("void")
STR = EpicType("str")


def ARRAY(elem):
    return EpicType("array", elem=elem)


def PTR(elem):
    return EpicType("ptr", elem=elem)


def NAMED(name):
    return EpicType("named", name=name)
