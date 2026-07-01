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
    "r8": 8,
    "r9": 9,
    "r10": 10,
    "r11": 11,
}

REG32_MOV_IMM = {
    "eax": 0xB8,
    "ecx": 0xB9,
    "edx": 0xBA,
}

REG8 = {
    "al": 0,
    "cl": 1,
    "dl": 2,
    "r10b": 10,
    "r11b": 11,
}

JCC = {
    "jo": 0x80,
    "jz": 0x84,
    "jnz": 0x85,
    "jns": 0x89,
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
        self.internal_fixups = []
        self.section = None

    def write_obj(self, path):
        self._emit_program()
        self._emit_needed_runtime_helpers()
        self._patch_internal_fixups()
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
            self._emit_item(item)

    def _emit_item(self, item):
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
        elif op == "push r8":
            self.text.extend(b"\x41\x50")
        elif op == "pop rdx":
            self.text.append(0x5A)
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
        elif m := re.match(r"^(jmp|jo|jz|jnz|jns) ([A-Za-z_.$][\w.$]*)$", op):
            self._emit_jump(m.group(1), m.group(2))
        elif op == "cqo":
            self.text.extend(b"\x48\x99")
        elif op == "idiv rcx":
            self.text.extend(b"\x48\xf7\xf9")
        elif op == "div rcx":
            self.text.extend(b"\x48\xf7\xf1")
        elif op == "imul rax, rcx":
            self.text.extend(b"\x48\x0f\xaf\xc1")
        elif op == "neg rax":
            self.text.extend(b"\x48\xf7\xd8")
        elif m := re.match(r"^test ([a-z0-9]+), \1$", op):
            self._emit_test_reg_reg(m.group(1))
        elif m := re.match(r"^xor ([a-z0-9]+), \1$", op):
            self._emit_xor_reg_reg(m.group(1))
        elif m := re.match(r"^(inc|dec) ([a-z0-9]+)$", op):
            self._emit_inc_dec(m.group(1), m.group(2))
        elif m := re.match(r"^(add|sub) ([a-z][a-z0-9]*), ([a-z][a-z0-9]*)$", op):
            self._emit_reg_reg_alu(m.group(1), m.group(2), m.group(3))
        elif m := re.match(r"^add ([a-z0-9]+), (-?\d+|'0')$", op):
            imm = 48 if m.group(2) == "'0'" else int(m.group(2))
            self._emit_add_reg_imm(m.group(1), imm)
        elif m := re.match(r"^mov (e?[a-z0-9]+), (-?\d+)$", op):
            self._emit_mov_reg_imm(m.group(1), int(m.group(2)))
        elif m := re.match(r"^mov ([a-z0-9]+), ([a-z0-9]+)$", op):
            self._emit_mov_reg_reg(m.group(1), m.group(2))
        elif m := re.match(r"^lea ([a-z0-9]+), \[([A-Za-z_.$][\w.$]*)\]$", op):
            self._emit_lea_symbol(m.group(1), m.group(2))
        elif m := re.match(r"^lea ([a-z0-9]+), \[rbp([+-]\d+)\]$", op):
            self._emit_lea_base_disp(m.group(1), "rbp", int(m.group(2)))
        elif m := re.match(r"^mov \[([A-Za-z_.$][\w.$]*)\], rax$", op):
            self._emit_mov_symbol_reg(m.group(1), "rax")
        elif m := re.match(r"^mov \[([A-Za-z_.$][\w.$]*)\], al$", op):
            self._emit_mov_symbol_reg8(m.group(1), "al")
        elif m := re.match(r"^mov \[rbp([+-]\d+)\], rax$", op):
            self._emit_mov_mem_reg("rbp", int(m.group(1)), "rax")
        elif m := re.match(r"^mov \[rbp([+-]\d+)\], ([a-z0-9]+)$", op):
            self._emit_mov_mem_reg("rbp", int(m.group(1)), m.group(2))
        elif m := re.match(r"^mov ([a-z0-9]+), \[rbp([+-]\d+)\]$", op):
            self._emit_mov_reg_mem(m.group(1), "rbp", int(m.group(2)))
        elif m := re.match(r"^mov ([a-z0-9]+), \[([a-z0-9]+)\]$", op):
            self._emit_mov_reg_mem(m.group(1), m.group(2), 0)
        elif m := re.match(r"^mov ([a-z0-9]+), \[([a-z0-9]+)([+-]\d+)\]$", op):
            self._emit_mov_reg_mem(m.group(1), m.group(2), int(m.group(3)))
        elif m := re.match(r"^mov \[([a-z0-9]+)\], ([a-z0-9]+)$", op):
            self._emit_mov_mem_reg(m.group(1), 0, m.group(2))
        elif m := re.match(r"^mov \[([a-z0-9]+)([+-]\d+)\], ([a-z0-9]+)$", op):
            self._emit_mov_mem_reg(m.group(1), int(m.group(2)), m.group(3))
        elif m := re.match(r"^mov qword \[rsp\+(\d+)\], (-?\d+)$", op):
            self._emit_mov_mem_imm("rsp", int(m.group(1)), int(m.group(2)), 8)
        elif m := re.match(r"^mov byte \[([a-z0-9]+)\], (-?\d+|'[^']')$", op):
            imm = ord(m.group(2)[1]) if m.group(2).startswith("'") else int(m.group(2))
            self._emit_mov_mem_imm(m.group(1), 0, imm, 1)
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

    def _emit_jump(self, kind, symbol):
        if kind == "jmp":
            self.text.append(0xE9)
        else:
            self.text.extend(bytes([0x0F, JCC[kind]]))
        off = len(self.text)
        self.text.extend(b"\x00\x00\x00\x00")
        self.internal_fixups.append((off, symbol))

    def _emit_mov_reg_imm(self, reg, imm):
        if reg in REG32_MOV_IMM:
            self.text.append(REG32_MOV_IMM[reg])
            self.text.extend(struct.pack("<i", imm))
        elif reg == "rax":
            self.text.extend(b"\x48\xc7\xc0")
            self.text.extend(struct.pack("<i", imm))
        elif reg in REG64:
            self._rex(w=True, b=REG64[reg] >> 3)
            self.text.append(0xC7)
            self._modrm(3, 0, REG64[reg])
            self.text.extend(struct.pack("<i", imm))
        else:
            raise MachineBackendError(f"unsupported immediate move register: {reg}")

    def _emit_mov_reg_reg(self, dst, src):
        self._require_reg64(dst)
        self._require_reg64(src)
        self._rex(w=True, r=REG64[src] >> 3, b=REG64[dst] >> 3)
        self.text.append(0x89)
        self._modrm(3, REG64[src], REG64[dst])

    def _emit_mov_symbol_reg(self, symbol, reg):
        self._require_reg64(reg)
        self._rex(w=True, r=REG64[reg] >> 3)
        self.text.append(0x89)
        self.text.append(0x05 | ((REG64[reg] & 7) << 3))
        off = len(self.text)
        self.text.extend(b"\x00\x00\x00\x00")
        self.text_relocs.append((off, symbol))

    def _emit_mov_symbol_reg8(self, symbol, reg):
        if reg != "al":
            raise MachineBackendError(f"unsupported symbol byte store register: {reg}")
        self.text.extend(b"\x88\x05")
        off = len(self.text)
        self.text.extend(b"\x00\x00\x00\x00")
        self.text_relocs.append((off, symbol))

    def _emit_mov_reg_mem(self, dst, base, disp):
        self._require_reg64(dst)
        self._require_reg64(base)
        self._rex(w=True, r=REG64[dst] >> 3, b=REG64[base] >> 3)
        self.text.append(0x8B)
        self._mem_modrm(REG64[dst], base, disp)

    def _emit_mov_mem_reg(self, base, disp, src):
        self._require_reg64(base)
        if src in REG8:
            self._rex(r=REG8[src] >> 3, b=REG64[base] >> 3)
            self.text.append(0x88)
            self._mem_modrm(REG8[src], base, disp)
            return
        self._require_reg64(src)
        self._rex(w=True, r=REG64[src] >> 3, b=REG64[base] >> 3)
        self.text.append(0x89)
        self._mem_modrm(REG64[src], base, disp)

    def _emit_mov_mem_imm(self, base, disp, imm, size):
        self._require_reg64(base)
        if size == 1:
            self._rex(b=REG64[base] >> 3)
            self.text.append(0xC6)
            self._mem_modrm(0, base, disp)
            self.text.append(imm & 0xFF)
        else:
            self._rex(w=True, b=REG64[base] >> 3)
            self.text.append(0xC7)
            self._mem_modrm(0, base, disp)
            self.text.extend(struct.pack("<i", imm))

    def _emit_lea_symbol(self, dst, symbol):
        self._require_reg64(dst)
        self._rex(w=True, r=REG64[dst] >> 3)
        self.text.append(0x8D)
        self.text.append(0x05 | ((REG64[dst] & 7) << 3))
        off = len(self.text)
        self.text.extend(b"\x00\x00\x00\x00")
        self.text_relocs.append((off, symbol))

    def _emit_lea_base_disp(self, dst, base, disp):
        self._require_reg64(dst)
        self._require_reg64(base)
        self._rex(w=True, r=REG64[dst] >> 3, b=REG64[base] >> 3)
        self.text.append(0x8D)
        self._mem_modrm(REG64[dst], base, disp)

    def _emit_test_reg_reg(self, reg):
        self._require_reg64(reg)
        self._rex(w=True, r=REG64[reg] >> 3, b=REG64[reg] >> 3)
        self.text.append(0x85)
        self._modrm(3, REG64[reg], REG64[reg])

    def _emit_xor_reg_reg(self, reg):
        self._require_reg64(reg)
        self._rex(w=True, r=REG64[reg] >> 3, b=REG64[reg] >> 3)
        self.text.append(0x31)
        self._modrm(3, REG64[reg], REG64[reg])

    def _emit_inc_dec(self, op, reg):
        self._require_reg64(reg)
        self._rex(w=True, b=REG64[reg] >> 3)
        self.text.append(0xFF)
        self._modrm(3, 0 if op == "inc" else 1, REG64[reg])

    def _emit_reg_reg_alu(self, op, dst, src):
        self._require_reg64(dst)
        self._require_reg64(src)
        opcode = 0x01 if op == "add" else 0x29
        self._rex(w=True, r=REG64[src] >> 3, b=REG64[dst] >> 3)
        self.text.append(opcode)
        self._modrm(3, REG64[src], REG64[dst])

    def _emit_add_reg_imm(self, reg, imm):
        if reg in REG8:
            self._rex(b=REG8[reg] >> 3)
            self.text.append(0x80)
            self._modrm(3, 0, REG8[reg])
            self.text.append(imm & 0xFF)
            return
        self._require_reg64(reg)
        self._rex(w=True, b=REG64[reg] >> 3)
        self.text.append(0x83)
        self._modrm(3, 0, REG64[reg])
        self.text.append(imm & 0xFF)

    def _rex(self, w=False, r=0, x=0, b=0):
        value = 0x40 | (0x08 if w else 0) | ((r & 1) << 2) | ((x & 1) << 1) | (b & 1)
        if value != 0x40:
            self.text.append(value)

    def _modrm(self, mod, reg, rm):
        self.text.append(((mod & 3) << 6) | ((reg & 7) << 3) | (rm & 7))

    def _mem_modrm(self, reg_field, base, disp):
        base_code = REG64[base]
        rm = base_code & 7
        if disp == 0 and rm != 5:
            mod = 0
        elif -128 <= disp <= 127:
            mod = 1
        else:
            mod = 2
        self._modrm(mod, reg_field, 4 if rm == 4 else rm)
        if rm == 4:
            self.text.append(0x24)
        if mod == 1:
            self.text.append(disp & 0xFF)
        elif mod == 2 or (mod == 0 and rm == 5):
            self.text.extend(struct.pack("<i", disp))

    def _require_reg64(self, reg):
        if reg not in REG64:
            raise MachineBackendError(f"unsupported register: {reg}")

    def _emit_needed_runtime_helpers(self):
        referenced = {sym for _, sym in self.text_relocs}
        if "_itoa" not in referenced or "_itoa" in self.text_labels:
            return
        for item in _itoa_helper_items():
            self._emit_item(item)

    def _patch_internal_fixups(self):
        for off, symbol in self.internal_fixups:
            if symbol not in self.text_labels:
                self.text_relocs.append((off, symbol))
                continue
            disp = self.text_labels[symbol] - (off + 4)
            struct.pack_into("<i", self.text, off, disp)

def write_machine_obj(program, obj_path):
    MachineObjectBuilder(program).write_obj(obj_path)


def _itoa_helper_items():
    return [
        MirAsmSection(".data"),
        MirAsmDataZero("_itoa_header", 16),
        MirAsmDataZero("_itoa_buf", 32),
        MirAsmSection(".text"),
        MirAsmLabel("_itoa"),
        MirAsmInst("push rbp"),
        MirAsmInst("mov rbp, rsp"),
        MirAsmInst("sub rsp, 16"),
        MirAsmInst("lea r10, [_itoa_buf]"),
        MirAsmInst("add r10, 31"),
        MirAsmInst("mov byte [r10], 0"),
        MirAsmInst("mov r11, 0"),
        MirAsmInst("mov rax, rcx"),
        MirAsmInst("mov r8, 0"),
        MirAsmInst("test rax, rax"),
        MirAsmInst("jns _itoa_positive"),
        MirAsmInst("neg rax"),
        MirAsmInst("mov r8, 1"),
        MirAsmLabel("_itoa_positive"),
        MirAsmInst("test rax, rax"),
        MirAsmInst("jnz _itoa_loop"),
        MirAsmInst("dec r10"),
        MirAsmInst("mov byte [r10], 48"),
        MirAsmInst("inc r11"),
        MirAsmInst("jmp _itoa_digits_done"),
        MirAsmLabel("_itoa_loop"),
        MirAsmInst("xor rdx, rdx"),
        MirAsmInst("mov rcx, 10"),
        MirAsmInst("div rcx"),
        MirAsmInst("add dl, 48"),
        MirAsmInst("dec r10"),
        MirAsmInst("mov [r10], dl"),
        MirAsmInst("inc r11"),
        MirAsmInst("test rax, rax"),
        MirAsmInst("jnz _itoa_loop"),
        MirAsmLabel("_itoa_digits_done"),
        MirAsmInst("test r8, r8"),
        MirAsmInst("jz _itoa_finish"),
        MirAsmInst("dec r10"),
        MirAsmInst("mov byte [r10], 45"),
        MirAsmInst("inc r11"),
        MirAsmLabel("_itoa_finish"),
        MirAsmInst("lea rax, [_itoa_header]"),
        MirAsmInst("mov [rax], r10"),
        MirAsmInst("mov [rax+8], r11"),
        MirAsmInst("mov rsp, rbp"),
        MirAsmInst("pop rbp"),
        MirAsmInst("ret"),
    ]
