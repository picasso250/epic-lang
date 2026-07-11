# Epic LowIR / X64IR 规格

本文档记录当前 Python machine backend 的真实合约。它不是通用 x64
汇编器说明，也不是未来完整后端设计；目标是给 `MIR -> X64IR ->
machine bytes -> COFF -> PE` 这条线建立可测试边界。

对应实现：

- `bootstrap/mir.py`: typed MIR data model and validator。
- `bootstrap/ast_to_mir.py`: AST -> MIR。
- `bootstrap/mir_to_x64.py`: MIR -> structured X64IR。
- `bootstrap/mir_runtime_helpers.py`: MIR runtime injection and preparation。
- `bootstrap/x64.py`: X64IR data model and text pretty printer。
- `bootstrap/machine.py`: X64IR -> machine bytes + COFF reloc records。
- `bootstrap/coff.py`: minimal AMD64 COFF object writer。
- `bootstrap/link.py`: minimal PE linker for generated COFF objects。

## 1. 分层边界

当前 machine backend 的主路径是：

```text
AST
  -> MIR
  -> X64Program
  -> MachineObjectBuilder(text bytes, data bytes, relocs, symbols)
  -> COFF obj
  -> bootstrap/link.py / lld-link
  -> PE exe
```

`compile_files()` 仍会把 `X64Program.text()` 写到 `.asm` 文件，但这个文件只是
debug pretty print，不参与 obj 生成。Python reference compiler 已移除
`--backend asm`，旧 Python asm 后端归档在 tag `python-asm-archive-2026-07-02`。

Runtime preparation happens before MIR lowering:

- runtime definitions and globals are injected into the program as MIR；
- startup and null-dereference checks are explicit MIR calls；
- reachability pruning keeps only functions reachable from `main`；
- `MirLower` emits program globals and lowers the remaining MIR without appending backend helpers。

### 1.1 MIR

MIR 是语义层：typed values、basic blocks、terminators、load/store、gep、call。
目标 MIR 合约见 `docs/mir-design.md`：pointer 是 opaque `ptr`，aggregate 操作要分解成 `gep/load/store/call/branch`。
本文档下方列出的 Epic-specific MIR ops 是当前 Python prototype 的真实状态，不是目标 MIR 设计。

### 1.2 X64IR / LowIR

X64IR 是当前 LowIR：它已经显式包含寄存器、栈槽、label、data item、
symbol reference、Windows x64 ABI 调用序列。它仍是结构化对象，不是 NASM
文本。

`X64Program.text()` 只用于审查和 golden tests。新增功能不能依赖解析这份文本。

### 1.3 MachineObjectBuilder

Machine layer 把 X64IR 编成：

- `.text` bytes
- `.data` bytes
- text labels
- data labels
- text relocations
- COFF symbols

Self-hosted `MachineObject` stores each relocation as an offset plus an already
resolved COFF symbol index. Symbol names are consumed inside `src/machine.ep`;
`src/coff.ep` only serializes integer indexes and does not rebuild a name map.

它只支持当前 lowering 实际会生成的指令和操作数组合。

## 2. X64Program 数据模型

`X64Program` 单调分配 `X64Label { id, symbol_name }`，`items` 是顺序 item
列表。匿名 label 只表示函数内控制流；带 `symbol_name` 的 label 同时是
linker 可见的 text symbol。创建、绑定和引用分别使用
`new_label/new_symbol_label`、`bind_label`、`label_ref`，不存在字符串 label API。

| Item | 含义 |
| --- | --- |
| `X64Global(name)` | 声明全局符号；当前 machine layer 不使用它决定导出，只依赖 label symbols。 |
| `X64Extern(name)` | 声明外部符号；当前 machine layer 收集但不验证引用必须先声明。 |
| `X64Section(name)` | 切换当前 section；当前支持 `.text`、`.data`。 |
| `X64Label(id, symbol_name)` | 在当前 section 绑定已分配的 label handle。 |
| `X64Inst(op, operands)` | `.text` 指令。 |
| `X64DataBytes(label, values)` | `.data` 内定义字节序列。 |
| `X64DataZero(label, count)` | `.data` 内定义零初始化字节。 |

操作数：

