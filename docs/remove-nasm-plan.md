# 删除 NASM 的大改计划

目标：把当前 `Epic AST -> 文本 ASM -> nasm.exe -> COFF obj -> link.py -> PE exe` 改成 `Epic AST -> 机器码/数据/fixup -> PE exe`，删除 `nasm.exe` 这个构建阶段。

## 判断

当前固定点构建里，Python reference compiler 的前端和汇编文本生成不到 1 秒，`nasm.exe` 汇编单个约 1.2MB / 5.8 万行的 ASM 需要约 9 秒。最终 exe 只有约 254-269KB，说明问题不在最终二进制大小，而在“生成巨大文本汇编再解析”的中间形态。

NASM 当前承担两件事：

- x64 指令编码。
- label、rel32、section-relative 引用和外部 import 的 relocation。

`link.py` 已经能写最小 PE64 exe，剩余核心缺口是一个 Epic 自己的 x64 子集编码器和 fixup 管理。

## 五步法

1. 质疑需求：我们真正需要的是 Windows PE64 可执行文件，不是 ASM 文本，也不是 COFF obj。
2. 删除部件：删除 `nasm.exe` 和“文本 ASM -> obj”阶段。COFF obj 也不作为新主路径需求。
3. 简化优化：先支持当前 codegen 实际用到的 x64 子集，不做通用 assembler。
4. 加速周转：保留 ASM backend 作对照，逐个 example 迁移到 machine backend。
5. 自动化：用现有 examples、bootstrap fixed point 和二进制一致性/行为测试守住迁移。

## 非目标

- 不实现通用 NASM 语法解析器。
- 不做向前兼容的老 toolchain 维护。
- 不优先做全局优化器或寄存器分配器。
- 不把 COFF obj 作为长期主路径，除非 PE 直接输出被证明成本更高。

## 总体架构

新增一个 machine backend：

```text
EmitterState
  text: u8[]
  data: u8[]
  labels: map[str]i64
  fixups: Fixup[]
  imports: str[]
  strings: StringLiteral[]

Codegen
  emit_mov(...)
  emit_call(...)
  emit_jmp(...)
  emit_data_string(...)

PE writer
  .text = text + import thunks
  .rdata = import table
  .data = data
```

现有文本 ASM backend 暂时保留，只作为迁移对照和回退，不新增功能。

## 阶段计划

### 1. 指令面审计

产出：`docs/x64-instruction-subset.md`。

任务：

- 从 `build/fixed-point/src/epic.asm` 提取实际指令集合。
- 按编码复杂度分组：无操作数、一操作数、二操作数、rel32、setcc、内存寻址。
- 标出必须支持的寻址形式，例如 `[rbp-8]`、`[rax+8]`、`[rcx+rdx*8]`、`[_heap]`、`lea rcx, [_str_1]`。

验收：

- 指令清单覆盖当前 bootstrap 生成 ASM。
- 每个指令族都有 machine encoder 的任务项。

### 2. Python 原型 MachineEmitter

产出：`bootstrap/machine.py` 或等价模块。

任务：

- 实现 `CodeBuffer`、`LabelTable`、`Fixup`。
- 实现最小寄存器和寻址表示，不接受任意字符串操作数。
- 实现 rel32 label fixup。
- 实现 import call thunk fixup。
- 实现 `.data` 字节输出。
- 复用或内联 `link.py` 的 PE 写出逻辑。

验收：

- 一个手写 smoke 程序能直接生成 exe 并运行。
- 不调用 `tools/nasm.exe`。

### 3. 迁移底层 emit API

任务：

- 把 `bootstrap/codegen.py` 中字符串化 helper 收敛到结构化 API。
- 先保留 `AsmEmitter` 和 `MachineEmitter` 两套实现。
- 禁止新增直接拼接指令字符串的路径。
- 对每个 helper 建立 ASM 输出和 machine 输出的对应关系。

验收：

- 现有 ASM backend 行为不变。
- 小 examples 可以选择 machine backend 编译运行。

### 4. 覆盖 examples

任务：

- 从简单到复杂迁移：`m1_exit.ep`、表达式、变量、函数、字符串、数组、文件、map、match。
- 每覆盖一类特性，补 machine backend 所需编码。
- 对无法结构化表达的指令输出，先删掉或改写 helper。

验收：

```powershell
python test_examples_py.py
```

在 machine backend 下通过所有 example。

### 5. 运行时迁移

任务：

- 删除“拼接 `runtime/*.asm` 文本”的依赖。
- 短期：用 machine emitter 重写 runtime helper。
- 中期：能用 Epic 写的 runtime 尽量改成 Epic 源码。
- 保留 Windows API import 表能力。

验收：

- `str_alloc`、`bytes`、`str_cat`、`read_file`、`write_file`、`system` 等 helper 不再依赖 NASM 文本。
- examples 仍通过。

### 6. Epic 自举 backend

任务：

- 在 `src/` 中实现与 Python 原型一致的 machine emitter。
- 迁移 `src/codegen_support.ep` 和 `src/codegen.ep`。
- 保持 Python reference compiler 和 Epic compiler 的输出语义一致。

验收：

```powershell
python test_bootstrap_fixed_point.py
```

固定点通过，并且构建链路不调用 `tools/nasm.exe`。

### 7. 删除旧部件

任务：

- 删除 `tools/nasm.exe` 依赖说明。
- 删除 `runtime/*.asm` 主路径依赖。
- 更新 `docs/impl.md`。
- 更新 README toolchain 描述。
- 删除或隔离 ASM backend，只保留必要的调试入口。

验收：

- 全仓库接受测试通过。
- 从干净环境构建不需要 NASM。

## 风险

- x64 编码 bug 会表现为运行期崩溃，定位比文本 ASM 难。
- Windows x64 ABI 细节必须严格保持：shadow space、栈 16 字节对齐、volatile register 假设。
- rel32、RIP-relative data、import thunk 的 off-by-one 错误容易造成不可执行文件。
- Python 和 Epic 两套 backend 同步期间会有重复实现成本。

## 降险策略

- 先支持真实用到的指令子集。
- 每个 encoder 加小的二进制 golden 测试。
- 保留 ASM backend 到固定点完成后再删。
- 先在 Python 原型里跑通，再移植到 Epic。
- 每阶段都跑当前接受测试。

## 初步工作量

- Python machine emitter 原型：1-2 天。
- examples 全覆盖：3-5 天。
- runtime 迁移：2-4 天。
- Epic 自举实现和固定点稳定：4-8 天。

总体预估：1-2 周，取决于 x64 encoder bug 数量和 runtime 迁移复杂度。

## 推荐第一步

先做指令面审计和 Python 原型，不直接改现有主构建链路。目标是在最小 example 上证明 `AST -> machine code -> PE` 可行，再决定是否全面迁移。
