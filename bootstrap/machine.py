"""Machine-code backend for the initial MirAsmProgram subset."""

import re
import struct

from coff import write_coff_obj
from mir_asm import MirAsmDataBytes, MirAsmDataInt, MirAsmDataZero, MirAsmDefaultRel
from mir_asm import MirAsmExtern, MirAsmGlobal, MirAsmInst, MirAsmLabel, MirAsmRaw, MirAsmSection


REG64 = {
    "rax": 0,
    "rcx": 1,
    "rdx": 2,
    "rbx": 3,
    "rsp": 4,
    "rbp": 5,
    "rsi": 6,
    "rdi": 7,
}

REG32_MOV_IMM = {
    "eax": 0xB8,
    "ecx": 0xB9,
    "edx": 0xBA,
}


class MachineBackendError(RuntimeError):
    pass


class MachineObjectBuilder:
    def __init__(self, program):
        self.program = program
        self.text = bytearray()
        self.data = bytearray()
        self.text_labels = {}
        self.data_labels = {}
        self.externs = set()
        self.text_relocs = []
        self.section = None

    def write_obj(self, path):
        self._emit_program()
        symbols = {}
        for name, off in self.text_labels.items():
            symbols[name] = (1, off)
        for name, off in self.data_labels.items():
            symbols[name] = (2, off)
        referenced = {sym for _, sym in self.text_relocs}
        for name in sorted(referenced):
            if name not in symbols:
                symbols[name] = (0, 0)
        write_coff_obj(path, self.text, self.data, self.text_relocs, [], symbols)

    def _emit_program(self):
        for item in self.program.items:
            if isinstance(item, MirAsmRaw):
                for line in item.lines():
                    if line.strip():
                        raise MachineBackendError(f"raw ASM is not supported by machine backend: {line.strip()}")
            elif isinstance(item, MirAsmGlobal):
                pass
            elif isinstance(item, MirAsmExtern):
                self.externs.add(item.name)
            elif isinstance(item, MirAsmDefaultRel):
                pass
            elif isinstance(item, MirAsmSection):
                self.section = item.name
            elif isinstance(item, MirAsmLabel):
                if self.section == ".text":
                    self.text_labels[item.name] = len(self.text)
                elif self.section == ".data":
                    self.data_labels[item.name] = len(self.data)
                else:
                    raise MachineBackendError(f"label outside section: {item.name}")
            elif isinstance(item, MirAsmInst):
                self._emit_inst(item.op)
            elif isinstance(item, MirAsmDataBytes):
                self._require_data_section(item.label)
                self.data_labels[item.label] = len(self.data)
                self.data.extend(v & 0xFF for v in item.values)
            elif isinstance(item, MirAsmDataZero):
                self._require_data_section(item.label)
                self.data_labels[item.label] = len(self.data)
                self.data.extend(b"\x00" * item.count)
            elif isinstance(item, MirAsmDataInt):
                self._require_data_section(item.label)
                self.data_labels[item.label] = len(self.data)
                self.data.extend(item.value.to_bytes(item.size, "little", signed=True))

    def _require_data_section(self, label):
        if self.section != ".data":
            raise MachineBackendError(f"data item outside .data section: {label}")

    def _strip_comment(self, line):
        return line.split(";", 1)[0]

    def _emit_inst(self, op):
        op = self._strip_comment(op).strip()
        if not op:
            return
        if op == "push rbp":
            self.text.append(0x55)
        elif op == "pop rbp":
            self.text.append(0x5D)
        elif op == "ret":
            self.text.append(0xC3)
        elif op == "mov rbp, rsp":
            self.text.extend(b"\x48\x89\xe5")
        elif op == "mov rsp, rbp":
            self.text.extend(b"\x48\x89\xec")
        elif m := re.match(r"^sub rsp, (-?\d+)$", op):
            self._emit_rsp_imm(0xEC, int(m.group(1)))
        elif m := re.match(r"^add rsp, (-?\d+)$", op):
            self._emit_rsp_imm(0xC4, int(m.group(1)))
        elif m := re.match(r"^call ([A-Za-z_.$][\w.$]*)$", op):
            self._emit_call(m.group(1))
        elif m := re.match(r"^mov (e?[a-z0-9]+), (-?\d+)$", op):
            self._emit_mov_reg_imm(m.group(1), int(m.group(2)))
        elif m := re.match(r"^mov \[([A-Za-z_.$][\w.$]*)\], rax$", op):
            self._emit_mov_mem_rax(m.group(1))
        elif m := re.match(r"^mov \[rbp([+-]\d+)\], rax$", op):
            self._emit_mov_rbp_rax(int(m.group(1)))
        elif m := re.match(r"^mov ([a-z0-9]+), \[rbp([+-]\d+)\]$", op):
            self._emit_mov_reg_rbp(m.group(1), int(m.group(2)))
        else:
            raise MachineBackendError(f"unsupported instruction: {op}")

    def _emit_rsp_imm(self, modrm_ext, imm):
        if 0 <= imm <= 127:
            self.text.extend(bytes([0x48, 0x83, modrm_ext, imm & 0xFF]))
        else:
            self.text.extend(bytes([0x48, 0x81, modrm_ext]))
            self.text.extend(struct.pack("<i", imm))

    def _emit_call(self, symbol):
        self.text.append(0xE8)
        off = len(self.text)
        self.text.extend(b"\x00\x00\x00\x00")
        self.text_relocs.append((off, symbol))

    def _emit_mov_reg_imm(self, reg, imm):
        if reg in REG32_MOV_IMM:
            self.text.append(REG32_MOV_IMM[reg])
            self.text.extend(struct.pack("<i", imm))
        elif reg == "rax":
            self.text.extend(b"\x48\xc7\xc0")
            self.text.extend(struct.pack("<i", imm))
        else:
            raise MachineBackendError(f"unsupported immediate move register: {reg}")

    def _emit_mov_mem_rax(self, symbol):
        self.text.extend(b"\x48\x89\x05")
        off = len(self.text)
        self.text.extend(b"\x00\x00\x00\x00")
        self.text_relocs.append((off, symbol))

    def _emit_mov_rbp_rax(self, disp):
        self.text.extend(b"\x48\x89\x85")
        self.text.extend(struct.pack("<i", disp))

    def _emit_mov_reg_rbp(self, reg, disp):
        if reg not in REG64:
            raise MachineBackendError(f"unsupported rbp load register: {reg}")
        self.text.extend(b"\x48\x8b")
        self.text.append(0x85 | (REG64[reg] << 3))
        self.text.extend(struct.pack("<i", disp))

def write_machine_obj(program, obj_path):
    MachineObjectBuilder(program).write_obj(obj_path)