| Operand | 含义 |
| --- | --- |
| `Reg(name)` | 寄存器。 |
| `Imm(value)` | 整数立即数。 |
| `Symbol(name)` | call target 或外部/section symbol reference。 |
| `LabelRef(label)` | 持有数字 label handle 的 branch target。 |
| `Mem(base, disp, symbol, size)` | base+disp memory 或 RIP-relative symbol memory。 |

`Mem(size=1)` 打印 `byte [...]`，`Mem(size=8)` 打印 `qword [...]`。
匿名 label 的 debug 文本是 `.L<id>`；函数入口和 runtime helper 等 named
label 保留 `symbol_name`，因此其汇编审查文本和链接名稳定。

## 3. Windows x64 ABI 约定

MIR lowering 当前固定面向 Windows x64：

- 前四个参数使用 `rcx`、`rdx`、`r8`、`r9`。
- 第五个及之后参数写入 call frame 的 `[rsp+32+index*8]`。
- 每次 call 前预留 32 字节 shadow space。
- 返回值在 `rax`。
- `main` 降成 PE entry symbol `_start`。
- `main` starts with an injected MIR call to `__ep_runtime_start` to cache the process heap and initialize `argv`。
- `main` 的 `ret value` 降成 `ExitProcess(value)`，不走普通 `ret`。
- Win32 `LPDWORD` output 参数只写 32 位。当前 helper 如果复用 8 字节栈槽
  存放这类输出，必须在 call 前清零整个 qword，或者后续改成显式 32-bit
  zero-extend load。
- 非 `main` 函数使用 prologue / epilogue：

```text
push rbp
mov rbp, rsp
sub rsp, aligned_frame
...
add rsp, aligned_frame
pop rbp
ret
```

当前 frame 规划很简单：

- 每个 MIR 参数、临时 value、`alloca` address 都占 8 字节栈槽。
- lowering 额外保留 8 个 scratch slots。
- frame 大小按 `((next_slot + 15) // 16) * 16` 对齐。
- 第一版不做寄存器分配。

## 4. 当前 MIR lowering 覆盖

核心 MIR ops：

| MIR op | X64IR 降级方向 |
| --- | --- |
| `alloca` | 只分配栈槽，不发指令。 |
| `store` | operand -> `rax`，再 `mov [rbp+slot], rax`。 |
| `load` | `mov rax, [rbp+slot]`，再存入结果栈槽。 |
| `add/sub/and/or/xor` | 左值 -> `rax`，右值 -> `rcx`，二地址 ALU。 |
| `mul` | `imul rax, rcx`。 |
| `sdiv/srem` | `cqo; idiv rcx`，`srem` 取 `rdx`。 |
| `udiv/urem` | `xor rdx, rdx; div rcx`，`urem` 取 `rdx`。 |
| `shl/sar/shr` | 左值 -> `rax`，右值 -> `rcx`，使用 `cl`。 |
| `not` | `test rax, rax; sete al; movzx eax, al`。 |
| `icmp.*` | `cmp rax, rcx; setcc al; movzx eax, al`；ordered predicates use signed `setl/setle/setg/setge` or unsigned `setb/setbe/seta/setae` explicitly. |
| `call` | Windows x64 call sequence。 |
| `br` | `jmp label`。 |
| `condbr` | `test rax, rax; jnz then; jmp else`。 |
| `ret` | `ExitProcess` for `main`，普通函数跳转到 shared return label。 |

## 5. 当前 machine instruction subset

支持的寄存器：

- 64-bit: `rax rcx rdx rbx rsp rbp rsi rdi r8 r9 r10 r11`
- 32-bit immediate move target: `eax ecx edx`
- 8-bit: `al cl dl r8b r9b r10b r11b`

当前 encoder 支持的指令形态：

