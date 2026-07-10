"""Machine-code backend for structured X64Program input."""

import struct

from coff import write_coff_obj
from x64 import Imm, LabelRef, Mem, Reg, Symbol, X64DataBytes, X64DataZero
from x64 import X64Extern, X64Global, X64Inst, X64Label, X64Section
from x64 import validate_x64_program


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
    "r8b": 8,
    "r9b": 9,
    "r10b": 10,
    "r11b": 11,
}

JCC = {
    "jo": 0x80,
    "jz": 0x84,
    "jnz": 0x85,
    "jl": 0x8C,
    "jge": 0x8D,
    "jle": 0x8E,
    "jg": 0x8F,
    "jns": 0x89,
}


class MachineBackendError(RuntimeError):
    pass


class MachineObjectBuilder:
    def __init__(self, program):
        validate_x64_program(program)
        self.program = program
        self.text = bytearray()
        self.data = bytearray()
        self.label_offsets = [0] * program.label_count
        self.label_defined = [False] * program.label_count
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
        # The Python reference backend intentionally uses CPython's native hash
        # tables; the self-hosted backend owns its separate MachineNameIndex.
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
        if isinstance(item, X64Global):
            pass
        elif isinstance(item, X64Extern):
            self.externs.add(item.name)
        elif isinstance(item, X64Section):
            self.section = item.name
        elif isinstance(item, X64Label):
            if item.id < 0 or item.id >= self.program.label_count:
                raise MachineBackendError(f"label id out of range: {item.id}")
            if self.label_defined[item.id]:
                raise MachineBackendError(f"duplicate label binding: {item.text()}")
            if self.section == ".text":
                self.label_offsets[item.id] = len(self.text)
                self.label_defined[item.id] = True
                if item.symbol_name is not None:
                    self.text_labels[item.symbol_name] = len(self.text)
            elif self.section == ".data":
                self.label_offsets[item.id] = len(self.data)
                self.label_defined[item.id] = True
                if item.symbol_name is not None:
                    self.data_labels[item.symbol_name] = len(self.data)
            else:
                raise MachineBackendError(f"label outside section: {item.text()}")
        elif isinstance(item, X64Inst):
            if self.section != ".text":
                raise MachineBackendError(f"instruction outside .text: {item.op}")
            self._emit_inst(item)
        elif isinstance(item, X64DataBytes):
            self._require_data_section(item.label)
            self.data_labels[item.label] = len(self.data)
            self.data.extend(v & 0xFF for v in item.values)
        elif isinstance(item, X64DataZero):
            self._require_data_section(item.label)
            self.data_labels[item.label] = len(self.data)
            self.data.extend(b"\x00" * item.count)
        else:
            raise MachineBackendError(f"unsupported machine item: {type(item).__name__}")

    def _require_data_section(self, label):
        if self.section != ".data":
            raise MachineBackendError(f"data item outside .data section: {label}")

    def _emit_inst(self, inst):
        op = inst.op
        operands = inst.operands
        if op == "push" and self._regs(operands, "rbp"):
            self.text.append(0x55)
        elif op == "push" and self._regs(operands, "r8"):
            self.text.extend(b"\x41\x50")
        elif op == "pop" and self._regs(operands, "rdx"):
            self.text.append(0x5A)
        elif op == "pop" and self._regs(operands, "rbp"):
            self.text.append(0x5D)
        elif op == "ret" and not operands:
            self.text.append(0xC3)
        elif op in ("sub", "add") and self._reg_imm(operands, "rsp"):
            self._emit_rsp_imm(0xEC if op == "sub" else 0xC4, operands[1].value)
        elif op == "call" and len(operands) == 1 and isinstance(operands[0], Symbol):
            self._emit_call(operands[0].name)
        elif op in ("jmp", "jo", "jz", "jnz", "jl", "jge", "jle", "jg", "jns") and len(operands) == 1 and isinstance(operands[0], LabelRef):
            self._emit_jump(op, operands[0].label)
        elif op == "cqo" and not operands:
            self.text.extend(b"\x48\x99")
        elif op in ("idiv", "div") and self._regs(operands, "rcx"):
            self.text.extend(b"\x48\xf7\xf9" if op == "idiv" else b"\x48\xf7\xf1")
        elif op == "imul" and self._regs(operands, "rax", "rcx"):
            self.text.extend(b"\x48\x0f\xaf\xc1")
        elif op == "neg" and self._regs(operands, "rax"):
            self.text.extend(b"\x48\xf7\xd8")
        elif op == "cmp" and self._two_regs(operands):
            self._emit_cmp_reg_reg(operands[0].name, operands[1].name)
        elif op == "cmp" and len(operands) == 2 and isinstance(operands[0], Reg) and isinstance(operands[1], Imm):
            self._emit_cmp_reg_imm(operands[0].name, operands[1].value)
        elif op in ("sete", "setne", "setg", "setl", "setge", "setle", "seta", "setae", "setb", "setbe") and self._regs(operands, "al"):
            self._emit_setcc(op)
        elif op == "movzx" and len(operands) == 2 and isinstance(operands[0], Reg) and isinstance(operands[1], Mem):
            mem = operands[1]
            if mem.size != 1 or mem.symbol is not None:
                raise MachineBackendError("movzx only supports byte base memory")
            self._emit_movzx_reg_mem8(operands[0].name, mem.base.name, mem.disp)
        elif op == "movzx" and self._regs(operands, "eax", "al"):
            self.text.extend(b"\x0f\xb6\xc0")
        elif op == "movsx" and len(operands) == 2 and isinstance(operands[0], Reg) and isinstance(operands[1], Mem):
            mem = operands[1]
            if mem.size != 1 or mem.symbol is not None:
                raise MachineBackendError("movsx only supports byte base memory")
            self._emit_movsx_reg_mem8(operands[0].name, mem.base.name, mem.disp)
        elif op == "test" and self._two_regs(operands) and operands[0].name == operands[1].name:
            self._emit_test_reg_reg(operands[0].name)
        elif op == "xor" and self._two_regs(operands) and operands[0].name == operands[1].name:
            self._emit_xor_reg_reg(operands[0].name)
        elif op in ("shl", "sar", "shr") and self._regs(operands, "rax", "cl"):
            self._emit_shift_rax_cl(op)
        elif op in ("inc", "dec") and len(operands) == 1 and isinstance(operands[0], Reg):
            self._emit_inc_dec(op, operands[0].name)
        elif op in ("add", "sub", "and", "or", "xor") and self._two_regs(operands):
            self._emit_reg_reg_alu(op, operands[0].name, operands[1].name)
        elif op == "add" and len(operands) == 2 and isinstance(operands[0], Reg) and isinstance(operands[1], Imm):
            self._emit_add_reg_imm(operands[0].name, operands[1].value)
        elif op == "mov":
            self._emit_mov_operands(operands)
        elif op == "lea" and len(operands) == 2 and isinstance(operands[0], Reg) and isinstance(operands[1], Mem):
            mem = operands[1]
            if mem.symbol is not None:
                self._emit_lea_symbol(operands[0].name, mem.symbol)
            else:
                self._emit_lea_base_disp(operands[0].name, mem.base.name, mem.disp)
        else:
            raise MachineBackendError(f"unsupported instruction: {inst.lines()[0].strip()}")

    def _emit_mov_operands(self, operands):
        if len(operands) != 2:
            raise MachineBackendError("mov needs two operands")
        dst, src = operands
        if isinstance(dst, Reg) and isinstance(src, Imm):
            self._emit_mov_reg_imm(dst.name, src.value)
        elif isinstance(dst, Reg) and isinstance(src, Reg):
            self._emit_mov_reg_reg(dst.name, src.name)
        elif isinstance(dst, Reg) and isinstance(src, Mem):
            if src.symbol is not None:
                self._emit_mov_reg_symbol(dst.name, src.symbol)
            else:
                self._emit_mov_reg_mem(dst.name, src.base.name, src.disp)
        elif isinstance(dst, Mem) and isinstance(src, Reg):
            if dst.symbol is not None:
                if src.name in REG8:
                    self._emit_mov_symbol_reg8(dst.symbol, src.name)
                else:
                    self._emit_mov_symbol_reg(dst.symbol, src.name)
            else:
                self._emit_mov_mem_reg(dst.base.name, dst.disp, src.name)
        elif isinstance(dst, Mem) and isinstance(src, Imm):
            if dst.symbol is not None:
                raise MachineBackendError("immediate store to symbol is not implemented")
            self._emit_mov_mem_imm(dst.base.name, dst.disp, src.value, dst.size)
        else:
            raise MachineBackendError("unsupported mov operands")

    def _regs(self, operands, *names):
        return len(operands) == len(names) and all(isinstance(op, Reg) and op.name == name for op, name in zip(operands, names))

    def _two_regs(self, operands):
        return len(operands) == 2 and isinstance(operands[0], Reg) and isinstance(operands[1], Reg)

    def _reg_imm(self, operands, reg):
        return len(operands) == 2 and isinstance(operands[0], Reg) and operands[0].name == reg and isinstance(operands[1], Imm)

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

    def _emit_jump(self, kind, label):
        if kind == "jmp":
            self.text.append(0xE9)
        else:
            self.text.extend(bytes([0x0F, JCC[kind]]))
        off = len(self.text)
        self.text.extend(b"\x00\x00\x00\x00")
        self.internal_fixups.append((off, label))

    def _emit_mov_reg_imm(self, reg, imm):
        if reg in REG32_MOV_IMM:
            self.text.append(REG32_MOV_IMM[reg])
            self.text.extend(struct.pack("<i", imm))
        elif reg in REG64 and not (-2147483648 <= imm <= 2147483647):
            self._rex(w=True, b=REG64[reg] >> 3)
            self.text.append(0xB8 + (REG64[reg] & 7))
            self.text.extend(struct.pack("<Q", imm & 0xFFFFFFFFFFFFFFFF))
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

    def _emit_mov_reg_symbol(self, reg, symbol):
        self._require_reg64(reg)
        self._rex(w=True, r=REG64[reg] >> 3)
        self.text.append(0x8B)
        self.text.append(0x05 | ((REG64[reg] & 7) << 3))
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

    def _emit_movsx_reg_mem8(self, dst, base, disp):
        self._require_reg64(dst)
        self._require_reg64(base)
        self._rex(w=True, r=REG64[dst] >> 3, b=REG64[base] >> 3)
        self.text.extend(b"\x0f\xbe")
        self._mem_modrm(REG64[dst], base, disp)

    def _emit_movzx_reg_mem8(self, dst, base, disp):
        self._require_reg64(dst)
        self._require_reg64(base)
        self._rex(w=True, r=REG64[dst] >> 3, b=REG64[base] >> 3)
        self.text.extend(b"\x0f\xb6")
        self._mem_modrm(REG64[dst], base, disp)

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
        opcode = {"add": 0x01, "sub": 0x29, "and": 0x21, "or": 0x09, "xor": 0x31}[op]
        self._rex(w=True, r=REG64[src] >> 3, b=REG64[dst] >> 3)
        self.text.append(opcode)
        self._modrm(3, REG64[src], REG64[dst])

    def _emit_shift_rax_cl(self, op):
        ext = {"shl": 4, "shr": 5, "sar": 7}[op]
        self._rex(w=True)
        self.text.append(0xD3)
        self._modrm(3, ext, REG64["rax"])

    def _emit_cmp_reg_reg(self, left, right):
        self._require_reg64(left)
        self._require_reg64(right)
        self._rex(w=True, r=REG64[right] >> 3, b=REG64[left] >> 3)
        self.text.append(0x39)
        self._modrm(3, REG64[right], REG64[left])

    def _emit_cmp_reg_imm(self, reg, imm):
        self._require_reg64(reg)
        self._rex(w=True, b=REG64[reg] >> 3)
        if -128 <= imm <= 127:
            self.text.append(0x83)
            self._modrm(3, 7, REG64[reg])
            self.text.append(imm & 0xFF)
        else:
            self.text.append(0x81)
            self._modrm(3, 7, REG64[reg])
            self.text.extend(struct.pack("<i", imm))

    def _emit_setcc(self, op):
        codes = {
            "sete": 0x94,
            "setne": 0x95,
            "setg": 0x9F,
            "setl": 0x9C,
            "setge": 0x9D,
            "setle": 0x9E,
            "seta": 0x97,
            "setae": 0x93,
            "setb": 0x92,
            "setbe": 0x96,
        }
        self.text.extend(bytes([0x0F, codes[op], 0xC0]))

    def _emit_add_reg_imm(self, reg, imm):
        if not -128 <= imm <= 127:
            raise MachineBackendError(f"add immediate out of signed imm8 range: {imm}")
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
        return

    def _patch_internal_fixups(self):
        for off, label in self.internal_fixups:
            if label.id < 0 or label.id >= self.program.label_count:
                raise MachineBackendError(f"label id out of range: {label.id}")
            if not self.label_defined[label.id]:
                if label.symbol_name is None:
                    raise MachineBackendError(f"unbound anonymous label: {label.text()}")
                self.text_relocs.append((off, label.symbol_name))
                continue
            disp = self.label_offsets[label.id] - (off + 4)
            struct.pack_into("<i", self.text, off, disp)

def write_machine_obj(program, obj_path):
    MachineObjectBuilder(program).write_obj(obj_path)


