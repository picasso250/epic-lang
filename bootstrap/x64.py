"""Structured X64/MachineIR for Epic's machine backend."""

from dataclasses import dataclass, field


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


def R(name):
    return Reg(name)


def I(value):
    return Imm(value)


def M(base=None, disp=0, size=8):
    return Mem(base=R(base) if isinstance(base, str) else base, disp=disp, size=size)


def MS(symbol, size=8):
    return Mem(symbol=symbol, size=size)

