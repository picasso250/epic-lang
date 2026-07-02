# Epic LowIR / X64IR 规格

本文档记录当前 Python machine backend 的真实合约。它不是通用 x64
汇编器说明，也不是未来完整后端设计；目标是给 `MIR -> X64IR ->
machine bytes -> COFF -> PE` 这条线建立可测试边界。

对应实现：

- `bootstrap/mir.py`: typed MIR data model and validator。
- `bootstrap/mir_codegen.py`: AST -> MIR。
- `bootstrap/mir_lower.py`: MIR -> structured X64IR。
- `bootstrap/x64_runtime.py`: runtime data, startup hook, and runtime append policy。
- `bootstrap/x64.py`: X64IR data model and text pretty printer。
- `bootstrap/machine.py`: X64IR -> machine bytes + COFF reloc records。
- `bootstrap/coff.py`: minimal AMD64 COFF object writer。
- `link.py`: minimal PE linker for generated COFF objects。

## 1. 分层边界

当前 machine backend 的主路径是：

```text
AST
  -> MIR
  -> X64Program
  -> MachineObjectBuilder(text bytes, data bytes, relocs, symbols)
  -> COFF obj
  -> link.py / lld-link
  -> PE exe
```

`compile_files()` 仍会把 `X64Program.text()` 写到 `.asm` 文件，但这个文件在
`--backend machine` 下只是 debug pretty print，不参与 obj 生成。

Runtime emission is split from MIR lowering at the policy boundary:

- `MirLower` lowers MIR into X64IR and emits a startup hook call for `main`。
- `x64_runtime.py` emits runtime data and appends the current full runtime。
- The current policy is still full runtime emission. Used-only emission is a
  future policy, not a current requirement。

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

它只支持当前 lowering 实际会生成的指令和操作数组合。

## 2. X64Program 数据模型

`X64Program.items` 是顺序 item 列表：

| Item | 含义 |
| --- | --- |
| `X64Global(name)` | 声明全局符号；当前 machine layer 不使用它决定导出，只依赖 label symbols。 |
| `X64Extern(name)` | 声明外部符号；当前 machine layer 收集但不验证引用必须先声明。 |
| `X64Section(name)` | 切换当前 section；当前支持 `.text`、`.data`。 |
| `X64Label(name)` | 当前 section 内定义 label。 |
| `X64Inst(op, operands)` | `.text` 指令。 |
| `X64DataBytes(label, values)` | `.data` 内定义字节序列。 |
| `X64DataZero(label, count)` | `.data` 内定义零初始化字节。 |

操作数：

| Operand | 含义 |
| --- | --- |
| `Reg(name)` | 寄存器。 |
| `Imm(value)` | 整数立即数。 |
| `Symbol(name)` | call target 或外部/section symbol reference。 |
| `LabelRef(name)` | branch target。 |
| `Mem(base, disp, symbol, size)` | base+disp memory 或 RIP-relative symbol memory。 |

`Mem(size=1)` 打印 `byte [...]`，`Mem(size=8)` 打印 `qword [...]`。

## 3. Windows x64 ABI 约定

MIR lowering 当前固定面向 Windows x64：

- 前四个参数使用 `rcx`、`rdx`、`r8`、`r9`。
- 第五个及之后参数写入 call frame 的 `[rsp+32+index*8]`。
- 每次 call 前预留 32 字节 shadow space。
- 返回值在 `rax`。
- `main` 降成 PE entry symbol `_start`。
- `main` prologue calls `__epic_runtime_start` to initialize runtime state。
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
- frame 大小按 `((next_slot + 32 + 15) // 16) * 16` 对齐。
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
| `div/mod` | `cqo; idiv rcx`，`mod` 取 `rdx`。 |
| `shl/sar/shr` | 左值 -> `rax`，右值 -> `rcx`，使用 `cl`。 |
| `not` | `test rax, rax; sete al; movzx eax, al`。 |
| `icmp.*` | `cmp rax, rcx; setcc al; movzx eax, al`。 |
| `call` | Windows x64 call sequence。 |
| `br` | `jmp label`。 |
| `condbr` | `test rax, rax; jnz then; jmp else`。 |
| `ret` | `ExitProcess` for `main`，普通函数跳转到 shared return label。 |

当前 Python prototype-only Epic-specific MIR ops：

