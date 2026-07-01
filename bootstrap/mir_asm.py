"""Low-level MIR container for NASM-compatible ASM pretty printing.

This is the migration bridge between the old direct text emitter and the
future machine backend. It preserves label/instruction boundaries where the
current emitter exposes them, while still allowing raw NASM helper blocks
during the runtime migration.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MirAsmRaw:
    text: str

    def lines(self):
        return self.text.splitlines() or [""]


@dataclass(frozen=True)
class MirAsmGlobal:
    name: str

    def lines(self):
        return [f"global {self.name}"]


@dataclass(frozen=True)
class MirAsmExtern:
    name: str

    def lines(self):
        return [f"extern {self.name}"]


@dataclass(frozen=True)
class MirAsmDefaultRel:
    def lines(self):
        return ["default rel"]


@dataclass(frozen=True)
class MirAsmSection:
    name: str

    def lines(self):
        return [f"section {self.name}"]


@dataclass(frozen=True)
class MirAsmLabel:
    name: str

    def lines(self):
        return [f"{self.name}:"]


@dataclass(frozen=True)
class MirAsmInst:
    op: str

    def lines(self):
        return [f"    {self.op}"]


@dataclass(frozen=True)
class MirAsmDataBytes:
    label: str
    values: list[int]

    def lines(self):
        return [f"{self.label}: db {', '.join(str(v) for v in self.values)}"]


@dataclass(frozen=True)
class MirAsmDataZero:
    label: str
    count: int

    def lines(self):
        return [f"    {self.label} times {self.count} db 0"]


@dataclass(frozen=True)
class MirAsmDataInt:
    label: str
    size: int
    value: int

    def lines(self):
        directive = "dd" if self.size == 4 else "dq"
        return [f"    {self.label} {directive} {self.value}"]


@dataclass
class MirAsmProgram:
    items: list = field(default_factory=list)
    current_section: str | None = None

    def raw(self, text):
        self.items.append(MirAsmRaw(text))

    def global_(self, name):
        self.items.append(MirAsmGlobal(name))

    def extern(self, name):
        self.items.append(MirAsmExtern(name))

    def default_rel(self):
        self.items.append(MirAsmDefaultRel())

    def section(self, name):
        self.current_section = name
        self.items.append(MirAsmSection(name))

    def label(self, name):
        self.items.append(MirAsmLabel(name))

    def inst(self, op):
        self.items.append(MirAsmInst(op))

    def data_bytes(self, label, values):
        self.items.append(MirAsmDataBytes(label, values))

    def data_zero(self, label, count):
        self.items.append(MirAsmDataZero(label, count))

    def data_int(self, label, size, value):
        self.items.append(MirAsmDataInt(label, size, value))

    def text(self):
        lines = []
        for item in self.items:
            lines.extend(item.lines())
        return "\n".join(lines) + "\n"


def write_asm_program(program, out_path):
    with open(out_path, "w", encoding="utf-8", newline="\n") as out:
        out.write(program.text())
