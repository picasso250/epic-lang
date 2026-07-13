# MIR Lowering Contract

## Scope

本文档记录 **当前实现** 的 MIR → X64Program lowering 规则。它不是目标设计，也不是理想合约，而是 `src/mir_to_x64.ep` 的真实行为。

目标 MIR 设计见 `docs/mir-design.md`。X64IR 合约见 `docs/x64-instruction-subset.md`。

```text
MIR -> MirToX64Lower -> X64Program -> machine -> COFF -> PE
```

## 1. 总体流程

```
mir_to_x64_lower_program(program):
  ├─ x64.global("_start")
  ├─ x64.extern(...) for each referenced WinAPI/source extern
  ├─ x64.section(".data")
  ├─ emit_program_data(x64, program)    # MIR globals、string header
  ├─ x64.section(".text")
  └─ for each fn: _lower_function(fn)
```

lowering 后，`X64Program` 包含：
1. 数据段：MIR program globals 与 string headers
2. 代码段：prune 后保留的所有 MIR functions

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

对 `main` 的启动初始化在 MIR preparation 阶段插入为 entry block 的第一条普通调用：

```
call void __ep_runtime_start()
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

`main` 不走此路径——它直接调用编码导入 `__ep_import$kernel32.dll$ExitProcess`。

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

不发射任何 x64 指令，只分配一个 `addr_slot`。当 load/store 的地址 operand 直接是该
`alloca` result 时，lowering 使用 `[rbp+addr_slot]` 直接访问，不再先发射 `lea`；GEP、
parameter、global 和普通 pointer value 仍先加载地址再间接访问。

### 5.2 `store`

```
_load_operand("rax", value)
_load_operand("rcx", addr)
mov qword [rcx], rax              # i64 / ptr
mov dword [rcx], eax              # i32 / u32
mov word [rcx], ax                # i16 / u16
mov byte [rcx], al                # i8
```

store width 由 `inst.typ` 的 memory access type 决定；value 本身仍可使用 64-bit representation。

### 5.3 `load`

```
_load_operand("rax", operand)     # 加载地址到 rax
movzx  rax, byte [rax]            # i8
movsx  rax, word [rax]            # i16
movzx  rax, word [rax]            # u16
movsxd rax, dword [rax]           # i32
mov    eax, dword [rax]           # u32, architectural zero extension
mov    rax, qword [rax]           # i64 / ptr
_store_result(inst.result, "rax")
```

memory access type carries lane width and signed load behavior. MIR result values remain normalized 64-bit values;
`i8` is the unsigned byte lane used by public `u8`/`bool` storage.

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
| `slt` | `setl` |
| `sgt` | `setg` |
| `sle` | `setle` |
| `sge` | `setge` |
| `ult` | `setb` |
| `ugt` | `seta` |
| `ule` | `setbe` |
| `uge` | `setae` |

Ordered predicate 的 signedness 由 opcode 明确表达。

当 block 最后一条 instruction 是任一整数 `icmp`，且紧随的 `condbr` 直接消费该
block-local result 时，lowering 发射 `cmp + jcc`，不再物化 `setcc + movzx` bool。
映射为 `jz/jnz`、signed `jl/jle/jg/jge` 或 unsigned `jb/jbe/ja/jae`。普通 value use 仍保持
原有物化路径。

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
| `i16`/`u16` | 1 | `base_ptr + index0 * 2` |
| `i32`/`u32` | 1 | `base_ptr + index0 * 4` |
| `i64`/`ptr` | 1 | `base_ptr + index0 * 8` |
| `array` | 1 | `base_ptr + index0 * sizeof(elem)` |

```
_load_operand("rax", operands[0])   # 基址
# 处理每个 index
for each index:
  if index is ConstIntOperand:
    rax += index.value * scale         # imm8 用 add rax, imm；否则 mov rcx, imm; add rax, rcx
  else if scale == 1 or scale == 8:
    _load_operand("rcx", index)
    if scale == 8: rcx = rcx * 8
    rax += rcx
  else:
    preserve base
    _load_operand("rax", index)
    rax *= scale
    rax += preserved base
