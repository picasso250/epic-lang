# Epic LowIR / X64IR 规格

本文档记录当前 Epic machine backend 的真实合约。它不是通用 x64
汇编器说明，也不是未来完整后端设计；目标是给 `MIR -> X64IR ->
machine bytes -> COFF -> PE` 这条线建立可测试边界。

对应实现：

- `src/mir.ep`: typed MIR data model and validator。
- `src/ast_to_mir.ep`: AST -> MIR。
- `src/mir_to_x64.ep`: MIR -> structured X64IR。
- `src/mir_runtime.ep`: MIR runtime injection and preparation。
- `src/x64.ep`: X64IR data model and text pretty printer。
- `src/machine.ep`: X64IR -> machine bytes + COFF reloc records。
- `src/coff.ep`: minimal AMD64 COFF object writer。
- `src/link.ep`: minimal PE linker for generated COFF objects。

## 1. 分层边界

当前 machine backend 的主路径是：

```text
AST
  -> MIR
  -> X64Program
  -> MachineObjectBuilder(text/rdata/data bytes, relocs, symbols)
  -> COFF obj
  -> src/link.ep
  -> PE exe
```

X64IR text 只用于 driver fixture 和诊断，不参与 obj 生成。旧 asm 后端归档在
tag `python-asm-archive-2026-07-02`。

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

X64IR 是当前 LowIR：它已经显式包含寄存器、栈槽、label、static-data item、
symbol reference、Windows x64 ABI 调用序列。它仍是结构化对象，不是 NASM
文本。

`X64Program.text()` 只用于审查和 golden tests。新增功能不能依赖解析这份文本。

### 1.3 MachineObjectBuilder

Machine layer 把 X64IR 编成：

- `.text` bytes
- `.rdata` bytes
- `.data` bytes
- text labels
- rdata labels
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
| `X64Section(name)` | 切换当前 section；当前支持 `.text`、`.rdata`、`.data`。 |
| `X64Label(id, symbol_name)` | 在当前 section 绑定已分配的 label handle。 |
| `X64Inst(op, operands)` | `.text` 指令；`op` 内部使用 enum-like `i64` ID，文本 mnemonic 只在 MIR->X64IR、pretty-print 和诊断边界转换。 |
| `X64DataBytes(label, values)` | 当前 static-data section 内定义字节序列。 |
| `X64DataZero(label, count)` | 当前 static-data section 内定义零初始化字节。 |

Opcode ID 的完整表集中在 `src/x64.ep`。在语言获得 scalar enum 之前，生产代码中的数字
opcode 必须带随行 mnemonic 注释，或处于有明确范围说明的 opcode-family 判断中；不要在其他
文件建立第二份无注释编号表。Jcc `8..23` 按 canonical near-Jcc byte 顺序排列，相邻 ID 是
inverse condition。实验与性能数据见 [`x64-opcode-id-experiment.md`](x64-opcode-id-experiment.md)。

操作数：

| Operand | 含义 |
| --- | --- |
| `Reg(name)` | 寄存器。 |
| `Imm(value)` | 整数立即数。 |
| `Symbol(name)` | call target 或外部/section symbol reference。 |
| `LabelRef(label)` | 持有数字 label handle 的 branch target。 |
| `Mem(base, disp, symbol, size)` | base+disp memory 或 RIP-relative symbol memory。 |

`Mem(size=1/2/4/8)` 分别打印 `byte/word/dword/qword [...]`。
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
- `main` 的 `ret value` 降成编码导入 `__ep_import$kernel32.dll$ExitProcess(value)`，不走普通 `ret`。
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
- block-local、单次使用且由下一条 instruction/terminator 从 `rax` 消费的 result 会短暂驻留
  `rax`；其他 value 继续使用栈槽。

## 4. 当前 MIR lowering 覆盖

核心 MIR ops：