| Instruction | Supported forms |
| --- | --- |
| `push` | `push rbp`, `push r8` |
| `pop` | `pop rdx`, `pop rbp` |
| `ret` | no operands |
| `sub/add` | `sub rsp, imm`, `add rsp, imm` |
| `call` | `call Symbol` |
| `jmp` | `jmp LabelRef` |
| `jo/jz/jnz/jl/jge/jle/jg/jns` | `jcc LabelRef` |
| `cqo` | no operands |
| `idiv/div` | `idiv rcx`, `div rcx` |
| `imul` | `imul rax, rcx` |
| `neg` | `neg rax` |
| `cmp` | `cmp r64, r64`, `cmp r64, imm32/imm8` |
| `sete/setne/setg/setl/setge/setle` | target `al` |
| `movzx` | `movzx eax, al` |
| `movsx` | `movsx r64, byte [r64+disp]` |
| `movzx` | `movzx r64, byte [r64+disp]` (also `movzx eax, al` for setcc) |
| `test` | intended contract: `test r64, same r64` |
| `xor` | `xor r64, r64` |
| `shl/sar/shr` | `op rax, cl` |
| `inc/dec` | `inc r64`, `dec r64` |
| `add/sub/and/or/xor` | `op r64, r64` |
| `add` | `add r64, imm8`, `add r8, imm8` |
| `mov` | forms listed below |
| `lea` | `lea r64, [symbol]`, `lea r64, [base+disp]` |

`mov` forms:

| Form | Notes |
| --- | --- |
| `mov r64, imm32/imm64` | imm64 only when outside signed 32-bit range. |
| `mov eax/ecx/edx, imm32` | 32-bit target subset only. |
| `mov r64, r64` | register move. |
| `mov r64, qword [base+disp]` | base memory load. |
| `mov r64, qword [symbol]` | RIP-relative symbol load relocation. |
| `mov [base+disp], r64` | base memory store. |
| `mov [base+disp], r8` | byte store when source is 8-bit reg. |
| `mov [base+disp], imm` | byte or qword-sized immediate store depending on `Mem.size`. |
| `mov [symbol], r64` | RIP-relative symbol store relocation. |
| `mov [symbol], al` | RIP-relative byte store relocation. |

### 5.1 Instruction form contract

以下规则是 `machine.py` 当前 encoder 的实际限制。**超出此合约的指令形式通常会被 `X64Validator` 拒绝或抛出 `MachineBackendError`**；但 validator 不是完整 x64 verifier，新增指令形态必须同时补 validator 和 encoder 测试。

#### Register contract

| 类别 | 支持 | 不支持 |
|------|------|--------|
| 64-bit | `rax rcx rdx rbx rsp rbp rsi rdi r8 r9 r10 r11` | `r12 r13 r14 r15` — encoder 未实现 REX.B 编码 |
| 32-bit | `eax ecx edx` | `ebx esi edi r8d`… — 仅用于 `mov` 的 imm32 形式 |
| 8-bit | `al cl dl r8b r9b r10b r11b` | `bl sil dil r12b`… — encoder 未实现低 8-bit 编码 |

#### `mov` contract

| 形式 | 状态 | 说明 |
|------|------|------|
| `mov al, byte [mem]` | ❌ 不支持 | `movzx rax, byte [mem]` 代替（零扩展），或 `movsx rax, byte [mem]`（符号扩展） |
| `mov byte [mem], imm` | ✅ 支持 | 需 `Mem(size=1)` |
| `mov qword [mem], imm` | ✅ 支持 | 需 `Mem(size=8)` |
| `mov r64, byte [mem]` | ❌ 不支持 | 使用 `movsx r64, byte [mem]` |
| `movzx r64, byte [mem]` | ✅ 新增 | 零扩展 byte load；`0F B6 /r` + REX.W |
| `mov r64, dword [mem]` | ❌ 不支持 | 当前只有 qword 和 byte 两种 size |
| `mov [mem], dword` | ❌ 不支持 | 同上 |
| `mov [rsp+disp], r64` | ✅ 支持 | 通过 `Mem("rsp", disp)` |
| `mov [rbp+disp], r64` | ✅ 支持 | 通过 `Mem("rbp", disp)` |
| `mov [reg+disp], r64` | ✅ 支持 | base 需属于当前 REG64 集合（`rax`–`r11`） |

#### Byte load/store contract

当前 byte 访问的合约：

| 操作 | 支持形式 |
|------|----------|
| byte load (zero-extend) | `movzx r64, byte [mem]` |
| byte store (8-bit reg) | `mov byte [mem], al/dl/r8b/r9b/r10b/r11b` |
| byte store (immediate) | `mov byte [mem], imm8` |
| byte load (sign-extend) | `movsx r64, byte [mem]` (internal helpers only) |

#### ALU contract