| MIR op | 说明 |
| --- | --- |
| `struct.new` | 使用 `_heap` + `HeapAlloc` 分配结构体大小。 |
| `field.store` / `field.load` | 通过 `program.structs` 查字段偏移。 |
| `adt.payload` | 从 ADT header 的 offset 8 取 payload pointer。 |
| `array.new` | 分配 `{data, len, cap}` header 和 data buffer。 |
| `array.push` | 内联 grow/copy/store。 |
| `array.extend` | 内联 grow/copy 多元素。 |
| `array.index.load` | 带 bounds check 的 8 字节元素读取。 |
| `ptr.index.load` | 指针按 8 字节元素读取。 |
| `ptr.i8.get` | 指针按字节读取并 sign-extend。 |
| `ptr.i64.get` | 指针按 8 字节读取。 |

这些 op 是当前实现债：它们能让 examples 先跑通，但不应固化为目标 MIR。
迁移方向是按 `docs/mir-design.md` 把它们分解成 `gep/load/store/call/branch`，
或在必要时显式放进独立 HighMIR，而不是继续扩大 MIR validator 对这类便捷 op 的接受面。

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
- If the target label exists in `.text`, machine layer patches the signed rel32
  displacement directly.
- Displacement is computed from the address after the 4-byte immediate.

External or section symbol references:

- `call Symbol` emits `E8 00 00 00 00` and a text relocation at the rel32 field.
- `lea reg, [symbol]` emits RIP-relative addressing and a text relocation.
- `mov reg, [symbol]` and `mov [symbol], reg` also use text relocations.
- If a branch target is not a local text label, it is left as a text relocation.

COFF contract:

- `bootstrap/coff.py` writes exactly two sections: `.text` and `.data`。
- Relocation type is currently always `IMAGE_REL_AMD64_REL32`。
- Symbols use section number 1 for `.text`, 2 for `.data`, 0 for external。
- `data_relocs` exists in the writer API but current machine backend does not emit it。

`link.py` contract:

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

- `test_mir.py`: MIR text and validation smoke test。
- `test_x64_layers.py`: X64 pretty print, MIR-to-X64 function lowering, and
  X64-to-machine bytes/fixups。
- `test_examples_py.py --backend machine`: executable-level acceptance。

The lower layers should stay small. Do not use full examples to test a single
encoding rule; use a tiny X64Program with one or two labels and one relocation.

## 8. Design audit

The current route is still sound, but several choices should be corrected before
the Epic implementation grows around them.

### 8.1 Runtime emission is too global

Runtime data and startup hook ownership now lives in `x64_runtime.py`, and
`MirLower` calls `__epic_runtime_start` instead of inlining heap/argv
initialization. The current remaining coupling is that helper body methods are
still physically on `MirLower` and are invoked through the runtime policy module.

Recommended next step: move helper body methods into `x64_runtime.py` as named
fragments, then keep the current `full` policy while making `used_only` a later
policy.

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

### 8.4 MIR still accepts prototype high-level ops

The target MIR design no longer treats `struct.new`, `field.load`,
`array.push`, and `adt.payload` as MIR ops. Current Python codegen still emits
them, and the validator only checks the older core MIR subset. Unknown ops are
effectively unchecked.

Recommended next step: first align codegen with `docs/mir-design.md` by lowering
aggregate allocation/access into `gep/load/store/call/branch`; then make the
validator reject unknown ops and reject the prototype-only high-level ops.

### 8.5 Dynamic metadata on MirProgram

`mir_codegen.py` assigns `program.structs` dynamically. That hides a real
contract from the MIR dataclass and will make the Epic port harder to keep in
sync.

Recommended next step: make struct and ADT layout metadata explicit fields on
`MirProgram`, matching `docs/mir-design.md`.

### 8.6 Symbol spelling is inconsistent

Docs describe module symbols as `@main`, while implementation currently uses raw
names such as `main`, `str_i64`, and `ExitProcess`. This is tolerable in Python
prototype code, but it should be resolved before committing the self-hosted
backend shape.

Recommended next step: define one internal symbol spelling and one text printing
spelling. Do not let pretty-print syntax leak into object symbols.

### 8.7 Self-hosted compiler is still old backend

`src/epic.ep` still emits text ASM and invokes `tools\\nasm.exe` and `link.py`.
That is acceptable for the current staged migration, but it must remain an
explicit milestone: Python machine backend passing examples is not the same as
the Epic compiler supporting the machine path.

Recommended next step: keep `test_bootstrap_fixed_point.py` marked as expected
to fail on the machine path until `src/` has its own MIR/X64IR/machine emitter.