| MIR op | X64IR 降级方向 |
| --- | --- |
| `alloca` | 只分配栈槽，不发指令。 |
| `store` | operand -> `rax`，再 `mov [rbp+slot], rax`。 |
| `load` | `mov rax, [rbp+slot]`；结果通常存入栈槽，满足 residency 条件时保留在 `rax`。 |
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
| `ret` | 编码 `ExitProcess` import for `main`，普通函数跳转到 shared return label。 |

## 5. 当前 machine instruction subset

当前指令形态可识别的寄存器名：

- 64-bit: `rax rcx rdx rbx rsp rbp rsi rdi r8 r9 r10 r11 r12 r13 r14 r15`
- 32-bit memory load/store: `eax ecx edx ebx esp ebp esi edi r8d r9d r10d r11d r12d r13d r14d r15d`
- 16-bit memory store: `ax cx dx bx sp bp si di r8w r9w r10w r11w r12w r13w r14w r15w`
- 8-bit store and immediate ALU: `al cl dl r8b r9b r10b r11b r12b r13b r14b r15b`

当前 encoder 支持的指令形态：

| Instruction | Supported forms |
| --- | --- |
| `push` | `push rbp` |
| `pop` | `pop rbp` |
| `ret` | no operands |
| `sub/add` | `sub rsp, imm`, `add rsp, imm` |
| `call` | `call Symbol` |
| `jmp` | `jmp LabelRef` |
| `jo/jno/jb/jae/jz/jnz/jbe/ja/js/jns/jp/jnp/jl/jge/jle/jg` | canonical near `jcc LabelRef` forms |
| `cqo` | no operands |
| `idiv/div` | `idiv r64`, `div r64`; dividend/result still use implicit `RDX:RAX` |
| `imul` | `imul r64, r64`, `imul r64, r64, imm8/imm32` |
| `neg` | `neg r64` |
| `cmp` | `cmp r64, r64`, `cmp r64, imm8/imm32` |
| `sete/setne/setg/setl/setge/setle` | target `al` |
| `movzx` | `movzx eax, al` |
| `movsx` | `movsx r64, byte/word [r64+disp]` |
| `movzx` | `movzx r64, byte/word [r64+disp]` (also `movzx eax, al` for setcc) |
| `movsxd` | `movsxd r64, dword [r64+disp]` |
| `test` | intended contract: `test r64, same r64` |
| `xor` | `xor r64, r64` |
| `shl/sar/shr` | `op r64, cl`, `op r64, imm8` |
| `inc/dec` | `inc r64`, `dec r64` |
| `add/sub/and/or/xor` | `op r64, r64` |
| `add/or/and/sub/xor` | `op r64, imm8/imm32`; immediate is sign-extended |
| `add` | `add r8, imm8` |
| `mov` | forms listed below |
| `lea` | `lea r64, [symbol]`, `lea r64, [base+disp]` |

`mov` forms:

| Form | Notes |
| --- | --- |
| `mov r64, imm32/imm64` | imm64 only when outside signed 32-bit range. |
| `mov r64, r64` | register move. |
| `mov r64, qword [base+disp]` | base memory load. |
| `mov r64, qword [symbol]` | RIP-relative symbol load relocation. |
| `mov [base+disp], r64` | base memory store. |
| `mov [base+disp], r8` | byte store when source is 8-bit reg. |
| `mov [base+disp], imm` | byte or qword-sized immediate store depending on `Mem.size`. |
| `mov [symbol], r64` | RIP-relative symbol store relocation. |
| `mov [symbol], al` | RIP-relative byte store relocation. |

### 5.1 Instruction form contract

以下规则是 `src/machine.ep` 当前 encoder 的实际限制。超出此合约的指令形式会在 machine encoding 时 panic；新增指令形态必须补 encoder 测试。

#### Register contract

