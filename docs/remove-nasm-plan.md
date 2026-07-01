# 删除 NASM 的大改计划

目标：把当前 `Epic AST -> 文本 ASM -> nasm.exe -> COFF obj -> link.py -> PE exe` 改成 `Epic AST -> MIR -> LowMIR/X64MIR -> 机器码/数据/fixup -> PE exe`，删除 `nasm.exe` 这个构建阶段。

MIR 的具体设计见 `docs/mir-design.md`。本文档只记录删除 NASM 的工程路线。

## 判断

当前固定点构建里，Python reference compiler 的前端和汇编文本生成不到 1 秒，`nasm.exe` 汇编单个约 1.2MB / 5.8 万行的 ASM 需要约 9 秒。最终 exe 只有约 254-269KB，说明问题不在最终二进制大小，而在“生成巨大文本汇编再解析”的中间形态。

NASM 当前承担两件事：

- x64 指令编码。
- label、rel32、section-relative 引用和外部 import 的 relocation。

`link.py` 已经能写最小 PE64 exe，剩余核心缺口是一个 Epic 自己的 MIR、MIR lowering、x64 子集编码器和 fixup 管理。

## 总路线

采用两阶段策略：

```text
短期：Epic AST -> MIR -> ASM text backend / machine backend 并存
中期：Epic AST -> MIR -> LowMIR/X64MIR -> machine code + reloc/fixup -> COFF-like object or PE exe
长期：Epic AST -> MIR -> LowMIR/X64MIR -> machine code + PE writer -> PE exe
```

短期目标不是立刻删除所有旧路径，而是先把“文本 ASM 是 codegen 主中间形态”替换为“结构化 MIR 是 codegen 主中间形态”。ASM backend 暂时保留为调试 pretty printer 和迁移对照；machine backend 逐步成为主路径。

COFF obj 不作为长期主路径，但可以作为 B 阶段的过渡形态，用来把“指令编码/MIR lowering”和“最终 PE 写出/import table/section layout”拆开，降低一次性迁移风险。

## MIR 原则摘要

完整设计见 `docs/mir-design.md`。当前已定原则：

- MIR 参考 LLVM IR 的核心形态：函数、basic block、terminator、typed value、三地址指令、显式 load/store、显式 branch。
- MIR 的主形态是内存中的结构化对象，不是字符串文本。
- 第一版不做 text MIR parser；text MIR 只作为调试、审计和 golden test 输出。
- text MIR pretty printer 默认打印完整类型信息，不为了简短省略类型。
- 第一版不直接做 SSA，采用三地址临时值 + mutable local address。
- 源码局部变量 lowering 成 `%x.addr = alloca ...` 这类地址；读写通过 `load` / `store`。
- bool 类型文本写作 `bool`，不写作 `i1`。
- MIR 不直接等于 x64；后续 lowering 成 LowMIR/X64MIR，再做 ASM pretty print 或机器码编码。

## 五步法

1. 质疑需求：我们真正需要的是 Windows PE64 可执行文件，不是 ASM 文本，也不是 COFF obj。
2. 删除部件：删除 `nasm.exe` 和“文本 ASM -> obj”阶段。COFF obj 可以作为过渡调试形态，但不作为长期主路径需求。
3. 简化优化：MIR 先参考 LLVM IR 的核心结构，但只保留 Epic 当前需要的类型、指令和控制流。
4. 加速周转：保留 ASM backend 作对照，逐个 example 迁移到 MIR + machine backend。
5. 自动化：用现有 examples、bootstrap fixed point 和二进制一致性/行为测试守住迁移。

## 非目标

- 不实现通用 NASM 语法解析器。
- 不做向前兼容的老 toolchain 维护。
- 不优先做全局优化器或寄存器分配器。
- 不做完整 LLVM IR 兼容层。
- 第一版不做 text MIR parser。
- 不做跨平台 IR，第一版 MIR 只服务 Epic 当前 Windows x64 目标。
- 不把 COFF obj 作为长期主路径，除非 PE 直接输出被证明成本更高。

## 总体架构

新增 MIR lowering 和两个后端：

```text
AST codegen / lowering
  -> MIR

MIR text backend
  -> text MIR
  -> 用于调试、审计、迁移对照

MIR lowering / selection
  -> LowMIR / X64MIR

LowMIR machine backend
  -> text: u8[]
  -> data: u8[]
  -> labels: map[str]i64
  -> fixups: Fixup[]
  -> imports: Import[]
  -> COFF-like object or PE exe
```

现有文本 ASM backend 暂时保留，但定位改为 LowMIR 的 pretty printer / 对照输出，不再作为新功能的主承载层。

## 阶段计划

### 1. 指令面和语义面审计

产出：`docs/mir-design.md` 和 `docs/x64-instruction-subset.md`。

任务：

- 从 `build/fixed-point/src/epic.asm` 提取实际 x64 指令集合。
- 从 `bootstrap/codegen_*.py` 提取当前 codegen 真实需要表达的语义操作：分支、循环、算术、比较、调用、load/store、字符串、数组、map、match。
- 把语义操作映射到 MIR op。
- 把 x64 指令映射到 LowMIR / encoder 任务。
- 标出 MIR lowering 必须处理的 ABI 和栈布局规则。

验收：

- MIR op 清单覆盖当前 examples 和 bootstrap。
- LowMIR 指令清单覆盖当前 bootstrap 生成 ASM。
- 每个 MIR op 都有明确 lowering 方向。

### 2. Python 原型 MIR

产出：`bootstrap/mir.py` 或等价模块。

任务：

- 实现 `MirProgram`、`MirFunction`、`MirBlock`、`MirInst`、`MirTerminator`、`MirType`。
- 实现 text MIR pretty printer。
- 实现最小 validator：block 必须以 terminator 结束，value 使用前必须定义，类型要匹配。
- 手写最小 MIR 程序，能输出 text MIR。

