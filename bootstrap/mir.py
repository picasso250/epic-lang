"""Epic MIR data model, text printer, and first-pass validator."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MirType:
    kind: str
    pointee: "MirType | None" = None
    count: int | None = None
    elem: "MirType | None" = None
    name: str | None = None

    def __str__(self):
        if self.kind == "ptr":
            return f"ptr {self.pointee}"
        if self.kind == "array":
            return f"array {self.count} x {self.elem}"
        if self.kind == "struct":
            return f"struct {self.name}"
        return self.kind


I64 = MirType("i64")
U64 = MirType("u64")
I8 = MirType("i8")
U8 = MirType("u8")
BOOL = MirType("bool")
VOID = MirType("void")


def ptr(pointee):
    return MirType("ptr", pointee=pointee)


def array(count, elem):
    return MirType("array", count=count, elem=elem)


def struct(name):
    return MirType("struct", name=name)


@dataclass(frozen=True)
class MirSignature:
    params: list[MirType]
    ret: MirType

    def __str__(self):
        return f"fn({', '.join(str(p) for p in self.params)}) -> {self.ret}"


@dataclass(frozen=True)
class MirValue:
    name: str
    type: MirType

    def __str__(self):
        return self.name


@dataclass(frozen=True)
class MirOperand:
    type: MirType

    def text(self):
        raise NotImplementedError

    def typed_text(self):
        return f"{self.type} {self.text()}"


@dataclass(frozen=True)
class ValueOperand(MirOperand):
    value: MirValue

    def __init__(self, value):
        object.__setattr__(self, "type", value.type)
        object.__setattr__(self, "value", value)

    def text(self):
        return self.value.name


@dataclass(frozen=True)
class ConstIntOperand(MirOperand):
    value: int

    def text(self):
        return str(self.value)


@dataclass(frozen=True)
class ConstBoolOperand(MirOperand):
    value: bool

    def __init__(self, value):
        object.__setattr__(self, "type", BOOL)
        object.__setattr__(self, "value", value)

    def text(self):
        return "true" if self.value else "false"


@dataclass(frozen=True)
class SymbolOperand(MirOperand):
    name: str

    def text(self):
        return self.name


@dataclass
class MirImport:
    name: str
    signature: MirSignature
    dll: str | None = None

    def text(self):
        return f"import {self.name}: {self.signature}"


@dataclass
class MirGlobal:
    name: str
    type: MirType
    init: str

    def text(self):
        return f"{self.name}: {self.type} = global {self.init}"


@dataclass
class MirParam:
    name: str
    type: MirType

    @property
    def value(self):
        return MirValue(self.name, self.type)

    def text(self):
        return f"{self.type} {self.name}"


@dataclass
class MirInst:
    op: str
    operands: list[MirOperand] = field(default_factory=list)
    result: MirValue | None = None
    type: MirType | None = None
    callee: str | None = None

    def text(self):
        prefix = ""
        if self.result is not None:
            prefix = f"{self.result.name}: {self.result.type} = "
        if self.op == "alloca":
            return f"{prefix}alloca {self.type}"
        if self.op == "load":
            addr = self.operands[0]
            return f"{prefix}load {self.type}, {addr.typed_text()}"
        if self.op == "store":
            value, addr = self.operands
            return f"store {value.typed_text()}, {addr.typed_text()}"
        if self.op == "call":
            args = ", ".join(op.typed_text() for op in self.operands)
            call = f"call {self.type} {self.callee}({args})"
            return f"{prefix}{call}"
        if self.op == "const":
            return f"{prefix}const {self.operands[0].typed_text()}"
        if self.op == "not":
            return f"{prefix}not {self.operands[0].typed_text()}"
        if self.op == "gep":
            base, offset = self.operands
            return f"{prefix}gep {base.typed_text()}, {offset.typed_text()}"
        rendered = ", ".join(op.typed_text() for op in self.operands)
        return f"{prefix}{self.op} {rendered}"


@dataclass(frozen=True)
class Br:
    target: str

    def text(self):
        return f"br label %{self.target}"


@dataclass(frozen=True)
class CondBr:
    cond: MirOperand
    then_target: str
    else_target: str

    def text(self):
        return (
            f"condbr {self.cond.typed_text()}, "
            f"label %{self.then_target}, label %{self.else_target}"
        )


@dataclass(frozen=True)
class Ret:
    value: MirOperand | None = None

    def text(self):
        if self.value is None:
            return "ret void"
        return f"ret {self.value.typed_text()}"


@dataclass
class MirBlock:
    name: str
    instructions: list[MirInst] = field(default_factory=list)
    terminator: Br | CondBr | Ret | None = None

    def text(self):
        lines = [f"{self.name}:"]
        for inst in self.instructions:
            lines.append(f"  {inst.text()}")
        if self.terminator is not None:
            lines.append(f"  {self.terminator.text()}")
        return "\n".join(lines)


@dataclass
class MirFunction:
    name: str
    params: list[MirParam]
    return_type: MirType
    blocks: list[MirBlock] = field(default_factory=list)

    @property
    def signature(self):
        return MirSignature([p.type for p in self.params], self.return_type)

    def text(self):
        params = ", ".join(p.text() for p in self.params)
        body = "\n\n".join(block.text() for block in self.blocks)
        return f"fn {self.name}({params}) -> {self.return_type} {{\n{body}\n}}"


@dataclass
class MirProgram:
    imports: list[MirImport] = field(default_factory=list)
    globals: list[MirGlobal] = field(default_factory=list)
    functions: list[MirFunction] = field(default_factory=list)

    def text(self):
        parts = []
        parts.extend(imp.text() for imp in self.imports)
        parts.extend(glob.text() for glob in self.globals)
        parts.extend(fn.text() for fn in self.functions)
        return "\n\n".join(parts)


class MirValidationError(Exception):
    pass


class MirValidator:
    def __init__(self, program):
        self.program = program
        self.errors = []
        self.symbols = {}

    def validate(self):
        self._collect_symbols()
        for fn in self.program.functions:
            self._validate_function(fn)
        if self.errors:
            raise MirValidationError("\n".join(self.errors))

    def _collect_symbols(self):
        for item in [*self.program.imports, *self.program.globals, *self.program.functions]:
            if item.name in self.symbols:
                self.errors.append(f"duplicate module symbol: {item.name}")
            self.symbols[item.name] = item

    def _validate_function(self, fn):
        if not fn.blocks:
            self.errors.append(f"{fn.name}: function has no blocks")
            return
        blocks = {}
        for block in fn.blocks:
            if block.name in blocks:
                self.errors.append(f"{fn.name}: duplicate block: {block.name}")
            blocks[block.name] = block
            if block.terminator is None:
                self.errors.append(f"{fn.name}.{block.name}: missing terminator")

        values = {}
        for param in fn.params:
            self._define(values, fn, "param", param.value)

        for block in fn.blocks:
            for inst in block.instructions:
                self._validate_inst(fn, block, inst, values)
                if inst.result is not None:
                    self._define(values, fn, block.name, inst.result)
            self._validate_terminator(fn, block, block.terminator, values, blocks)

    def _define(self, values, fn, where, value):
        if value.name in values:
            self.errors.append(f"{fn.name}.{where}: duplicate value: {value.name}")
        values[value.name] = value.type

    def _check_operand(self, fn, where, operand, values):
        if isinstance(operand, ValueOperand):
            name = operand.value.name
            if name not in values:
                self.errors.append(f"{fn.name}.{where}: undefined value: {name}")
            elif values[name] != operand.type:
                self.errors.append(f"{fn.name}.{where}: stale value type for {name}")
        if isinstance(operand, SymbolOperand) and operand.name not in self.symbols:
            self.errors.append(f"{fn.name}.{where}: undefined symbol: {operand.name}")

    def _validate_inst(self, fn, block, inst, values):
        where = block.name
        for operand in inst.operands:
            self._check_operand(fn, where, operand, values)

        if inst.op == "alloca":
            self._require(inst.result is not None, fn, where, "alloca needs a result")
            self._require(inst.type is not None, fn, where, "alloca needs an element type")
            if inst.result is not None and inst.type is not None:
                self._require(
                    inst.result.type == ptr(inst.type),
                    fn,
                    where,
                    "alloca result must be ptr element type",
                )
        elif inst.op == "load":
            self._require(len(inst.operands) == 1, fn, where, "load needs one operand")
            self._require(inst.result is not None, fn, where, "load needs a result")
            if inst.operands:
                self._require(inst.operands[0].type == ptr(inst.type), fn, where, "load type mismatch")
            if inst.result is not None:
                self._require(inst.result.type == inst.type, fn, where, "load result type mismatch")
        elif inst.op == "store":
            self._require(len(inst.operands) == 2, fn, where, "store needs two operands")
            self._require(inst.result is None, fn, where, "store must not have a result")
            if len(inst.operands) == 2:
                value, addr = inst.operands
                self._require(addr.type == ptr(value.type), fn, where, "store type mismatch")
        elif inst.op in ("add", "sub", "mul", "div", "mod", "and", "or"):
            self._require(len(inst.operands) == 2, fn, where, f"{inst.op} needs two operands")
            self._validate_same_typed_result(fn, where, inst)
        elif inst.op == "not":
            self._require(len(inst.operands) == 1, fn, where, "not needs one operand")
            self._require(inst.result is not None and inst.result.type == BOOL, fn, where, "not returns bool")
            if inst.operands:
                self._require(inst.operands[0].type == BOOL, fn, where, "not operand must be bool")
        elif inst.op.startswith("icmp."):
            self._require(len(inst.operands) == 2, fn, where, f"{inst.op} needs two operands")
            if len(inst.operands) == 2:
                self._require(inst.operands[0].type == inst.operands[1].type, fn, where, "icmp type mismatch")
            self._require(inst.result is not None and inst.result.type == BOOL, fn, where, "icmp returns bool")
        elif inst.op == "call":
            self._validate_call(fn, where, inst)

    def _validate_same_typed_result(self, fn, where, inst):
        if len(inst.operands) == 2:
            self._require(inst.operands[0].type == inst.operands[1].type, fn, where, f"{inst.op} type mismatch")
        self._require(inst.result is not None, fn, where, f"{inst.op} needs a result")
        if inst.result is not None and inst.operands:
            self._require(inst.result.type == inst.operands[0].type, fn, where, f"{inst.op} result type mismatch")

    def _validate_call(self, fn, where, inst):
        self._require(inst.callee is not None, fn, where, "call needs callee")
        self._require(inst.type is not None, fn, where, "call needs return type")
        callee = self.symbols.get(inst.callee)
        signature = getattr(callee, "signature", None)
        if signature is None:
            self.errors.append(f"{fn.name}.{where}: callee is not callable: {inst.callee}")
            return
        self._require(signature.ret == inst.type, fn, where, "call return type mismatch")
        self._require(len(signature.params) == len(inst.operands), fn, where, "call arity mismatch")
        for idx, (expected, operand) in enumerate(zip(signature.params, inst.operands)):
            self._require(expected == operand.type, fn, where, f"call argument {idx} type mismatch")
        if inst.type == VOID:
            self._require(inst.result is None, fn, where, "void call must not have a result")
        else:
            self._require(inst.result is not None and inst.result.type == inst.type, fn, where, "call result type mismatch")

    def _validate_terminator(self, fn, block, term, values, blocks):
        if term is None:
            return
        where = block.name
        if isinstance(term, Br):
            self._check_label(fn, where, term.target, blocks)
        elif isinstance(term, CondBr):
            self._check_operand(fn, where, term.cond, values)
            self._require(term.cond.type == BOOL, fn, where, "condbr condition must be bool")
            self._check_label(fn, where, term.then_target, blocks)
            self._check_label(fn, where, term.else_target, blocks)
        elif isinstance(term, Ret):
            if fn.return_type == VOID:
                self._require(term.value is None, fn, where, "void function must return void")
            else:
                self._require(term.value is not None, fn, where, "non-void function must return a value")
                if term.value is not None:
                    self._check_operand(fn, where, term.value, values)
                    self._require(term.value.type == fn.return_type, fn, where, "return type mismatch")

    def _check_label(self, fn, where, label, blocks):
        if label not in blocks:
            self.errors.append(f"{fn.name}.{where}: undefined label: %{label}")

    def _require(self, condition, fn, where, message):
        if not condition:
            self.errors.append(f"{fn.name}.{where}: {message}")


def validate(program):
    MirValidator(program).validate()
