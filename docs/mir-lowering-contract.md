# MIR Lowering Contract

## Scope

本文档记录 **当前实现** 的 MIR → X64Program lowering 规则。它不是目标设计，也不是理想合约，而是 `bootstrap/mir_to_x64.py` 的真实行为。

目标 MIR 设计见 `docs/mir-design.md`。X64IR 合约见 `docs/x64-instruction-subset.md`。

```text
MIR -> MirLower -> X64Program -> X64IR text (debug) / machine -> COFF -> PE
```

## 1. 总体流程

```
MirLower.__init__(program)
  ├─ self.x64 = X64Program()
  └─ 初始化栈槽、scratch、临时状态

lower():
  ├─ x64.global("_start")
  ├─ x64.extern(...) for each referenced program extern and backend-owned runtime import
  ├─ x64.section(".data")
  ├─ emit_runtime_data(x64, program)    # 数据全局、string header
  ├─ x64.section(".text")
  ├─ for each fn: _lower_function(fn)
  └─ append_runtime_helpers(self)       # runtime helper x64 标签 + 函数体
```

`lower()` 后，`X64Program` 包含：
1. 数据段：运行时数据（`_heap`、`_argv`、string headers 等）
2. 代码段：每个用户函数 + runtime helpers

## 2. Function lowering

### 2.1 Entry label

| 函数名 | X64 label |
|--------|-----------|
| `main` | `_start` |
| 其他 | `fn.name`（如 `foo`、`bar`） |

### 2.2 Prologue

```
push rbp
mov  rbp, rsp
sub  rsp, aligned_frame   # 仅当 frame > 0
```

对 `main`：prologue 后插入 `__epx_runtime_start` 调用（初始化 `_heap` 和 `_argv`）：

```
sub  rsp, 32
call __epx_runtime_start
add  rsp, 32
```

### 2.3 Parameter setup

前 4 个参数从 `rcx`/`rdx`/`r8`/`r9` 写入对应 value slot：

```
mov [rbp+slot], rcx/rdx/r8/r9
```

超过 4 个参数 → 抛出 `MirLowerError`。

### 2.4 Block lowering

函数 lowering 开始时预分配 entry、全部 MIR block 和 return label。block name
只用于 lowering 内找到对应 handle；X64IR 中保存数字 label ID，不构造
`fn_name.block_name` 字符串。block/return 的 debug 文本为 `.L<id>`。

### 2.5 Epilogue

所有非 `main` 函数共享一个 return label（`fn_name.__return`）：

```
add  rsp, aligned_frame   # 仅当 frame > 0
pop  rbp
ret
```

`main` 不走此路径——它直接 `call ExitProcess`。

## 3. Stack model

### 3.1 Slot allocation

`_plan_slots(fn)` 为每个函数计算栈槽：

| 项目 | 分配位置 | 大小 |
|------|----------|------|
| 参数 | `value_slots` | 每个 8 字节 |
| 指令 result (临时值) | `value_slots` | 每个 8 字节 |
| `alloca` 地址 | `addr_slots` | 每个 8 字节 |
| scratch | `scratch_slots` (固定 8 个) | 每个 8 字节，共 64 字节 |

```
next_slot 从 0 开始，每分配一个 slot += 8。
slot 是负值：-8, -16, -24, ...
```

### 3.2 Frame alignment

```
aligned_frame = ((next_slot + 15) // 16) * 16
```

`_lower_call()` 为每次 call 独立分配 shadow space（`sub rsp, 32 + extra`）。函数 frame 只覆盖本函数 slots，不额外预留 caller shadow space。

### 3.3 Value slot vs address slot

| Slot 类型 | 存放内容 | 加载方式 |
|-----------|----------|----------|
| `value_slots[value_id]` | 计算出的值 | `mov reg, [rbp+slot]` |
| `addr_slots[value_id]` | 指向 `alloca` 的指针 | `lea reg, [rbp+slot]` |

函数局部 MIR value 使用正整数 ID。`value_slots`、`addr_slots`、临时槽标志、block-local use counts、可复用标志和 definition block 都是由最大 ID 定长后直接索引的数组；MIR→x64 不再维护 string-keyed map。

## 4. Operand loading

`_load_operand(reg, operand)` 将 MIR operand 的值加载到指定 x64 寄存器中。