验收：

- 一个手写 smoke MIR 程序可打印、可验证。
- text MIR 可读，适合作为调试形态。

### 3. MIR -> LowMIR / X64MIR lowering 原型

产出：`bootstrap/mir_lower.py` 或等价模块。

任务：

- 实现基本块和 terminator lowering。
- 实现 `add/sub/icmp/load/store/call/ret` 的最小 lowering。
- 先采用简单策略：固定寄存器 + stack slot，不做寄存器分配。
- 生成 LowMIR，不生成字符串 ASM。

验收：

- 手写 MIR 程序可以 lowering 到 LowMIR。
- LowMIR pretty printer 输出接近当前 ASM，可人工审查。

### 4. Python 原型 MachineEmitter

产出：`bootstrap/machine.py` 或等价模块。

任务：

- 从 LowMIR 输入，而不是从字符串 ASM 输入。
- 实现 `CodeBuffer`、`LabelTable`、`Fixup`。
- 实现 rel32 label fixup。
- 实现 import call thunk fixup。
- 实现 `.data` 字节输出。
- 短期可以输出 COFF-like 中间结构或直接复用/内联 `link.py` 的 PE 写出逻辑。

验收：

- 一个手写 MIR smoke 程序能直接生成 exe 并运行。
- 不调用 `tools/nasm.exe`。

### 5. 迁移 AST codegen 到 MIR

任务：

- 把 `bootstrap/codegen_*.py` 中直接 emit ASM 的路径迁移为 emit MIR。
- 先从简单 example 开始，不一次性迁移全部语言特性。
- 禁止新增直接拼接指令字符串的路径。
- 对每个迁移点建立 AST -> MIR -> LowMIR -> ASM pretty print / machine 的对应关系。

验收：

- 现有 ASM backend 行为不变。
- 小 examples 可以选择 MIR + machine backend 编译运行。

### 6. 覆盖 examples

任务：

- 从简单到复杂迁移：`m1_exit.ep`、表达式、变量、函数、字符串、数组、文件、map、match。
- 每覆盖一类特性，补 MIR op、lowering 和 machine backend 所需编码。
- 对无法结构化表达的指令输出，先删掉或改写 helper。

验收：

```powershell
python test_examples_py.py
```

在 MIR + machine backend 下通过所有 example。

### 7. 运行时迁移

任务：

- 删除“拼接 `runtime/*.asm` 文本”的依赖。
- 短期：用 MIR/LowMIR builder 重写 runtime helper。
- 中期：能用 Epic 写的 runtime 尽量改成 Epic 源码。
- 保留 Windows API import 表能力。

验收：

- `str_alloc`、`bytes`、`str_cat`、`read_file`、`write_file`、`system` 等 helper 不再依赖 NASM 文本。
- examples 仍通过。

### 8. Epic 自举 backend

任务：

- 在 `src/` 中实现与 Python 原型一致的 MIR、MIR lowering 和 machine emitter。
- 迁移 `src/codegen_support.ep` 和 `src/codegen.ep`。
- 保持 Python reference compiler 和 Epic compiler 的输出语义一致。

验收：

```powershell
python test_bootstrap_fixed_point.py
```

固定点通过，并且构建链路不调用 `tools/nasm.exe`。

### 9. 删除旧部件

任务：

- 删除 `tools/nasm.exe` 依赖说明。
- 删除 `runtime/*.asm` 主路径依赖。
- 更新 `docs/impl.md`。
- 更新 README toolchain 描述。
- 删除或隔离旧 ASM backend，只保留 MIR/LowMIR pretty printer / 调试入口。

验收：

- 全仓库接受测试通过。
- 从干净环境构建不需要 NASM。

## 风险

- x64 编码 bug 会表现为运行期崩溃，定位比文本 ASM 难。
- MIR 设计过厚会拖慢迁移，设计过薄又可能退化成结构化汇编。
- 如果第一版就追求完整 SSA/优化框架，可能偏离删除 NASM 这个主目标。
- Windows x64 ABI 细节必须严格保持：shadow space、栈 16 字节对齐、volatile register 假设。
- rel32、RIP-relative data、import thunk 的 off-by-one 错误容易造成不可执行文件。
- Python 和 Epic 两套 backend 同步期间会有重复实现成本。

## 降险策略

- MIR 参考 LLVM IR 的结构，但只实现 Epic 当前需要的最小集合。
- 第一版先支持真实用到的 MIR op 和 x64 指令子集。
- 每个 MIR op 都要有 text MIR golden 测试。
- 每个 lowering 规则都要有 LowMIR golden 测试。
- 每个 encoder 加小的二进制 golden 测试。
- 保留 ASM backend 到固定点完成后再删。
- 先在 Python 原型里跑通，再移植到 Epic。
- 每阶段都跑当前接受测试。

## 初步工作量

- MIR 数据结构、printer、validator：1-2 天。
- MIR -> LowMIR lowering 原型：1-2 天。
- Python machine emitter 原型：1-2 天。
- examples 全覆盖：3-6 天。
- runtime 迁移：2-4 天。
- Epic 自举实现和固定点稳定：5-10 天。

总体预估：2 周左右，取决于 MIR 设计范围、x64 encoder bug 数量和 runtime 迁移复杂度。

## 推荐第一步

先单独写 `docs/mir-design.md`，把 MIR 的 type、function、block、instruction、terminator、local variable、call、memory model 定下来。然后做 Python MIR 原型和 text MIR printer，不直接改现有主构建链路。目标是在最小 example 上证明 `AST -> MIR -> LowMIR -> machine code -> PE` 可行，再决定 machine backend 是否先经由 COFF-like 过渡形态。