| 类别 | 支持 | 不支持 |
|------|------|--------|
| 64-bit | `rax rcx rdx rbx rsp rbp rsi rdi r8`–`r15` | 无整数 GPR 缺口；具体指令形态仍受下表限制 |
| 32-bit | `eax ecx edx ebx esp ebp esi edi r8d`–`r15d` | 当前只作为 `mov` memory load/store operand |
| 16-bit | `ax cx dx bx sp bp si di r8w`–`r15w` | 当前只作为 `mov` memory store source |
| 8-bit | `al cl dl r8b`–`r15b` | `bl spl bpl sil dil` 及 high-byte `ah ch dh bh` |

#### `mov` contract

| 形式 | 状态 | 说明 |
|------|------|------|
| `mov al, byte [mem]` | ❌ 不支持 | `movzx rax, byte [mem]` 代替（零扩展），或 `movsx rax, byte [mem]`（符号扩展） |
| `mov byte [mem], imm` | ✅ 支持 | 需 `Mem(size=1)` |
| `mov qword [mem], imm` | ✅ 支持 | 需 `Mem(size=8)` |
| `mov r64, byte [mem]` | ❌ 不支持 | 使用 `movsx r64, byte [mem]` |
| `movzx r64, byte [mem]` | ✅ 新增 | 零扩展 byte load；`0F B6 /r` + REX.W |
| `mov r32, dword [mem]` | ✅ 支持 | 写入 32-bit register 时自动零扩展到对应 r64 |
| `mov [mem], r16/r32` | ✅ 支持 | word/dword narrow store |
| `mov [rsp+disp], r64` | ✅ 支持 | 通过 `Mem("rsp", disp)` |
| `mov [rbp+disp], r64` | ✅ 支持 | 通过 `Mem("rbp", disp)` |
| `mov [reg+disp], r64` | ✅ 支持 | base 需属于当前 REG64 集合（`rax`–`r11`） |

#### Byte load/store contract

当前 byte 访问的合约：

| 操作 | 支持形式 |
|------|----------|
| byte load (zero-extend) | `movzx r64, byte [mem]` |
| byte store (8-bit reg) | `mov byte [mem], al/cl/dl/r8b`–`r15b` |
| byte store (immediate) | `mov byte [mem], imm8` |
| byte load (sign-extend) | `movsx r64, byte [mem]` (internal helpers only) |

#### ALU contract

| 形式 | 状态 | 说明 |
|------|------|------|
| `add/sub/and/or/xor r64, r64` | ✅ | 二地址运算 |
| `add/or/and/sub/xor r64, imm8/imm32` | ✅ | Group 1 immediate encoding; imm32 is sign-extended |
| `add r8, imm8` | ✅ | byte arithmetic |
| `cmp r64, r64` | ✅ | |
| `cmp r64, imm32/imm8` | ✅ | imm32 和 imm8 均支持 |
| `test r64, r64` | ✅ | 当前合约只允许两个 operand 相同寄存器 |
| `test r64, imm` | ❌ 不支持 | |
| `neg r64` | ✅ | Group 3 `/3` encoding |
| `shl/sar/shr r64, cl` | ✅ | target is generic; variable count register is architecturally fixed |
| `shl/sar/shr r64, imm8` | ✅ | constant shift count |
| `imul r64, r64` | ✅ | two-operand low-64-bit multiply |
| `imul r64, r64, imm8/imm32` | ✅ | three-operand signed immediate multiply |
| `cqo; idiv r64` | ✅ | dividend and quotient/remainder use implicit `RDX:RAX` |
| `div r64` | ✅ | dividend and quotient/remainder use implicit `RDX:RAX` |

#### Memory addressing contract

| 形式 | 状态 | 说明 |
|------|------|------|
| `[base+disp]` | ✅ | base 可使用全部 16 个 64-bit GPR；lowering 中 `rsp`/`rbp` 最常见 |
| `[symbol]` | ✅ | RIP-relative symbol load/store |
| `[base+index*scale+disp]` | ❌ | SIB 未实现 |
| `[base]` | ✅ | disp=0 的 `Mem(base, 0)` |
| `Mem(size=N)` | ✅ | size=1/2/4/8 |

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