| Operand 类型 | 对应寄存器加载 |
|-------------|---------------|
| `ConstBoolOperand(true)` | `mov reg, 1` |
| `ConstBoolOperand(false)` | `mov reg, 0` |
| `ConstIntOperand(value)` | `mov reg, imm(value)` |
| `ConstNullOperand` | `mov reg, 0` |
| `ValueOperand(value_id)` — value slot | `mov reg, [rbp+slot]` |
| `ValueOperand(value_id)` — address slot | `lea reg, [rbp+slot]` |
| `SymbolOperand("argv")` | `mov reg, [_argv]` |
| `SymbolOperand(string_global)` | 构造 string header 到 reg（见下文） |

### 4.1 String global materialization

SymbolOperand 用于字面量字符串。`_load_operand` 会构造一个 Epic string header（`{ptr, len}`）：

```
lea  r11, [data_label]        # string data pointer
lea  reg,  [header_label]     # string header slot
mov  [reg], r11               # header.ptr = data_label
mov  r11, length              # length 立即数
mov  [reg+8], r11             # header.len = length
```

注意：`r11` 是固定的临时寄存器，不经过 slot 分配。如果 `_load_operand` 在 r11 未释放时被嵌套调用可能导致状态污染——但当前 lowering 中 string global 只在 `load` 指令中调用一次，无嵌套。

## 5. Core op lowering

### 5.1 `alloca`

不发射任何 x64 指令。只是分配一个 `addr_slot`，后续 `lea` 访问。

### 5.2 `store`

```
_load_operand("rax", value)
_load_operand("rcx", addr)
mov [rcx], rax                    # qword
mov byte [rcx], al                # i8 (value.type == I8)
```

注意：i8 store 只能使用 `al` 寄存器，由 `_load_operand` 保证值在 `rax`。

### 5.3 `load`

```
_load_operand("rax", operand)     # 加载地址到 rax
movzx rax, byte [rax]             # i8 (zero-extend, byte load)
mov   rax, qword [rax]            # 其他类型
_store_result(inst.result, "rax")
```

**重要语义**：Epic MIR 沿用 LLVM-like spelling，`i8` 表示 8-bit integer / byte lane，不表示 signed source type。Epic public surface 只暴露 `u8` 作为 byte 类型。8-bit load 零扩展到 i64，结果范围 0..255；signedness 由 opcode 表达，不由 `i8` 类型名表达。

### 5.4 Arithmetic

二元运算统一策略：

```
_load_operand("rax", operands[0])   # 左值
_load_operand("rcx", operands[1])   # 右值
ALU_op(rax, rcx)                    # 运算
_store_result(inst.result, "rax")   # 结果存入 value_slot
```

| MIR op | x64 指令 | 说明 |
|--------|----------|------|
| `add` | `add rax, rcx` | |
| `sub` | `sub rax, rcx` | |
| `mul` | `imul rax, rcx` | 有符号，结果截断到 64-bit |
| `sdiv` | `cqo; idiv rcx` | signed quotient in `rax` |
| `srem` | `cqo; idiv rcx; mov rax, rdx` | signed remainder in `rdx` |
| `udiv` | `xor rdx, rdx; div rcx` | unsigned quotient in `rax` |
| `urem` | `xor rdx, rdx; div rcx; mov rax, rdx` | unsigned remainder in `rdx` |
| `and` | `and rax, rcx` | |
| `or` | `or rax, rcx` | |
| `xor` | `xor rax, rcx` | |
| `shl` | `shl rax, cl` | 只使用 cl |
| `sar` | `sar rax, cl` | 只使用 cl |
| `shr` | `shr rax, cl` | 只使用 cl |
| `not` | `test rax, rax; sete al; movzx eax, al` | bool not（不是 bitwise not） |

### 5.5 `icmp.*`

Ordered integer comparisons must spell signedness in the predicate: `icmp.slt` / `icmp.sle` / `icmp.sgt` / `icmp.sge` for signed comparisons and `icmp.ult` / `icmp.ule` / `icmp.ugt` / `icmp.uge` for unsigned comparisons. `icmp.eq` and `icmp.ne` are bitwise equality predicates and do not carry signedness.

