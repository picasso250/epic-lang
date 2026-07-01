"""Lower Epic MIR to structured X64 MachineIR."""

from mir import Br, CondBr, ConstBoolOperand, ConstIntOperand, Ret, ValueOperand, VOID
from x64 import I, M, MS, R, LabelRef, Symbol, X64Program


ARG_REGS = ["rcx", "rdx", "r8", "r9"]


class MirLowerError(RuntimeError):
    pass


class MirLower:
    def __init__(self, program):
        self.program = program
        self.x64 = X64Program()
        self.value_slots = {}
        self.addr_slots = {}
        self.next_slot = 0
        self.return_label = None

    def lower(self):
        self.x64.global_("_start")
        for imp in self.program.imports:
            self.x64.extern(imp.name)
        self.x64.section(".data")
        self.x64.data_zero("_written", 4)
        self.x64.data_zero("_str_i64_header", 16)
        self.x64.data_zero("_str_i64_buf", 32)
        self.x64.data_bytes("_newline", [10])
        self.x64.section(".text")
        for fn in self.program.functions:
            self._lower_function(fn)
        self._emit_runtime_helpers()
        return self.x64

    def _lower_function(self, fn):
        self.value_slots = {}
        self.addr_slots = {}
        self.next_slot = 0
        self.return_label = f"{fn.name}.__return"
        self._plan_slots(fn)
        label = "_start" if fn.name == "main" else fn.name
        frame = self._aligned_frame()
        self.x64.label(label)
        self.x64.inst("push", R("rbp"))
        self.x64.inst("mov", R("rbp"), R("rsp"))
        if frame:
            self.x64.inst("sub", R("rsp"), I(frame))
        for idx, param in enumerate(fn.params):
            if idx >= len(ARG_REGS):
                raise MirLowerError(f"{fn.name}: more than four params are not supported")
            self.x64.inst("mov", M("rbp", self.value_slots[param.name]), R(ARG_REGS[idx]))
        for block in fn.blocks:
            self.x64.label(self._block_label(fn, block.name))
            for inst in block.instructions:
                self._lower_inst(inst)
            self._lower_term(fn, block.terminator)
        self.x64.label(self.return_label)
        if frame:
            self.x64.inst("add", R("rsp"), I(frame))
        self.x64.inst("pop", R("rbp"))
        self.x64.inst("ret")

    def _plan_slots(self, fn):
        for param in fn.params:
            self.value_slots[param.name] = self._slot()
        for block in fn.blocks:
            for inst in block.instructions:
                if inst.op == "alloca":
                    self.addr_slots[inst.result.name] = self._slot()
                elif inst.result is not None:
                    self.value_slots[inst.result.name] = self._slot()

    def _slot(self):
        self.next_slot += 8
        return -self.next_slot

    def _aligned_frame(self):
        return ((self.next_slot + 32 + 15) // 16) * 16

    def _block_label(self, fn, block_name):
        return f"{fn.name}.{block_name}"

    def _lower_inst(self, inst):
        if inst.op == "alloca":
            return
        if inst.op == "store":
            value, addr = inst.operands
            self._load_operand("rax", value)
            self.x64.inst("mov", M("rbp", self._addr_slot(addr)), R("rax"))
            return
        if inst.op == "load":
            self.x64.inst("mov", R("rax"), M("rbp", self._addr_slot(inst.operands[0])))
            self._store_result(inst.result, "rax")
            return
        if inst.op in ("add", "sub", "mul", "div", "mod"):
            self._load_operand("rax", inst.operands[0])
            self._load_operand("rcx", inst.operands[1])
            if inst.op == "add":
                self.x64.inst("add", R("rax"), R("rcx"))
            elif inst.op == "sub":
                self.x64.inst("sub", R("rax"), R("rcx"))
            elif inst.op == "mul":
                self.x64.inst("imul", R("rax"), R("rcx"))
            elif inst.op in ("div", "mod"):
                self.x64.inst("cqo")
                self.x64.inst("idiv", R("rcx"))
                if inst.op == "mod":
                    self.x64.inst("mov", R("rax"), R("rdx"))
            self._store_result(inst.result, "rax")
            return
        if inst.op == "not":
            self._load_operand("rax", inst.operands[0])
            self.x64.inst("test", R("rax"), R("rax"))
            self.x64.inst("sete", R("al"))
            self.x64.inst("movzx", R("eax"), R("al"))
            self._store_result(inst.result, "rax")
            return
        if inst.op.startswith("icmp."):
            self._load_operand("rax", inst.operands[0])
            self._load_operand("rcx", inst.operands[1])
            self.x64.inst("cmp", R("rax"), R("rcx"))
            cc = {"eq": "sete", "ne": "setne", "lt": "setl", "gt": "setg", "le": "setle", "ge": "setge"}[inst.op[5:]]
            self.x64.inst(cc, R("al"))
            self.x64.inst("movzx", R("eax"), R("al"))
            self._store_result(inst.result, "rax")
            return
        if inst.op == "call":
            self._lower_call(inst)
            return
        raise MirLowerError(f"unsupported MIR instruction: {inst.op}")

    def _lower_call(self, inst):
        if len(inst.operands) > 4:
            raise MirLowerError(f"call {inst.callee}: more than four args are not supported")
        for idx, operand in enumerate(inst.operands):
            self._load_operand(ARG_REGS[idx], operand)
        self.x64.inst("sub", R("rsp"), I(32))
        self.x64.inst("call", Symbol(inst.callee))
        self.x64.inst("add", R("rsp"), I(32))
        if inst.result is not None:
            self._store_result(inst.result, "rax")

    def _lower_term(self, fn, term):
        if isinstance(term, Br):
            self.x64.inst("jmp", LabelRef(self._block_label(fn, term.target)))
        elif isinstance(term, CondBr):
            self._load_operand("rax", term.cond)
            self.x64.inst("test", R("rax"), R("rax"))
            self.x64.inst("jnz", LabelRef(self._block_label(fn, term.then_target)))
            self.x64.inst("jmp", LabelRef(self._block_label(fn, term.else_target)))
        elif isinstance(term, Ret):
            if term.value is not None:
                self._load_operand("rax", term.value)
            if fn.name == "main":
                self.x64.inst("mov", R("rcx"), R("rax") if term.value is not None else I(0))
                self.x64.inst("sub", R("rsp"), I(32))
                self.x64.inst("call", Symbol("ExitProcess"))
            else:
                self.x64.inst("jmp", LabelRef(self.return_label))
        else:
            raise MirLowerError("missing terminator")

    def _load_operand(self, reg, operand):
        if isinstance(operand, ConstBoolOperand):
            self.x64.inst("mov", R(reg), I(1 if operand.value else 0))
        elif isinstance(operand, ConstIntOperand):
            self.x64.inst("mov", R(reg), I(operand.value))
        elif isinstance(operand, ValueOperand):
            name = operand.value.name
            if name in self.value_slots:
                self.x64.inst("mov", R(reg), M("rbp", self.value_slots[name]))
            elif name in self.addr_slots:
                self.x64.inst("lea", R(reg), M("rbp", self.addr_slots[name]))
            else:
                raise MirLowerError(f"unknown MIR value: {name}")
        else:
            raise MirLowerError(f"unsupported operand: {type(operand).__name__}")

    def _store_result(self, value, reg):
        self.x64.inst("mov", M("rbp", self.value_slots[value.name]), R(reg))

    def _addr_slot(self, operand):
        if not isinstance(operand, ValueOperand) or operand.value.name not in self.addr_slots:
            raise MirLowerError("only alloca addresses are supported in first MIR lowering")
        return self.addr_slots[operand.value.name]

    def _emit_runtime_helpers(self):
        self._emit_str_i64()
        self._emit_print_str()
        self._emit_print_newline()

    def _emit_str_i64(self):
        x = self.x64
        x.label("str_i64")
        x.inst("push", R("rbp"))
        x.inst("mov", R("rbp"), R("rsp"))
        x.inst("sub", R("rsp"), I(16))
        x.inst("lea", R("r10"), MS("_str_i64_buf"))
        x.inst("add", R("r10"), I(31))
        x.inst("mov", M("r10", 0, 1), I(0))
        x.inst("mov", R("r11"), I(0))
        x.inst("mov", R("rax"), R("rcx"))
        x.inst("mov", R("r8"), I(0))
        x.inst("test", R("rax"), R("rax"))
        x.inst("jns", LabelRef("str_i64.positive"))
        x.inst("neg", R("rax"))
        x.inst("mov", R("r8"), I(1))
        x.label("str_i64.positive")
        x.inst("test", R("rax"), R("rax"))
        x.inst("jnz", LabelRef("str_i64.loop"))
        x.inst("dec", R("r10"))
        x.inst("mov", M("r10", 0, 1), I(48))
        x.inst("inc", R("r11"))
        x.inst("jmp", LabelRef("str_i64.digits_done"))
        x.label("str_i64.loop")
        x.inst("xor", R("rdx"), R("rdx"))
        x.inst("mov", R("rcx"), I(10))
        x.inst("div", R("rcx"))
        x.inst("add", R("dl"), I(48))
        x.inst("dec", R("r10"))
        x.inst("mov", M("r10"), R("dl"))
        x.inst("inc", R("r11"))
        x.inst("test", R("rax"), R("rax"))
        x.inst("jnz", LabelRef("str_i64.loop"))
        x.label("str_i64.digits_done")
        x.inst("test", R("r8"), R("r8"))
        x.inst("jz", LabelRef("str_i64.finish"))
        x.inst("dec", R("r10"))
        x.inst("mov", M("r10", 0, 1), I(45))
        x.inst("inc", R("r11"))
        x.label("str_i64.finish")
        x.inst("lea", R("rax"), MS("_str_i64_header"))
        x.inst("mov", M("rax"), R("r10"))
        x.inst("mov", M("rax", 8), R("r11"))
        x.inst("add", R("rsp"), I(16))
        x.inst("pop", R("rbp"))
        x.inst("ret")

    def _emit_print_str(self):
        x = self.x64
        x.label("print_str")
        x.inst("push", R("rbp"))
        x.inst("mov", R("rbp"), R("rsp"))
        x.inst("sub", R("rsp"), I(48))
        x.inst("mov", M("rbp", -8), R("rcx"))
        x.inst("mov", R("rcx"), I(-11))
        x.inst("call", Symbol("GetStdHandle"))
        x.inst("mov", R("rcx"), R("rax"))
        x.inst("mov", R("rax"), M("rbp", -8))
        x.inst("mov", R("rdx"), M("rax"))
        x.inst("mov", R("r8"), M("rax", 8))
        x.inst("lea", R("r9"), MS("_written"))
        x.inst("mov", M("rsp", 32), I(0))
        x.inst("call", Symbol("WriteFile"))
        x.inst("add", R("rsp"), I(48))
        x.inst("pop", R("rbp"))
        x.inst("ret")

    def _emit_print_newline(self):
        x = self.x64
        x.label("print_newline")
        x.inst("push", R("rbp"))
        x.inst("mov", R("rbp"), R("rsp"))
        x.inst("sub", R("rsp"), I(48))
        x.inst("mov", R("rcx"), I(-11))
        x.inst("call", Symbol("GetStdHandle"))
        x.inst("mov", R("rcx"), R("rax"))
        x.inst("lea", R("rdx"), MS("_newline"))
        x.inst("mov", R("r8"), I(1))
        x.inst("lea", R("r9"), MS("_written"))
        x.inst("mov", M("rsp", 32), I(0))
        x.inst("call", Symbol("WriteFile"))
        x.inst("add", R("rsp"), I(48))
        x.inst("pop", R("rbp"))
        x.inst("ret")


def lower_mir_to_x64(program):
    return MirLower(program).lower()