- `src/coff.ep` writes exactly three sections: `.text`, `.rdata`, and `.data`。
- Relocation type is currently always `IMAGE_REL_AMD64_REL32`。
- Symbols use section number 1 for `.text`, 2 for `.rdata`, 3 for `.data`, 0 for external。
- 只有 named text label 进入 symbol table；匿名 block/return label 不进入 COFF。
- Symbol 顺序固定为 named text、rdata、data、按 ASCII 排序的 extern。
- Backend 使用 `src/util.ep` 中固定容量、u64 FNV hash 的开放寻址
  `NameIndex` 做私有查询；MIR module-name lookup 与 machine symbol resolution 共用该实现，
  relocation 在 `src/machine.ep` 中直接取得
  最终 COFF symbol index；索引从不参与迭代，因此 hash 桶布局不会影响
  输出顺序或自举固定点。
- `data_relocs` exists in the writer API but current machine backend does not emit it。

`src/link.ep` contract:

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
`src/mir_runtime.ep` injects the shared runtime, inserts preparation calls, and
prunes unreachable functions.

`bytes(str)` calls `__ep_bytes_from_str` and `str(u8[])` calls
`__ep_str_from_bytes`; both deep-copy logical bytes. String byte indexing calls
`__ep_str_at`. String literals are inline `{len, bytes..., NUL}` objects in
`.rdata`.

Base helper bodies, array helpers, file I/O, and panic are bundled in `runtime/mir/helpers.ir`;
the remaining string helpers are written in Epic. `src/runtime_bundle.ep` embeds both MIR bundles
and the Epic string runtime source. The Epic source is merged with user input; equivalent extern declarations are
canonicalized before MIR lowering.
The x64 layer owns only ABI lowering, program data emission, and WinAPI
imports.

### 8.2 X64Program validator exists

`validate_x64_program(program)` now runs before machine encoding through
`MachineObjectBuilder.__init__()`. The two previously risky forms are covered:

- `test a, b` is rejected unless both operands are the same register.
- 64-bit Group 1 ALU and `imul` immediate forms accept signed imm32 values; larger constants require a register operand.
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
`__ep_import$kernel32.dll$ExitProcess`, and `str.1`. The `@` sigil is reserved for a future text MIR
syntax/parser and must not be stored in `MirFunction.name`, `MirExtern.name`,
`MirGlobal.name`, or `SymbolOperand.name`. Local SSA values also use raw names in `MirValue.name` / `MirParam.name`; the `%` sigil belongs to text MIR printing/parsing only.

### 8.6 Self-hosted compiler uses the MIR/X64IR/machine path

The old NASM-oriented driver and `src/codegen_support.ep` / `src/codegen.ep` backend line have been removed. The current `src/epic.ep` is a new active driver: it runs the Epic-written frontend, lowers through MIR and X64IR, emits machine code and COFF through `src/machine.ep` and `src/coff.ep`, and links through `src/link.ep`.

`compiler_sources.py` defines the canonical source order used to build this compiler. `test_bootstrap_fixed_point.py` repeatedly compiles the self-hosted compiler with the generated compiler and verifies that later generations stabilize.


## Local X64IR append-time simplification

X64IR construction performs only adjacency-proven simplifications:

- remove `mov reg, [mem]` immediately following `mov [mem], reg` when reg/base/disp/width all match;
- remove `jmp label` when `label` is bound immediately afterward;
- rewrite `jcc next; jmp other; next:` to `inverse-jcc other; next:` for all canonical inverse pairs:
  `jo/jno`, `jb/jae`, `jz/jnz`, `jbe/ja`, `js/jns`, `jp/jnp`, `jl/jge`, and `jle/jg`.

A label or any intervening X64IR item blocks these rewrites. This is local instruction selection, not a CFG or
register-allocation pass. Measurement and safety details are recorded in
[`local-x64-peepholes-experiment.md`](local-x64-peepholes-experiment.md).