```
_load_operand("rax", operands[0])
_load_operand("rcx", operands[1])
cmp rax, rcx
setcc al
movzx eax, al
_store_result(inst.result, "rax")
```

| icmp 谓词 | setcc 指令 |
|-----------|-----------|
| `eq` | `sete` |
| `ne` | `setne` |
| `lt` | `setl` |
| `gt` | `setg` |
| `le` | `setle` |
| `ge` | `setge` |

均使用**有符号**比较。

### 5.6 `ptrtoint`

```
_load_operand("rax", operands[0])   # 指针值
_store_result(inst.result, "rax")   # 作为 i64 存入
```

不涉及截断或符号问题。

### 5.7 `gep`

GEP lowering 依赖于 source type 和 indices：

| Source type | index 数量 | 行为 |
|-------------|-----------|------|
| `struct` | 1 | `base_ptr + index0 * sizeof(struct)` |
| `struct` | 2 | `base_ptr + index0 * sizeof(struct) + field_offset(index1)` |
| `i8` | 1 | `base_ptr + index0 * 1` |
| `i64`/`ptr` | 1 | `base_ptr + index0 * 8` |
| `array` | 1 | `base_ptr + index0 * sizeof(elem)` |

```
_load_operand("rax", operands[0])   # 基址
# 处理每个 index
for each index:
  if index is ConstIntOperand:
    rax += index.value * scale         # imm8 用 add rax, imm；否则 mov rcx, imm; add rax, rcx
  else:
    _load_operand("rcx", index)
    if scale == 8:  rcx = rcx*8       # scale_rcx_by_8: add rcx x 3
    rax += rcx                         # add rax, rcx
_store_result(inst.result, "rax")
```

**scale_rcx_by_8** 通过三次 `add rcx, rcx` 实现 `rcx *= 8`。这只在 scale == 8 时使用，scale == 1 时直加。

Struct field offset 通过 `program.structs[struct_name].field_by_index(index).offset` 查表获取，field index 必须是编译期常量。

## 6. Call lowering

`_lower_call(inst)` 实现 Windows x64 ABI 调用序列：

```
# 前四个参数放入寄存器
_load_operand("rcx", operands[0])   # 第一个参数
_load_operand("rdx", operands[1])   # 第二个参数
_load_operand("r8",  operands[2])   # 第三个参数
_load_operand("r9",  operands[3])   # 第四个参数

# 分配 shadow space + 栈参数空间
frame = 32 + ((max(0, arg_count - 4) * 8 + 15) // 16) * 16
sub rsp, frame

# 第 5+ 个参数写入栈
for idx, operand in enumerate(operands[4:]):
  _load_operand("rax", operand)
  mov [rsp+32+idx*8], rax

# 调用
call Symbol(callee_name)

# 恢复栈
add rsp, frame

# 保存返回值（如有）
if inst.result is not None:
  _store_result(inst.result, "rax")
```

### 6.1 Callee symbol

`Symbol(callee)` 的 `callee` 直接取 `inst.callee` 字符串。可以是：

- 用户函数名（如 `main`、`foo`）
- backend-owned WinAPI import 名（如 `ExitProcess`、`HeapAlloc`）
- source extern 编码名（`__ep_import$<dll>$<symbol>`）
- Runtime helper 名（如 `__ep_print_str`、`__epx_alloc`）
- `__epx_alloc`

### 6.2 Frame alignment

Shadow space (32) 已包含在 frame 计算中。栈参数按 16 字节对齐计算 extra。

## 7. Terminator lowering

### 7.1 `br`

```
jmp LabelRef(block_label_id)
```

### 7.2 `condbr`

```
_load_operand("rax", cond)
test rax, rax
jnz  LabelRef(fn_name.then_target)
jmp  LabelRef(fn_name.else_target)
```

注意：condbr 对 `bool` 值检查 "非零即真"。

### 7.3 `ret`

| 函数 | 行为 |
|------|------|
| `main` (有值) | `mov rcx, rax; sub rsp, 32; call ExitProcess` |
| `main` (无值) | `mov rcx, 0; sub rsp, 32; call ExitProcess` |
| 非 main (有值) | `_load_operand("rax", value); jmp return_label` |
| 非 main (无值) | `jmp return_label` |

## 8. Runtime boundary

### 8.1 Runtime data

