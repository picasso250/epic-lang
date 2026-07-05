"""Structured X64/MachineIR for Epic's machine backend."""

from dataclasses import dataclass, field


REG64 = {
    "rax",
    "rcx",
    "rdx",
    "rbx",
    "rsp",
    "rbp",
    "rsi",
    "rdi",
    "r8",
    "r9",
    "r10",
    "r11",
}
REG32_MOV_IMM = {"eax", "ecx", "edx"}
REG8 = {"al", "cl", "dl", "r8b", "r9b", "r10b", "r11b"}
JUMPS = {"jmp", "jo", "jz", "jnz", "jl", "jge", "jle", "jg", "jns"}
SETCC = {"sete", "setne", "setg", "setl", "setge", "setle", "seta", "setae", "setb", "setbe"}
ALU_REG_REG = {"add", "sub", "and", "or", "xor"}
SHIFT_OPS = {"shl", "sar", "shr"}
SUPPORTED_SECTIONS = {".text", ".data"}


@dataclass(frozen=True)
class Reg:
    name: str

    def text(self):
        return self.name


@dataclass(frozen=True)
class Imm:
    value: int

    def text(self):
        return str(self.value)


@dataclass(frozen=True)
class Symbol:
    name: str

    def text(self):
        return self.name


@dataclass(frozen=True)
class LabelRef:
    name: str

    def text(self):
        return self.name


@dataclass(frozen=True)
class Mem:
    base: Reg | None = None
    disp: int = 0
    symbol: str | None = None
    size: int = 8

    def text(self):
        prefix = "byte " if self.size == 1 else "qword " if self.size == 8 else ""
        if self.symbol is not None:
            return f"{prefix}[{self.symbol}]"
        if self.disp == 0:
            return f"{prefix}[{self.base.text()}]"
        sign = "+" if self.disp >= 0 else ""
        return f"{prefix}[{self.base.text()}{sign}{self.disp}]"


@dataclass(frozen=True)
class X64Global:
    name: str

    def lines(self):
        return [f"global {self.name}"]


@dataclass(frozen=True)
class X64Extern:
    name: str

    def lines(self):
        return [f"extern {self.name}"]


@dataclass(frozen=True)
class X64Section:
    name: str

    def lines(self):
        return [f"section {self.name}"]


@dataclass(frozen=True)
class X64Label:
    name: str

    def lines(self):
        return [f"{self.name}:"]


@dataclass(frozen=True)
class X64Inst:
    op: str
    operands: tuple = ()

    def lines(self):
        if self.operands:
            return [f"    {self.op} " + ", ".join(op.text() for op in self.operands)]
        return [f"    {self.op}"]


@dataclass(frozen=True)
class X64DataBytes:
    label: str
    values: list[int]

    def lines(self):
        return [f"{self.label}: db {', '.join(str(v) for v in self.values)}"]


@dataclass(frozen=True)
class X64DataZero:
    label: str
    count: int

    def lines(self):
        return [f"{self.label}: times {self.count} db 0"]


@dataclass
class X64Program:
    items: list = field(default_factory=list)

    def global_(self, name):
        self.items.append(X64Global(name))

    def extern(self, name):
        self.items.append(X64Extern(name))

    def section(self, name):
        self.items.append(X64Section(name))

    def label(self, name):
        self.items.append(X64Label(name))

    def inst(self, op, *operands):
        self.items.append(X64Inst(op, tuple(operands)))

    def data_bytes(self, label, values):
        self.items.append(X64DataBytes(label, values))

    def data_zero(self, label, count):
        self.items.append(X64DataZero(label, count))

    def text(self):
        lines = []
        for item in self.items:
            lines.extend(item.lines())
        return "\n".join(lines) + "\n"


class X64ValidationError(RuntimeError):
    pass


