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
            return "ptr"
        if self.kind == "array":
            return f"array {self.count} x {self.elem}"
        if self.kind == "struct":
            return f"struct {self.name}"
        return self.kind


I64 = MirType("i64")
U64 = MirType("u64")
I32 = MirType("i32")
I8 = MirType("i8")
U8 = MirType("u8")
BOOL = MirType("bool")
VOID = MirType("void")
PTR = MirType("ptr")


def ptr(pointee=None):
    """Return the single opaque MIR pointer type.

    The optional pointee parameter is accepted during the migration so existing
    callers can keep spelling layout/access intent nearby, but MIR pointer
    values themselves never carry pointee type information.
    """
    return PTR


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
class ConstNullOperand(MirOperand):
    def __init__(self):
        object.__setattr__(self, "type", PTR)

    def text(self):
        return "null"


@dataclass(frozen=True)
class SymbolOperand(MirOperand):
    name: str

    def __init__(self, type, name):
        object.__setattr__(self, "type", type)
        object.__setattr__(self, "name", name)

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
class MirExtern:
    name: str
    signature: MirSignature

    def text(self):
        return f"extern {self.name}: {self.signature}"


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
            base = self.operands[0]
            indices = ", ".join(op.typed_text() for op in self.operands[1:])
            suffix = f", {indices}" if indices else ""
            return f"{prefix}gep {self.type}, {base.typed_text()}{suffix}"
        if self.op == "ptrtoint":
            target = self.type if self.type is not None else self.result.type
            return f"{prefix}ptrtoint {self.operands[0].typed_text()} to {target}"
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


@dataclass(frozen=True)
class MirField:
    name: str
    type: MirType
    offset: int


@dataclass(frozen=True)
class MirStruct:
    name: str
    fields: list[MirField] = field(default_factory=list)
    size: int = 0

    def field(self, name):
        for field_item in self.fields:
            if field_item.name == name:
                return field_item
        raise KeyError(name)

    def field_index(self, name):
        for idx, field_item in enumerate(self.fields):
            if field_item.name == name:
                return idx
        raise KeyError(name)

    def field_by_index(self, index):
        return self.fields[index]


@dataclass
class MirProgram:
    imports: list[MirImport] = field(default_factory=list)
    externs: list[MirExtern] = field(default_factory=list)
    globals: list[MirGlobal] = field(default_factory=list)
    functions: list[MirFunction] = field(default_factory=list)
    structs: dict[str, MirStruct] = field(default_factory=dict)

    def text(self):
        parts = []
        parts.extend(imp.text() for imp in self.imports)
        parts.extend(ext.text() for ext in self.externs)
        parts.extend(glob.text() for glob in self.globals)
        parts.extend(fn.text() for fn in self.functions)
        return "\n\n".join(parts)


class MirValidationError(Exception):
    pass


