"""Code generation mixin split from bootstrap.codegen."""




class AsmEmitterMixin:
    def emit(self, s):
        if getattr(self, "asm_program", None) is not None:
            self.asm_program.raw(s)
            return
        self.out.write(s + "\n")

    def emit_label(self, name):
        if getattr(self, "asm_program", None) is not None:
            self.asm_program.label(name)
            return
        self.emit(f"{name}:")

    def emit_inst(self, op):
        if getattr(self, "asm_program", None) is not None:
            self.asm_program.inst(op)
            return
        self.emit(f"    {op}")

    def emit_mov(self, dst, src):
        self.emit_inst(f"mov {dst}, {src}")

    def emit_lea(self, dst, src):
        self.emit_inst(f"lea {dst}, {src}")

    def emit_call_inst(self, target):
        self.emit_inst(f"call {target}")

    def emit_jmp(self, label):
        self.emit_inst(f"jmp {label}")

    def rbp_slot(self, slot):
        return f"[rbp{slot:+d}]"

    def emit_stack_store(self, slot, src):
        self.emit_mov(self.rbp_slot(slot), src)

    def emit_stack_load(self, dst, slot):
        self.emit_mov(dst, self.rbp_slot(slot))

    def fresh_label(self):
        self.label_counter += 1
        return f"L{self.label_counter}"

    def close(self):
        if getattr(self, "asm_program", None) is not None:
            from mir_asm import write_asm_program

            write_asm_program(self.asm_program, self.out_path)
            return
        self.out.close()

    # ── program header ──────────────────────────────────────────────────

    def _call_prep(self, stack_args=0):
        """Emit sub rsp for extra stack params beyond the 4 register params.
        The frame already has 32 bytes shadow space; extra bytes are for
        params 5+ at [rsp+32], [rsp+40], etc.  Alignment: rsp ≡ 8 mod 16."""
        extra_bytes = stack_args * 8
        if extra_bytes == 0:
            return 0
        frame = ((extra_bytes + 15) // 16) * 16
        self.emit(f"    sub rsp, {frame}")
        return frame

    def _call_cleanup(self, stack_args=0):
        extra_bytes = stack_args * 8
        if extra_bytes == 0:
            return
        frame = ((extra_bytes + 15) // 16) * 16
        self.emit(f"    add rsp, {frame}")

    def _spill_args(self, args):
        slots = []
        for arg in args:
            self.emit_expr(arg)
            slot = self._alloc_temp()
            self.emit_stack_store(slot, "rax")
            slots.append(slot)
        return slots

    def _load_spilled_args(self, slots):
        param_regs = ["rcx", "rdx", "r8", "r9"]
        for i, slot in enumerate(slots):
            self.emit_stack_load(param_regs[i], slot)

    def _call_with_shadow(self, target):
        self.emit("    sub rsp, 32")
        self.emit_call_inst(target)
        self.emit("    add rsp, 32")

    def _syscall_symbol(self, name, namespace=""):
        if namespace == "os":
            symbol = name
        elif name.startswith("os."):
            symbol = name[3:]
        else:
            return None
        if symbol not in self.winapi:
            full_name = f"{namespace}.{name}" if namespace else name
            raise RuntimeError(f"Unsupported os call: {full_name}")
        return symbol

    def _emit_syscall(self, symbol, args):
        param_regs = ["rcx", "rdx", "r8", "r9"]
        slots = []
        for arg in args:
            arg_type = self._expr_type(arg)
            self.emit_expr(arg)
            if arg_type == "&str":
                self.emit_mov("rax", "[rax]")
            slot = self._alloc_temp()
            self.emit_stack_store(slot, "rax")
            slots.append(slot)
        stack_args = max(0, len(slots) - 4)
        extra_bytes = stack_args * 8
        extra_frame = ((extra_bytes + 15) // 16) * 16
        frame = 32 + extra_frame
        for i, slot in enumerate(slots[:4]):
            self.emit_stack_load(param_regs[i], slot)
        self.emit(f"    sub rsp, {frame}")
        for i, slot in enumerate(slots[4:]):
            self.emit_stack_load("rax", slot)
            self.emit_mov(f"[rsp+{32 + i * 8}]", "rax")
        self.emit_call_inst(symbol)
        self.emit(f"    add rsp, {frame}")