class X64Validator:
    def __init__(self, program):
        self.program = program
        self.errors = []
        self.externs = set()
        self.globals = set()
        self.text_labels = set()
        self.data_labels = set()
        self.defined_symbols = set()
        self.declared_symbols = set()
        self.section = None

    def validate(self):
        self._collect_symbols()
        self._validate_items()
        if self.errors:
            raise X64ValidationError("\n".join(self.errors))

    def _collect_symbols(self):
        section = None
        for idx, item in enumerate(self.program.items):
            if isinstance(item, X64Section):
                section = item.name
            elif isinstance(item, X64Extern):
                self._add_decl(self.externs, item.name, "extern", idx)
            elif isinstance(item, X64Global):
                self._add_decl(self.globals, item.name, "global", idx)
            elif isinstance(item, X64Label):
                if section == ".text":
                    self._define_symbol(item.name, self.text_labels, "text label", idx)
                elif section == ".data":
                    self._define_symbol(item.name, self.data_labels, "data label", idx)
            elif isinstance(item, (X64DataBytes, X64DataZero)) and section == ".data":
                self._define_symbol(item.label, self.data_labels, "data label", idx)

        self.defined_symbols = self.text_labels | self.data_labels
        self.declared_symbols = self.defined_symbols | self.externs
        for name in sorted(self.externs & self.defined_symbols):
            self.errors.append(f"extern also defined: {name}")
        for name in sorted(self.globals - self.defined_symbols):
            self.errors.append(f"global has no matching label: {name}")

    def _add_decl(self, target, name, kind, idx):
        if name in target:
            self.errors.append(f"item {idx}: duplicate {kind}: {name}")
        target.add(name)

    def _define_symbol(self, name, section_symbols, kind, idx):
        if name in self.defined_symbols or name in self.text_labels or name in self.data_labels:
            self.errors.append(f"item {idx}: duplicate symbol: {name}")
        section_symbols.add(name)

    def _validate_items(self):
        self.section = None
        for idx, item in enumerate(self.program.items):
            if isinstance(item, (X64Global, X64Extern)):
                self._require_name(item.name, idx, type(item).__name__)
            elif isinstance(item, X64Section):
                self._validate_section(item, idx)
            elif isinstance(item, X64Label):
                self._validate_label(item, idx)
            elif isinstance(item, X64Inst):
                self._validate_inst(item, idx)
            elif isinstance(item, X64DataBytes):
                self._validate_data_bytes(item, idx)
            elif isinstance(item, X64DataZero):
                self._validate_data_zero(item, idx)
            else:
                self.errors.append(f"item {idx}: unsupported X64 item: {type(item).__name__}")

    def _validate_section(self, item, idx):
        if item.name not in SUPPORTED_SECTIONS:
            self.errors.append(f"item {idx}: unsupported section: {item.name}")
        self.section = item.name

    def _validate_label(self, item, idx):
        self._require_name(item.name, idx, "label")
        if self.section not in SUPPORTED_SECTIONS:
            self.errors.append(f"item {idx}: label outside section: {item.name}")

    def _validate_data_bytes(self, item, idx):
        self._require_section(idx, ".data", f"data bytes {item.label}")
        self._require_name(item.label, idx, "data label")
        for pos, value in enumerate(item.values):
            if not isinstance(value, int) or not 0 <= value <= 255:
                self.errors.append(f"item {idx}: data byte {item.label}[{pos}] out of range: {value}")

    def _validate_data_zero(self, item, idx):
        self._require_section(idx, ".data", f"data zero {item.label}")
        self._require_name(item.label, idx, "data label")
        if not isinstance(item.count, int) or item.count < 0:
            self.errors.append(f"item {idx}: data zero count must be non-negative: {item.count}")

    def _validate_inst(self, inst, idx):
        self._require_section(idx, ".text", inst.op)
        operands = inst.operands
        for operand in operands:
            self._validate_operand(operand, idx)

        if inst.op == "push":
            self._require(self._matches_regs(inst.operands, "rbp") or self._matches_regs(inst.operands, "r8"), idx, "push needs rbp or r8")
        elif inst.op == "pop":
            self._require(self._matches_regs(inst.operands, "rdx") or self._matches_regs(inst.operands, "rbp"), idx, "pop needs rdx or rbp")
        elif inst.op == "ret":
            self._require(len(operands) == 0, idx, "ret takes no operands")
        elif inst.op in ("sub", "add") and self._is_reg_imm(operands, "rsp"):
            self._require_i32(operands[1].value, idx, f"{inst.op} rsp immediate")
        elif inst.op == "call":
            self._validate_call(inst, idx)
        elif inst.op in JUMPS:
            self._validate_jump(inst, idx)
        elif inst.op == "cqo":
            self._require(len(operands) == 0, idx, "cqo takes no operands")
        elif inst.op in ("idiv", "div"):
            self._require_regs(idx, inst, "rcx")
        elif inst.op == "imul":
            self._require_regs(idx, inst, "rax", "rcx")
        elif inst.op == "neg":
            self._require_regs(idx, inst, "rax")
        elif inst.op == "cmp":
            self._validate_cmp(inst, idx)
        elif inst.op in SETCC:
            self._require_regs(idx, inst, "al")
        elif inst.op == "movzx":
            self._validate_movzx(inst, idx)
        elif inst.op == "movsx":
            self._validate_movsx(inst, idx)
        elif inst.op == "test":
            self._validate_test(inst, idx)
        elif inst.op in SHIFT_OPS:
            self._require_regs(idx, inst, "rax", "cl")
        elif inst.op in ("inc", "dec"):
            self._require(len(operands) == 1 and self._is_reg64(operands[0]), idx, f"{inst.op} needs one r64")
        elif inst.op in ALU_REG_REG and self._two_reg64(operands):
            return
        elif inst.op == "add" and self._is_any_reg_imm(operands):
            self._validate_add_reg_imm(inst, idx)
        elif inst.op == "mov":
            self._validate_mov(inst, idx)
        elif inst.op == "lea":
            self._validate_lea(inst, idx)
        else:
            self.errors.append(f"item {idx}: unsupported instruction: {inst.lines()[0].strip()}")

    def _validate_operand(self, operand, idx):
        if isinstance(operand, Reg):
            return
        if isinstance(operand, Imm):
            if not isinstance(operand.value, int):
                self.errors.append(f"item {idx}: immediate is not an int: {operand.value}")
            return
        if isinstance(operand, Symbol):
            self._require_known_symbol(operand.name, idx, "symbol")
            return
        if isinstance(operand, LabelRef):
            return
        if isinstance(operand, Mem):
            self._validate_mem(operand, idx)
            return
        self.errors.append(f"item {idx}: unsupported operand: {type(operand).__name__}")

    def _validate_mem(self, mem, idx):
        if mem.size not in (1, 8):
            self.errors.append(f"item {idx}: memory size must be 1 or 8: {mem.size}")
        if mem.symbol is not None:
            if mem.base is not None:
                self.errors.append(f"item {idx}: memory cannot have both base and symbol")
            self._require_known_symbol(mem.symbol, idx, "memory symbol")
            return
        if mem.base is None:
            self.errors.append(f"item {idx}: memory needs a base register or symbol")
            return
        if not self._is_reg64(mem.base):
            self.errors.append(f"item {idx}: memory base must be r64: {mem.base.text()}")
        self._require_i32(mem.disp, idx, "memory displacement")

    def _validate_call(self, inst, idx):
        operands = inst.operands
        self._require(len(operands) == 1 and isinstance(operands[0], Symbol), idx, "call needs one Symbol operand")

    def _validate_jump(self, inst, idx):
        operands = inst.operands
        if not self._require(len(operands) == 1 and isinstance(operands[0], LabelRef), idx, f"{inst.op} needs one LabelRef operand"):
            return
        target = operands[0].name
        if target not in self.text_labels and target not in self.externs:
            self.errors.append(f"item {idx}: undefined branch target: {target}")

    def _validate_cmp(self, inst, idx):
        operands = inst.operands
        if self._two_reg64(operands):
            return
        if self._is_reg_imm_any(operands):
            self._require_i32(operands[1].value, idx, "cmp immediate")
            return
        self.errors.append(f"item {idx}: cmp needs r64,r64 or r64,imm32")

    def _validate_movzx(self, inst, idx):
        operands = inst.operands
        if len(operands) == 2 and self._is_reg64(operands[0]) and isinstance(operands[1], Mem):
            mem = operands[1]
            if mem.size != 1 or mem.symbol is not None:
                self.errors.append(f"item {idx}: movzx source must be byte base memory")
            return
        self._require_regs(idx, inst, "eax", "al")

    def _validate_movsx(self, inst, idx):
        operands = inst.operands
        if not self._require(len(operands) == 2 and self._is_reg64(operands[0]) and isinstance(operands[1], Mem), idx, "movsx needs r64, byte [r64+disp]"):
            return
        mem = operands[1]
        if mem.size != 1 or mem.symbol is not None:
            self.errors.append(f"item {idx}: movsx source must be byte base memory")

    def _validate_test(self, inst, idx):
        operands = inst.operands
        if not self._require(self._two_reg64(operands), idx, "test needs r64, r64"):
            return
        if operands[0].name != operands[1].name:
            self.errors.append(f"item {idx}: test requires identical operands, got {operands[0].text()}, {operands[1].text()}")

    def _validate_add_reg_imm(self, inst, idx):
        operands = inst.operands
        reg = operands[0]
        imm = operands[1].value
        if self._is_reg64(reg) or self._is_reg8(reg):
            self._require_i8(imm, idx, "add immediate")
            return
        self.errors.append(f"item {idx}: add immediate target must be r64 or r8")

    def _validate_mov(self, inst, idx):
        operands = inst.operands
        if not self._require(len(operands) == 2, idx, "mov needs two operands"):
            return
        dst, src = operands
        if self._is_reg64(dst) and isinstance(src, Imm):
            self._require_i64(src.value, idx, "mov immediate")
        elif self._is_reg32_imm(dst) and isinstance(src, Imm):
            self._require_i32(src.value, idx, "mov r32 immediate")
        elif self._is_reg64(dst) and self._is_reg64(src):
            return
        elif self._is_reg64(dst) and isinstance(src, Mem):
            self._require(src.size == 8, idx, "mov r64 load needs qword memory")
        elif isinstance(dst, Mem) and (self._is_reg64(src) or self._is_reg8(src)):
            if self._is_reg8(src):
                self._require(dst.size == 1, idx, "byte register store needs byte memory")
                if dst.symbol is not None:
                    self._require(src.name == "al", idx, "symbol byte store only supports al")
            else:
                self._require(dst.size == 8, idx, "r64 store needs qword memory")
        elif isinstance(dst, Mem) and isinstance(src, Imm):
            self._require(dst.symbol is None, idx, "immediate store to symbol is not implemented")
            if dst.size == 1:
                self._require_i8(src.value, idx, "mov byte memory immediate")
            elif dst.size == 8:
                self._require_i32(src.value, idx, "mov qword memory immediate")
            else:
                self.errors.append(f"item {idx}: unsupported mov memory immediate size: {dst.size}")
        else:
            self.errors.append(f"item {idx}: unsupported mov operands")

    def _validate_lea(self, inst, idx):
        operands = inst.operands
        if not self._require(len(operands) == 2 and self._is_reg64(operands[0]) and isinstance(operands[1], Mem), idx, "lea needs r64, memory"):
            return
        mem = operands[1]
        if mem.symbol is None and mem.base is None:
            self.errors.append(f"item {idx}: lea memory needs base or symbol")

    def _require_section(self, idx, expected, what):
        if self.section != expected:
            self.errors.append(f"item {idx}: {what} outside {expected}")

    def _require_name(self, name, idx, kind):
        if not isinstance(name, str) or not name:
            self.errors.append(f"item {idx}: {kind} needs a non-empty name")

    def _require_known_symbol(self, name, idx, kind):
        if name not in self.declared_symbols:
            self.errors.append(f"item {idx}: undefined {kind}: {name}")

    def _require_i8(self, value, idx, what):
        if not isinstance(value, int) or not -128 <= value <= 127:
            self.errors.append(f"item {idx}: {what} must fit signed imm8: {value}")

    def _require_i32(self, value, idx, what):
        if not isinstance(value, int) or not -2147483648 <= value <= 2147483647:
            self.errors.append(f"item {idx}: {what} must fit signed imm32: {value}")

    def _require_i64(self, value, idx, what):
        if not isinstance(value, int) or not -9223372036854775808 <= value <= 18446744073709551615:
            self.errors.append(f"item {idx}: {what} must fit x64 immediate: {value}")

    def _require_regs(self, idx, inst, *names):
        ok = self._matches_regs(inst.operands, *names)
        if not ok:
            self.errors.append(f"item {idx}: {inst.op} needs operands: {', '.join(names)}")
        return ok

    def _matches_regs(self, operands, *names):
        return len(operands) == len(names) and all(
            isinstance(operand, Reg) and operand.name == name
            for operand, name in zip(operands, names)
        )

    def _require(self, condition, idx, message):
        if not condition:
            self.errors.append(f"item {idx}: {message}")
        return condition

    def _is_reg64(self, operand):
        return isinstance(operand, Reg) and operand.name in REG64

    def _is_reg8(self, operand):
        return isinstance(operand, Reg) and operand.name in REG8

    def _is_reg32_imm(self, operand):
        return isinstance(operand, Reg) and operand.name in REG32_MOV_IMM

    def _two_reg64(self, operands):
        return len(operands) == 2 and self._is_reg64(operands[0]) and self._is_reg64(operands[1])

    def _is_reg_imm(self, operands, reg):
        return len(operands) == 2 and isinstance(operands[0], Reg) and operands[0].name == reg and isinstance(operands[1], Imm)

    def _is_reg_imm_any(self, operands):
        return len(operands) == 2 and self._is_reg64(operands[0]) and isinstance(operands[1], Imm)

    def _is_any_reg_imm(self, operands):
        return len(operands) == 2 and isinstance(operands[0], Reg) and isinstance(operands[1], Imm)


def validate_x64_program(program):
    X64Validator(program).validate()


def R(name):
    return Reg(name)


def I(value):
    return Imm(value)


def M(base=None, disp=0, size=8):
    return Mem(base=R(base) if isinstance(base, str) else base, disp=disp, size=size)


def MS(symbol, size=8):
    return Mem(symbol=symbol, size=size)