`emit_runtime_data()` 在 `.data` section 生成：

- `_written`: 4-byte zeroed integer slot
- `_heap: qword` (8 bytes zero) — 进程堆句柄
- `_argv: qword` (8 bytes zero) — 命令行参数数组
- `_newline: byte 0x0a`
- `_cstr_panic_prefix: "panic line "`
- `_cstr_panic_suffix: ": invalid cstr"`
- runtime string globals injected by MIR helpers, such as
  `str.runtime.bool.true` / `str.runtime.bool.false`
- 每个程序全局 string 的 `data_label` 和 `header_label`

### 8.2 Startup hook

`__epx_runtime_start` 在 `main` 的 prologue 中被调用：

```
push  rbp
mov   rbp, rsp
sub   rsp, 32
call  GetProcessHeap
add   rsp, 32
mov   [_heap], rax
sub   rsp, 32
call __epx_argv_init
add   rsp, 32
mov   [_argv], rax
pop   rbp
ret
```

### 8.3 Runtime helper emission

`append_runtime_helpers()` 在当前实现下无条件发射所有 helper：

- `__epx_alloc` (x64 primitive)
- x64 primitives and still-x64 helpers:
- `cstr` (`__ep_cstr`)
- `__ep_write_file` / `__ep_read_file`
- `__epx_argv_init`
- `__ep_print_str` / `__ep_print_newline`
- `__epx_slice_oob`

MIR-implemented helpers such as `__ep_str_from_bool`,
`__ep_str_cat`, `__ep_str_eq`, `__ep_str_slice`,
`__ep_slice_u8_*`, `__ep_slice_i64_*`, `__ep_slice_ptr_*`,
and `__ep_slice_u8_extend` are
ordinary `MirFunction`s loaded from `runtime/mir/helpers.mir` and injected by
`bootstrap/mir_runtime_helpers.py` in the Python compiler and `src/mir_runtime.ep`
in the self-hosted compiler. After injection, both compilers prune unreachable
MIR functions from the final program; roots include `main` and MIR/Epic
functions directly called by hand-written x64 runtime
(`__ep_str_from_i64`, `__ep_slice_u8_alloc`). They no longer have same-named x64 fallback bodies.
`bytes(str)` and `str(u8[])` are lowered as identity casts, so they do not
require MIR runtime functions.
Remaining x64 labels and function bodies are hand-written in `mir_to_x64.py`
`_emit_*()` methods.

Current helper ownership is documented by this contract plus `docs/builtin-inventory.md`. The old standalone MIR runtime helper migration plan was removed after the numeric/string helper migration completed.

## 9. Known debts

### 9.1 Unused helpers

No known unused runtime helper label is intentionally emitted. The old `__epx_putc` label and `_putc_buf` data were removed after `putc` left the public surface.

### 9.2 No register allocation

所有值走栈槽，第一版不做寄存器分配。性能不是目标。

### 9.3 No callee-saved register preservation

当前 lowering 不使用被调用者保存的寄存器（`rbx`、`rsi`、`rdi`、`r12`–`r15`），因此不需要保存它们。

### 9.4 Dynamic GEP scale

`_add_scaled_index` 在动态 index 且 `scale != 1` / `scale != 8` 时抛出 `MirLowerError`。常量 index 不受此限制，因为 offset 会在 lowering 时折叠成立即数。当前这足够覆盖 `u8` buffer（scale=1）、word/pointer array（scale=8）和常量 struct field offset；未来若支持紧凑 4-byte integer array、value struct array，或更通用 aggregate GEP，需要补通用 `index * element_size` 地址计算。scale=8 仅通过三次 `add rcx, rcx` 实现，不是真正的 shift。

### 9.5 `_add_rax_imm` only uses current machine-supported immediates

`_add_rax_imm` emits single-instruction `add rax, imm` only for signed imm8
values because the current machine encoder supports `add reg, imm8`. Larger
offsets still lower as `mov rcx, imm; add rax, rcx` until the encoder grows
imm32 support.

### 9.6 No `.data` relocations

`machine.py` 支持 `data_relocs` API 但当前不发射任何 `.data` section relocations。string header 初始化由 runtime `_load_operand` 以代码形式生成（lea + mov 序列），而非数据重定位。