| 形式 | 状态 | 说明 |
|------|------|------|
| `add/sub/and/or/xor r64, r64` | ✅ | 二地址运算 |
| `add/sub r64, imm8` | ✅ | 仅有 `add` 支持 imm8；`sub` 当前未直接使用此形式 |
| `add r8, imm8` | ✅ | byte arithmetic |
| `cmp r64, r64` | ✅ | |
| `cmp r64, imm32/imm8` | ✅ | imm32 和 imm8 均支持 |
| `test r64, r64` | ✅ | 当前合约只允许两个 operand 相同寄存器 |
| `test r64, imm` | ❌ 不支持 | |
| `imul rax, rcx` | ✅ | 仅此一种支持形式 |
| `cqo; idiv rcx` | ✅ | signed divide 的标准形式 |
| `div rcx` | ✅ | unsigned divide，used by runtime helpers |

#### Memory addressing contract

| 形式 | 状态 | 说明 |
|------|------|------|
| `[base+disp]` | ✅ | base 需属于当前 REG64 集合（`rax`–`r11`）；lowering 中 `rsp`/`rbp` 最常见，但 runtime helper 也使用 `rcx`、`rsi`、`rdi`、`r8`–`r11` 等 |
| `[symbol]` | ✅ | RIP-relative symbol load/store |
| `[base+index*scale+disp]` | ❌ | SIB 未实现 |
| `[base]` | ✅ | disp=0 的 `Mem(base, 0)` |
| `Mem(size=N)` | ✅ | size=1 (byte), size=8 (qword) — 仅支持这两种 |

#### Branch/call contract

| 形式 | 状态 | 说明 |
|------|------|------|
| `jmp LabelRef` | ✅ | 内部 branch fixup |
| `jcc LabelRef` | ✅ | 条件跳转 fixup |
| `call Symbol` | ✅ | 外部符号或 section 符号；E8 rel32 |
| `call LabelRef` | ❌ 不支持 | 当前 call 目标必须是 `Symbol`，内部 label 用 `jmp` |
| `jmp Symbol` | ❌ 不支持 | 必须使用 `LabelRef` |

#### 可执行但应避免的形式

这些形式在 encoder 中能工作，但语义容易混淆或未来可能移除：

- `mov [rsp+disp], r8` — byte store to stack (当前没有 MIR lowering 路径产生此形式，但 encoder 支持)
- `mov [symbol], imm` — 当前 `machine.py` 中 RIP-relative 形式的 imm store 只在 `.data` section 场景测试过

Current unsupported examples:

- Generic SIB/index addressing.
- Arbitrary memory-to-memory ops.
- `.data` relocations.
- Direct absolute addressing.
- Vector/SIMD.
- Floating point.
- Callee-saved register preservation beyond the fixed prologue model.

## 6. Fixup and relocation contract

Internal branch fixups:

- `jmp` emits `E9 rel32 placeholder`。
- `jcc` emits `0F 8? rel32 placeholder`。
- `MachineBuilder` 按 `program.label_count` 分配 `label_offsets` 和
  `label_defined`；fixup 保存 label handle，并用 ID 直接索引目标 offset。
- If the target label is bound in `.text`, machine layer patches the signed rel32
  displacement directly，不扫描字符串 label 表。
- Displacement is computed from the address after the 4-byte immediate.
- 重复绑定、越界 ID、未绑定匿名 label 是 backend error。未绑定 named label
  会变成 relocation，供 standalone function lowering 使用。

External or section symbol references:

- `call Symbol` emits `E8 00 00 00 00` and a text relocation at the rel32 field.
- `lea reg, [symbol]` emits RIP-relative addressing and a text relocation.
- `mov reg, [symbol]` and `mov [symbol], reg` also use text relocations.
- If a branch target is not a local text label, it is left as a text relocation.

COFF contract:

- `bootstrap/coff.py` writes exactly two sections: `.text` and `.data`。
- Relocation type is currently always `IMAGE_REL_AMD64_REL32`。
- Symbols use section number 1 for `.text`, 2 for `.data`, 0 for external。
- 只有 named text label 进入 symbol table；匿名 block/return label 不进入 COFF。
- Symbol 顺序固定为 named text、data、按 ASCII 排序的 extern。
- Python reference backend 使用 CPython 原生 `dict` / `set` 保存 symbol name，
  `bootstrap/coff.py` 在序列化时建立 COFF symbol index。
