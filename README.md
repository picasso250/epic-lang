# Epic

一个已完成自举的 **Windows x64** 原生编程语言。v0 公开语言契约已冻结。

- **可复现自举**：从 Python stage-0 构建 self-hosted compiler，并达到字节一致的不动点
- **直接生成原生 PE**：无需额外部署 Epic runtime 或第三方运行库；下面的 Hello World 为 **5632 bytes（5.5 KiB）**
- **完整编译器栈在仓库内**：typed MIR、结构化 x64 后端、COFF writer 和 PE linker

包含一个 Python 参考编译器、一个用 Epic 自身编写的自托管编译器、一个类型化的 LLVM 风格 MIR、一个结构化的 x64 后端、一个小型 COFF/PE 工具链，以及用于构建真实 Windows 可执行文件的运行时辅助代码。

## 快速上手

先看一段 Epic 代码：

```epic
fun main(): void {
    println("Hello, Epic!")
}
```

仓库中的 `examples/00_hello_world.ep` 就是上面的程序。先生成达到不动点的 self-hosted compiler，再用它编译并运行 Hello World：

```powershell
python test_bootstrap_fixed_point.py -o build\epic.exe

.\build\epic.exe `
  runtime\array.ep `
  runtime\panic.ep `
  runtime\str.ep `
  examples\00_hello_world.ep `
  --main examples\00_hello_world.ep `
  -o build\hello.exe

.\build\hello.exe
```

第一条命令从 Python stage-0 启动完整 bootstrap，只用于生成稳定的 `build\epic.exe`。self-hosted compiler 当前显式接收三份 runtime 源码和目标程序源码；之后的 examples 可以沿用同一形式，只替换目标 `.ep` 文件。

输出：

```
Hello, Epic!
```

从 **examples/00_hello_world.ep** 到 **examples/08_builtin_fun.ep** 按编号渐进学习。

## 语言特性

Epic 目前支持：

- 函数与结构体接收者方法、局部变量、块尾部值、显式返回
- `if`/`else`、`for condition` 条件循环、`for i: start:end` 半开区间循环
- `break`、`continue`、`panic`、字面量 `match`、穷举 ADT `match`；`_:` 是唯一的默认分支形式
- `i64`、`u64`、`i32`、`u32`、`u8`、`bool`、显式整数类型转换、带检查的算术运算
- 面向字节的 `str`、字符字面量和 f-string 字面量、内容等值比较、切片、分配型 `str + str`
- 动态数组（`T[]`）——字面量、定长零初始化、带检查的索引、`len`、`push`、`pop`、`extend`
- 堆分配结构体——具名和部分初始化；省略的引用字段为 null，可用后缀 `?` 检查
- 封闭的结构体-联合 ADT——`type Name = A | B` 声明、显式包装构造、公共字段访问
- 面向字节的文件 I/O、`argv`、进程退出、Windows 上类型化的直接 WinAPI 导入

主要语言特性可通过 `examples/` 渐进学习；完整语言边界由 `docs/` 和意图级测试共同定义。

v0 的公开语言特性由当前编译器、`examples/` 和 `docs/` 共同定义并保持稳定。内部实现（编译器、runtime、GC、IR、后端）不属于冻结边界，可持续演进。

## 自举不动点

项目已通过完整 bootstrap fixed-point 验证：Python reference compiler 先编译 Epic compiler 源码，得到 `epic-py.exe`；之后连续使用生成的 self-hosted compiler 重新编译同一份源码。

| 世代 | 使用的编译器 | 生成产物 | 本次耗时 | exe 体积 |
|------|--------------|----------|----------|----------|
| 1 | Python reference compiler | `epic-py.exe` | 2.79s | 0.70 MiB |
| 2 | `epic-py.exe` | `epic-epic.exe` | 2.50s | 0.70 MiB |
| 3 | `epic-epic.exe` | `epic-epic-epic.exe` | 2.52s | 0.70 MiB |
| 4 | `epic-epic-epic.exe` | `epic-epic-epic-epic.exe` | 2.51s | 0.70 MiB |

- **self-hosted 产物已达到字节不动点**：连续三个 self-hosted generations 字节一致
- 表中的时间来自一次本机构建记录，用于观察 bootstrap 过程，不是跨环境 benchmark

生成并保留最终收敛的编译器：

```powershell
python test_bootstrap_fixed_point.py -o build\epic.exe
```

### 重建 v0 bootstrap compiler

`v0` 标签包含可复现的 bootstrap 构建入口。脚本将目标 revision 检出到临时 detached worktree，在干净源码上运行完整不动点构建，校验已提交的 SHA-256，随后清理 worktree：

```powershell
python build_epic_v0.py --require-expected
```

产物：

```text
build/bootstrap-v0/epic-v0.exe
build/bootstrap-v0/epic-v0.exe.sha256
build/bootstrap-v0/manifest.json
```

后续编译器、GC 或后端开发可以用该 v0 compiler 作为稳定 seed，并检查当前源码能否再次收敛：

```powershell
python test_bootstrap_fixed_point.py --seed build/bootstrap-v0/epic-v0.exe
```

Python reference compiler 继续作为语言判定基准（oracle）和完整 bootstrap 的恢复入口；日常 self-hosted 演进可以从 `epic-v0.exe` 起步。

## 当前边界

Epic v0 已冻结公开语言契约，但仍有以下明确边界：

- 仅面向 Windows x64；尚无跨平台 ABI 承诺
- MIR 是 LLVM 风格，但并非 LLVM IR 兼容
- 一等用户指针类型不纳入公开语言特性
- 尚无完整的 SSA / phi-node 优化器流水线
- 尚无通用汇编器或通用寄存器分配器
- 旧的 NASM 文本汇编后端路径已归档，不再活跃

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

早期阶段的自举目录保存在 Git 历史与标签中。存档标签：`staged-bootstrap-archive-2026-06-30`、`python-asm-archive-2026-07-02`。

## 运行测试

```powershell
python tests/run.py                    # 模块级编译测试
python test_examples.py                # examples/ 正向示例
python test_bootstrap_fixed_point.py   # 从 Python 开始的完整自举不动点检查
```

模块级测试：

```powershell
python tests/mir/run.py
python tests/x64/run.py
python tests/lexer/run.py
python tests/parser/run.py
python tests/link/run.py
```

`test_*.py` 是可直接运行的脚本，非 pytest。

## 开发规则

- 修改编译器某个区域之前，先阅读对应的 `docs/` 文件。
- 保持示例正向友好；负向测试放在 `tests/<module>/fail/`。
- 倾向清晰的编译器代码，而非过早的性能优化。
- 遵守 v0 稳定边界：公开语义变更必须显式讨论并同步更新设计文档与意图级测试；内部实现无需维持兼容。

## 编译器流水线

当前活跃的编译路径：

```text
解析 / 合并（parse / merge）
  -> 语义分析（semantic analysis）
  -> AST 到 MIR
  -> MIR 验证（MIR validation）
  -> MIR 到 X64IR
  -> X64IR 验证（X64IR validation）
  -> 机器码字节 + COFF 重定位（machine bytes + COFF relocations）
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
bootstrap/machine.py       X64IR -> 机器码字节 + COFF 记录
bootstrap/coff.py          最小 AMD64 COFF 写入器
bootstrap/link.py          最小 PE 链接器
```

Python 参考编译器是当前语言的判定基准（oracle）。用 Epic 编写的编译器代码应先与参考路径保持一致，再发展独立的优化行为。未来的优化工作应置于显式的优化模式之下，而非放在默认的 oracle 路径中。
