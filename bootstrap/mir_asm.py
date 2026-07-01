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
class MirAsmLabel:
    name: str

    def lines(self):
        return [f"{self.name}:"]


@dataclass(frozen=True)
class MirAsmInst:
    op: str

    def lines(self):
        return [f"    {self.op}"]


@dataclass
class MirAsmProgram:
    items: list[MirAsmRaw | MirAsmLabel | MirAsmInst] = field(default_factory=list)

    def raw(self, text):
        self.items.append(MirAsmRaw(text))

    def label(self, name):
        self.items.append(MirAsmLabel(name))

    def inst(self, op):
        self.items.append(MirAsmInst(op))

    def text(self):
        lines = []
        for item in self.items:
            lines.extend(item.lines())
        return "\n".join(lines) + "\n"


def write_asm_program(program, out_path):
    with open(out_path, "w", encoding="utf-8", newline="\n") as out:
        out.write(program.text())