class MirValidator:
    HIGH_LEVEL_OPS = {
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
    }

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
        for item in [*self.program.imports, *self.program.externs, *self.program.globals, *self.program.functions]:
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

        if inst.op in self.HIGH_LEVEL_OPS:
            self.errors.append(f"{fn.name}.{where}: high-level MIR op is not allowed: {inst.op}")
        elif inst.op == "alloca":
            self._require(inst.result is not None, fn, where, "alloca needs a result")
            self._require(inst.type is not None, fn, where, "alloca needs an element type")
            if inst.result is not None and inst.type is not None:
                self._require(
                    self._is_ptr(inst.result.type),
                    fn,
                    where,
                    "alloca result must be ptr",
                )
        elif inst.op == "load":
            self._require(len(inst.operands) == 1, fn, where, "load needs one operand")
            self._require(inst.result is not None, fn, where, "load needs a result")
            self._require(inst.type is not None, fn, where, "load needs an access type")
            if inst.operands:
                self._require(self._is_ptr(inst.operands[0].type), fn, where, "load address must be ptr")
            if inst.result is not None:
                self._require(
                    self._same_type(inst.result.type, inst.type) or (inst.type == I8 and inst.result.type == I64),
                    fn,
                    where,
                    "load result type mismatch",
                )
        elif inst.op == "store":
            self._require(len(inst.operands) == 2, fn, where, "store needs two operands")
            self._require(inst.result is None, fn, where, "store must not have a result")
            if len(inst.operands) == 2:
                value, addr = inst.operands
                self._require(self._is_ptr(addr.type), fn, where, "store address must be ptr")
        elif inst.op in ("add", "sub", "mul", "sdiv", "udiv", "srem", "urem", "and", "or", "xor", "shl", "sar", "shr"):
            self._require(len(inst.operands) == 2, fn, where, f"{inst.op} needs two operands")
            self._validate_same_typed_result(fn, where, inst)
        elif inst.op == "not":
            self._require(len(inst.operands) == 1, fn, where, "not needs one operand")
            self._require(inst.result is not None and inst.result.type == BOOL, fn, where, "not returns bool")
            if inst.operands:
                self._require(inst.operands[0].type == BOOL, fn, where, "not operand must be bool")
        elif inst.op.startswith("icmp."):
            pred = inst.op[5:]
            valid_preds = {"eq", "ne", "slt", "sle", "sgt", "sge", "ult", "ule", "ugt", "uge"}
            self._require(pred in valid_preds, fn, where, f"unsupported icmp predicate: {pred}")
            self._require(len(inst.operands) == 2, fn, where, f"{inst.op} needs two operands")
            if len(inst.operands) == 2:
                self._require(inst.operands[0].type == inst.operands[1].type, fn, where, "icmp type mismatch")
            self._require(inst.result is not None and inst.result.type == BOOL, fn, where, "icmp returns bool")
        elif inst.op == "call":
            self._validate_call(fn, where, inst)
        elif inst.op == "gep":
            self._validate_gep(fn, where, inst)
        elif inst.op == "ptrtoint":
            self._require(len(inst.operands) == 1, fn, where, "ptrtoint needs one operand")
            self._require(inst.result is not None, fn, where, "ptrtoint needs a result")
            self._require(inst.type == I64, fn, where, "ptrtoint target must be i64")
            if inst.operands:
                self._require(self._is_ptr(inst.operands[0].type), fn, where, "ptrtoint operand must be ptr")
            if inst.result is not None:
                self._require(inst.result.type == I64, fn, where, "ptrtoint result type mismatch")
        else:
            self.errors.append(f"{fn.name}.{where}: unknown MIR op: {inst.op}")

    def _validate_same_typed_result(self, fn, where, inst):
        if len(inst.operands) == 2:
            self._require(self._same_type(inst.operands[0].type, inst.operands[1].type), fn, where, f"{inst.op} type mismatch")
        self._require(inst.result is not None, fn, where, f"{inst.op} needs a result")
        if inst.result is not None and inst.operands:
            self._require(self._same_type(inst.result.type, inst.operands[0].type), fn, where, f"{inst.op} result type mismatch")

    def _validate_call(self, fn, where, inst):
        self._require(inst.callee is not None, fn, where, "call needs callee")
        self._require(inst.type is not None, fn, where, "call needs return type")
        callee = self.symbols.get(inst.callee)
        signature = getattr(callee, "signature", None)
        if signature is None:
            self.errors.append(f"{fn.name}.{where}: callee is not callable: {inst.callee}")
            return
        self._require(self._same_type(signature.ret, inst.type), fn, where, "call return type mismatch")
        self._require(len(signature.params) == len(inst.operands), fn, where, "call arity mismatch")
        for idx, (expected, operand) in enumerate(zip(signature.params, inst.operands)):
            self._require(self._same_type(expected, operand.type), fn, where, f"call argument {idx} type mismatch")
        if inst.type == VOID:
            self._require(inst.result is None, fn, where, "void call must not have a result")
        else:
            self._require(inst.result is not None and self._same_type(inst.result.type, inst.type), fn, where, "call result type mismatch")

    def _validate_gep(self, fn, where, inst):
        self._require(inst.result is not None, fn, where, "gep needs a result")
        self._require(inst.type is not None, fn, where, "gep needs a source type")
        if inst.result is not None:
            self._require(self._is_ptr(inst.result.type), fn, where, "gep result must be ptr")
        self._require(len(inst.operands) >= 2, fn, where, "gep needs base and at least one index")
        if not inst.operands:
            return
        self._require(self._is_ptr(inst.operands[0].type), fn, where, "gep base must be ptr")
        for operand in inst.operands[1:]:
            self._require(operand.type in (I64, I32), fn, where, "gep indices must be integer")
        if inst.type is None:
            return
        if inst.type.kind == "struct":
            if len(inst.operands) == 2:
                return
            self._require(len(inst.operands) == 3, fn, where, "struct gep needs one or two indices")
            field_index = inst.operands[2]
            if isinstance(field_index, ConstIntOperand):
                struct_layout = self.program.structs.get(inst.type.name)
                field_count = len(struct_layout.fields) if struct_layout is not None else 0
                self._require(0 <= field_index.value < field_count, fn, where, f"unknown struct field index: {inst.type.name}.{field_index.value}")
            return
        self._require(inst.type.kind in {"i64", "i8", "ptr", "array"}, fn, where, f"unsupported gep source type: {inst.type}")

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
                    self._require(self._same_type(term.value.type, fn.return_type), fn, where, "return type mismatch")

    def _check_label(self, fn, where, label, blocks):
        if label not in blocks:
            self.errors.append(f"{fn.name}.{where}: undefined label: %{label}")

    def _require(self, condition, fn, where, message):
        if not condition:
            self.errors.append(f"{fn.name}.{where}: {message}")

    def _is_ptr(self, typ):
        return typ is not None and typ.kind == "ptr"

    def _same_type(self, left, right):
        if left is None or right is None:
            return left == right
        if self._is_ptr(left) and self._is_ptr(right):
            return True
        return left == right


def validate(program):
    MirValidator(program).validate()