_store_result(inst.result, "rax")
```

动态 GEP 支持任意正 element size；1 和 8 保留简单 fast path，其余使用 `imul`。

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
- Windows API / source extern 编码名（`__ep_import$<dll>$<symbol>`）
- Runtime helper 名（如 `__ep_print_str`、`__ep_alloc`）

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
| `main` (有值) | `mov rcx, rax; sub rsp, 32; call __ep_import$kernel32.dll$ExitProcess` |
| `main` (无值) | `mov rcx, 0; sub rsp, 32; call __ep_import$kernel32.dll$ExitProcess` |
| 非 main (有值) | `_load_operand("rax", value); jmp return_label` |
| 非 main (无值) | `jmp return_label` |

## 8. Runtime boundary

### 8.1 Program data

`emit_program_data()` 在 `.data` section 按 MIR globals 生成。普通字符串字面量和 `embed` 文件内容使用同一 global 表示：

- 无初始化 global：8-byte zero slot，例如 `argv` 和 cached process `heap`
- ptr/string global：零结尾 data bytes 与 24-byte header
- scalar global：8-byte little-endian value

### 8.2 Startup hook

MIR preparation 在 `main` entry 插入 `__ep_runtime_start`。该 MIR helper 缓存
`GetProcessHeap()` 的结果，再调用 `__ep_argv_init` 并把结果存入 `argv`
global；`__ep_alloc` 直接读取 cached heap，随后与普通函数一样 lowering。

### 8.3 Runtime helper emission

Helpers such as `__ep_alloc`, `__ep_print_str`, `__ep_print_newline`,
`__ep_str_from_bool`,
`__ep_str_cat`, `__ep_str_eq`, `__ep_str_slice`,
`__ep_slice_u8_*`, `__ep_slice_i64_*`, `__ep_slice_ptr_*`,
and `__ep_slice_u8_extend` are
ordinary `MirFunction`s loaded from the embedded `runtime/mir/helpers.ir` bundle and
injected by `src/mir_runtime.ep`. All standard composite helpers, including `runtime/file.ep`,
come from Epic sources embedded by `src/runtime_bundle.ep` and merged with user source before
sema. Canonically identical repeated extern declarations are folded; conflicts are rejected.
After injection, the compiler prunes unreachable MIR functions from the final
program starting at `main`; startup and helper dependencies remain reachable
through explicit MIR calls.
`bytes(str)` and `str(u8[])` are lowered as identity casts. `cptr(str/u8[])`
loads the aggregate `data` field, while `cptr(FFI-safe struct)` returns the payload
pointer unchanged; deprecated `cstr(str)` uses the same lowering. None require a MIR
runtime function or runtime validation. Active `__ep_read_file` / `__ep_write_file` bodies come only from `runtime/file.ep` and
use `cptr(str/u8[])` plus explicit pointer-typed WinAPI externs. Their MIR signatures match the
public builtins exactly: one path operand for read, and path plus data operands for write.
`runtime/mir/helpers.ir` contains no same-named fallback bodies.
The x64 backend contains only generic instruction lowering in `src/mir_to_x64.ep`.

Current helper ownership is documented by this contract plus `docs/builtin-inventory.md`. The old standalone MIR runtime helper migration plan was removed after the numeric/string helper migration completed.

## 9. Known debts

### 9.1 Unused helpers

No known unused runtime helper label is intentionally emitted. The old `__epx_putc` label and `_putc_buf` data were removed after `putc` left the public surface.

### 9.2 No register allocation

所有值走栈槽，第一版不做寄存器分配。性能不是目标。

### 9.3 No callee-saved register preservation

当前 lowering 不使用被调用者保存的寄存器（`rbx`、`rsi`、`rdi`、`r12`–`r15`），因此不需要保存它们。

### 9.4 Dynamic GEP scale

动态 index 已支持任意显式 element size。scale 1/8 使用直接加法或三次 doubling；其他 scale 使用
`imul index, element_size` 后与 preserved base 相加。struct stride 必须来自 MIR 的显式 layout size，
不能由字段数量推导。

### 9.5 `_add_rax_imm` only uses current machine-supported immediates

`_add_rax_imm` emits single-instruction `add rax, imm` only for signed imm8
values because the current machine encoder supports `add reg, imm8`. Larger
offsets still lower as `mov rcx, imm; add rax, rcx` until the encoder grows
imm32 support.

### 9.6 No `.data` relocations

`machine.py` 支持 `data_relocs` API 但当前不发射任何 `.data` section relocations。string header 初始化由 runtime `_load_operand` 以代码形式生成（lea + mov 序列），而非数据重定位。
