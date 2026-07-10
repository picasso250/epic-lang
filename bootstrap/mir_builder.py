"""Helpers for constructing MIR functions.

This module intentionally sits between the MIR data model and higher-level
emitters.  It owns only function-local construction state: the current insertion
block, value/block counters, and basic instruction/terminator emission.
"""

from mir import Br, CondBr, MirBlock, MirFunction, MirInst, MirParam, MirValue, Ret

_MISSING = object()


class MirFunctionBuilder:
    """Function-local MIR construction state and primitive emit helpers."""

    def __init__(
        self,
        name: str | None = None,
        params: list[MirParam] | None = None,
        ret_type=None,
        *,
        numbered_blocks: bool = True,
        clear_current_on_terminate: bool = True,
        create_entry: bool = False,
    ):
        self.numbered_blocks = numbered_blocks
        self.clear_current_on_terminate = clear_current_on_terminate
        self.fn = None
        self.entry_block = None
        self.current_block = None
        self.value_counter = 0
        self.block_counter = 0
        if name is not None:
            self.begin_function(name, params or [], ret_type, create_entry=create_entry)

    def begin_function(self, name: str, params: list[MirParam], ret_type, *, create_entry: bool = False):
        self.fn = MirFunction(name, params, ret_type)
        self.entry_block = None
        self.current_block = None
        self.value_counter = max((param.id for param in params), default=0)
        self.block_counter = 0
        if create_entry:
            self.entry_block = self.new_block("entry")
            self.current_block = self.entry_block
        return self.fn

    def new_value(self, typ):
        self.value_counter += 1
        return MirValue(self.value_counter, typ)

    def value(self, typ):
        return self.new_value(typ)

    def new_block(self, prefix):
        if self.fn is None:
            raise RuntimeError("cannot create MIR block before begin_function")
        if self.numbered_blocks:
            self.block_counter += 1
            name = f"{prefix}{self.block_counter}"
        else:
            name = prefix
        block = MirBlock(name)
        self.fn.blocks.append(block)
        return block

    def ensure_insertable(self, block=None):
        block = self.current_block if block is None else block
        if block is None:
            raise RuntimeError("no reachable MIR insertion block")
        if block.terminator is not None:
            raise RuntimeError(f"cannot emit after terminator in block {block.name}")
        return block

    def set_block(self, block):
        self.current_block = self.ensure_insertable(block)
        return self.current_block

    def inst(self, op, operands=None, result_type=None, type=None, callee=None):
        block = self.ensure_insertable()
        result = self.new_value(result_type) if result_type is not None else None
        inst = MirInst(op, operands or [], result=result, type=type, callee=callee)
        block.instructions.append(inst)
        return result

    def terminate(self, block_or_terminator, terminator=None):
        if terminator is None:
            block = self.ensure_insertable()
            terminator = block_or_terminator
        else:
            block = self.ensure_insertable(block_or_terminator)
        block.terminator = terminator
        if self.clear_current_on_terminate and self.current_block is block:
            self.current_block = None
        return None

    def br(self, block_or_target, target=None):
        if target is None:
            block = self.ensure_insertable()
            target = block_or_target
        else:
            block = block_or_target
        target_name = target.name if isinstance(target, MirBlock) else target
        return self.terminate(block, Br(target_name))

    def condbr(self, block_or_cond, cond_or_then, then_or_else=None, else_target=None):
        if else_target is None:
            block = self.ensure_insertable()
            cond = block_or_cond
            then_target = cond_or_then
            else_target = then_or_else
        else:
            block = block_or_cond
            cond = cond_or_then
            then_target = then_or_else
        then_name = then_target.name if isinstance(then_target, MirBlock) else then_target
        else_name = else_target.name if isinstance(else_target, MirBlock) else else_target
        return self.terminate(block, CondBr(cond, then_name, else_name))

    def ret(self, block_or_value=None, value=_MISSING):
        if value is _MISSING:
            if isinstance(block_or_value, MirBlock):
                block = block_or_value
                value = None
            else:
                block = self.ensure_insertable()
                value = block_or_value
        else:
            block = block_or_value
        if value is None:
            return self.terminate(block, Ret())
        return self.terminate(block, Ret(value))
