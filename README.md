# Epic

Epic 是一个小巧的自托管（self-hosted）系统编程语言，目标平台为 Windows x64。

它包含一个 Python 参考编译器、一个用 Epic 自身编写的自托管编译器、一个类型化的 LLVM 风格 MIR、一个结构化的 x64 后端、一个小型 COFF/PE 工具链，以及用于构建真实 Windows 可执行文件的运行时辅助代码。

```text
Epic 源码
  -> AST
  -> typed MIR
  -> structured X64IR / LowIR
  -> 机器码字节
  -> AMD64 COFF 目标文件
  -> PE 可执行文件
```

Epic 的实现仍在快速发展，但 v0 公开语言契约已经冻结。项目已跨越自托管里程碑，支持足够的语言特性来编写有意义的程序——包括用 Epic 本身编写的编译器模块。

## 亮点

- **自托管语言工作**：`bootstrap/` 是 Python 参考编译器；`src/` 包含用 Epic 编写的编译器模块和工具，跟随当前语言设计更新。
- **类型化 LLVM 风格 MIR**：Epic 拥有自己的中间表示（MIR），具有类型化值、基本块、终结指令（terminator）、`load`/`store`、`gep`、函数调用、分支和验证。其灵感来自 LLVM 风格的编译器构造，而非追求 LLVM 兼容性。
- **结构化 x64 后端**：MIR 降级为 X64IR / LowIR，这是一个结构化的对象模型，涵盖寄存器、栈槽位、标签、符号、数据项和 Windows x64 ABI 调用。`.asm` 输出仅用于调试打印，而非活跃后端。
- **机器码后端**：X64IR 直接编码为机器码字节，写入 AMD64 COFF 目标文件，并由仓库内的 Python 链接器链接为 PE 可执行文件。
- **运行时辅助代码迁移**：MIR 运行时辅助代码（runtime helper）的主体已集中到 `runtime/mir/helpers.mir`，使得 Python 参考编译器和自托管编译器使用同一份运行时源码。
- **明确的稳定边界**：v0 冻结用户可见的语言与工具行为；编译器、runtime、GC、IR 和后端内部仍可持续演进。

## 语言特性

Epic 目前支持：

- 函数与结构体接收者方法、局部变量、块尾部值、显式返回
- `if`/`else`、`for condition` 条件循环、`for i: start:end` 半开区间循环
- `break`、`continue`、`panic`、字面量 `match`、穷举 ADT `match`；`_:` 是唯一的默认分支形式
- `i64`、`u64`、`i32`、`u32`、`u8`、`bool`、显式整数类型转换、带检查的算术运算
- 面向字节的 `str`、字符字面量和 f-string 字面量、内容等值比较、切片、分配型 `str + str`
- 动态数组（`T[]`）——支持字面量、定长零初始化、带检查的索引、`len`、`push`、`pop`、`extend`
- 堆分配结构体——支持具名和部分初始化；省略的引用字段为 null，可用后缀 `?` 检查
- 封闭的结构体-联合 ADT——`type Name = A | B` 声明、显式包装构造、公共字段访问
- 面向字节的文件 I/O、`argv`、进程退出、Windows 上类型化的直接 WinAPI 导入

v0 的公开语言特性由当前编译器、`examples/` 和 `docs/` 共同定义并保持稳定。内部实现不属于冻结边界，可以为 GC、优化、可维护性和新后端继续演进。

## 编译器流水线

当前活跃的编译路径：

```text
解析 / 合并（parse / merge）
  -> 语义分析（semantic analysis）
  -> AST 到 MIR
  -> MIR 验证（MIR validation）
  -> MIR 到 X64IR
  -> X64IR 验证（X64IR validation）
  -> 机器字节码 + COFF 重定位（machine bytes + COFF relocations）
  -> PE 链接（PE linking）
```

关键实现文件：

```text
bootstrap/epic.py          编译器驱动
bootstrap/lexer.py         词法分析器
bootstrap/parser.py        语法解析器
bootstrap/sema.py          语义分析
bootstrap/ast_to_mir.py    AST -> MIR
bootstrap/mir.py           类型化 MIR 模型与验证器
bootstrap/mir_to_x64.py    MIR -> 结构化 X64IR
bootstrap/x64.py           X64IR 模型与美化打印
bootstrap/machine.py       X64IR -> 机器字节码 + COFF 记录
bootstrap/coff.py          最小 AMD64 COFF 写入器
bootstrap/link.py          最小 PE 链接器
```

Python 参考编译器是当前语言的判定基准（oracle）。用 Epic 编写的编译器代码应先与参考路径保持一致，再发展独立的优化行为。未来的优化工作应置于显式的优化模式之下，而非放在默认的 oracle 路径中。

## 仓库布局

```text
bootstrap/          Python 参考编译器（当前语言）
src/                用 Epic 编写的编译器模块和工具
runtime/            MIR 运行时辅助代码和后端运行时支持
examples/           正向学习示例
tests/              模块级编译测试与负向测试
docs/               设计笔记与实现契约
editors/            编辑器集成资源
tools/              本地工具二进制文件（如 lld-link.exe）
build/              忽略的本地构建输出
```

早期阶段的自举目录保存在 Git 历史与标签中，不作为维护中的源码目录。有用的存档标签包括：

```text
staged-bootstrap-archive-2026-06-30
python-asm-archive-2026-07-02
```

## 运行测试

从仓库根目录推荐的测试入口：

```powershell
python tests/run.py                    # 模块级编译测试
python test_examples.py                # examples/ 正向学习示例
python test_bootstrap_fixed_point.py   # 自举不动点检查（fixed-point check）
```

也可运行特定模块的测试：

```powershell
python tests/mir/run.py
python tests/x64/run.py
python tests/lexer/run.py
python tests/parser/run.py
python tests/link/run.py
```

`test_*.py` 文件是可直接运行的脚本测试。请勿将 `python -m pytest` 当作支持的测试入口。

## 构建与运行示例

示例代码位于 `examples/` 下，旨在作为正向、典型的程序，帮助新读者学习当前语言。

```powershell
python test_examples.py
```

也可以通过 Python 参考编译器编译单个示例。构建产物写入 `build/` 目录。

```powershell
python bootstrap/epic.py examples/00_hello_world.ep
```

默认路径使用仓库内的 Python PE 链接器。`lld-link`（若存在于 `tools/` 中）可作为可选的对照工具。

## 当前边界

Epic v0 已冻结公开语言契约，但仍有以下明确边界：

- 仅面向 Windows x64；尚无跨平台 ABI 承诺
- MIR 是 LLVM 风格，但并非 LLVM IR 兼容
- 一等用户指针类型不纳入公开语言特性
- 尚无完整的 SSA / phi-node 优化器流水线
- 尚无通用汇编器或通用寄存器分配器
- 旧的 NASM 文本汇编后端路径已归档，不再活跃

## 开发规则

- 修改编译器某个区域之前，先阅读对应的 `docs/` 文件。
- 保持示例正向友好；负向测试放在 `tests/<module>/fail/`。
- 倾向清晰的编译器代码，而非过早的性能优化。
- 遵守 v0 稳定边界：公开语义变更必须显式讨论并同步更新设计文档与意图级测试；内部实现无需维持兼容。