- Self-hosted backend 使用固定容量、u64 FNV hash 的开放寻址
  `MachineNameIndex` 做私有查询，relocation 在 `src/machine.ep` 中直接取得
  最终 COFF symbol index；索引从不参与迭代，因此 hash 桶布局不会影响
  输出顺序或自举固定点。
- `data_relocs` exists in the writer API but current machine backend does not emit it。

`bootstrap/link.py` contract:

- Reads the generated COFF object.
- Builds import thunks in `.text`。
- Patches REL32 references to local section symbols or import thunks。
- Currently builds import metadata for `KERNEL32.dll` only。

## 7. Golden tests

Layered golden tests should lock each boundary separately:

| Layer | Test shape |
| --- | --- |
| MIR text | Hand-written MIR -> `program.text()` exact string. |
| MIR -> X64IR | Hand-written MIR function -> `X64Program.text()` exact string. |
| X64IR text | Hand-written X64Program -> exact pretty print. |
| X64IR -> machine | Hand-written X64Program -> exact bytes, labels, data, relocs. |
| machine -> executable | Small compiled example -> run and assert exit/stdout. |

Current files:

- `tests/mir/test_mir.py`: MIR text and validation smoke test。
- `tests/x64/test_x64_layers.py`: X64 pretty print, MIR-to-X64 function lowering, and
  X64-to-machine bytes/fixups。
- `tests/examples/run.py`: executable-level acceptance for the Python machine backend。

The lower layers should stay small. Do not use full examples to test a single
encoding rule; use a tiny X64Program with one or two labels and one relocation.

## 8. Design audit

The current route is still sound, but several choices should be corrected before
the Epic implementation grows around them.

### 8.1 Runtime is represented in MIR

Runtime helper bodies, globals, startup, allocation, I/O, argv parsing, panic,
and safety checks are represented as ordinary MIR definitions and calls.
`bootstrap/mir_runtime_helpers.py` and `src/mir_runtime.ep` inject the shared
runtime, insert preparation calls, and prune unreachable functions.

`bytes(str)` and `str(u8[])` are identity casts in lowering, not runtime helper
calls.

Base helper bodies are bundled in `runtime/mir/helpers.mir`; composite helpers
are written in `runtime/*.ep`. Python and self-hosted compilers consume the same
sources. The x64 layer owns only ABI lowering, program data emission, and WinAPI
imports.

### 8.2 X64Program validator exists

`validate_x64_program(program)` now runs before machine encoding through
`MachineObjectBuilder.__init__()`. The two previously risky forms are covered:

- `test a, b` is rejected unless both operands are the same register.
- `add r64, imm` rejects immediates outside signed imm8 for the current encoder path.
- `call Symbol` requires a defined or declared symbol.

Recommended next step: keep validator tests next to each newly supported X64IR
instruction form.

### 8.3 MachineObjectBuilder lacks a public build result

The public API writes an obj file. Unit tests that want text bytes, data bytes,
labels, and relocs must reach into private methods.

Recommended next step: expose a small `build_machine_object(program)` result
object and let `write_machine_obj()` wrap it.

### 8.4 Struct metadata on MirProgram

`MirProgram.structs` carries typed `MirStruct` layout metadata for aggregate
`gep` lowering. Field lookup uses ordered `MirField` entries so field index and
byte offset stay part of the MIR contract.

### 8.5 Symbol spelling contract

MIR object model stores raw module symbols such as `main`, `__ep_str_eq`,
`ExitProcess`, and `str.1`. The `@` sigil is reserved for a future text MIR
syntax/parser and must not be stored in `MirFunction.name`, `MirExtern.name`,
`MirGlobal.name`, or `SymbolOperand.name`. Local SSA values also use raw names in `MirValue.name` / `MirParam.name`; the `%` sigil belongs to text MIR printing/parsing only.

### 8.6 Self-hosted compiler uses the MIR/X64IR/machine path

The old NASM-oriented driver and `src/codegen_support.ep` / `src/codegen.ep` backend line have been removed. The current `src/epic.ep` is a new active driver: it runs the Epic-written frontend, lowers through MIR and X64IR, emits machine code and COFF through `src/machine.ep` and `src/coff.ep`, and links through `src/link.ep`.

`compiler_sources.py` defines the canonical source order used to build this compiler. `test_bootstrap_fixed_point.py` repeatedly compiles the self-hosted compiler with the generated compiler and verifies that later generations stabilize.

