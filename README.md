# Epic

一个已完成自举的 **Windows x64** 原生编程语言。版本标签保存可复现里程碑；当前 `dev` 语言契约允许显式破坏性演进。

- **可复现自举**：从 `v0` 分支导出的 seed 构建当前 self-hosted compiler，并达到字节一致的不动点
- **纯 Epic 源码完成自举**：当前自托管编译器与内置 runtime 资源共同形成自包含工具链
- **自动内存管理**：内置 non-moving conservative mark-sweep GC，无需额外 runtime 部署
- **直接生成原生 PE**：无需额外部署 Epic runtime 或第三方运行库；下面的 Hello World（含 GC）为 **10752 bytes（10.5 KiB）**
- **完整编译器栈**：typed MIR、结构化 x64 后端、COFF writer 和 PE linker

包含一个用 Epic 自身编写的自托管编译器、一个类型化的 LLVM 风格 MIR、一个结构化的 x64 后端、一个小型 COFF/PE 工具链，以及用于构建真实 Windows 可执行文件的运行时辅助代码。

## 快速上手

先看一段 Epic 代码：

```epic
fun main(): void {
    println("Hello, Epic!")
}
```

仓库中的 `examples/00_hello_world.ep` 就是上面的程序。先生成达到不动点的 self-hosted compiler，再用它编译并运行 Hello World：

```powershell
python bootstrap_fixed_point.py -o build\epic.exe
.\build\epic.exe examples\00_hello_world.ep -o build\hello.exe
.\build\hello.exe
```

默认输出只包含成功结果或错误。需要查看编译阶段、timing 和 stats 时加 `--verbose`：

```powershell
.\build\epic.exe examples\00_hello_world.ep -o build\hello.exe --verbose
```

第一条命令使用 `v0` 分支导出的 seed 启动完整 bootstrap；本地缺少 seed 时会从该分支的 detached worktree 自动重建。生成的 self-hosted compiler 已把 MIR runtime bundle 嵌入自身 `.data`，运行时不依赖当前工作目录中的 `runtime/`。

程序输出：

```
Hello, Epic!
```

从 **examples/00_hello_world.ep** 到 **examples/08_builtin_fun.ep** 按编号渐进学习。

## 语言特性

Epic 目前支持：

- 函数与 product type 接收者方法、局部变量、显式返回
- `if`/`else`、`for condition` 条件循环、`for i: start:end` 半开区间循环
- `break`、`continue`、`panic`、字面量 `match`、穷举 ADT `match`；`_:` 是唯一的默认分支形式
- `i64`、`u64`、`i32`、`u32`、`i16`、`u16`、`u8`、`bool`、显式整数类型转换、带检查的算术运算
- 面向字节的 `str`、字符字面量和 f-string 字面量、内容等值比较、切片、分配型 `str + str`
- 动态数组（`T[]`）——字面量、定长零初始化、带检查的索引、`len`、`push`、`pop`、`extend`
- 堆分配的具名字段类型——具名和部分初始化；省略的引用字段为 null，可用后缀 `?` 检查
- 自动垃圾回收；对象地址在生命周期内保持稳定
- 封闭的 named payload sum——`type Name = A | B` 声明、显式包装构造、公共字段访问
- `embed "path"` 编译期原始字节嵌入、面向字节的文件 I/O、`argv`、进程退出、Windows 上类型化的直接 WinAPI 导入

主要语言特性可通过 `examples/` 渐进学习；完整语言边界由 `docs/` 和意图级测试共同定义。

当前语言特性由编译器、`examples/`、`docs/` 和意图级测试共同定义。源码与 MIR 不承诺跨开发版本兼容；破坏性变更必须同步更新文档和测试。`v0` 分支维护可复现 bootstrap seed；其余版本标签保存对应历史快照。

## 自举不动点

项目已通过完整 bootstrap fixed-point 验证：`v0` 分支导出的 `epic-v0.exe` 编译当前 Epic compiler，随后连续使用生成的 compiler 重新编译同一份源码。

- **self-hosted 产物已达到字节不动点**：连续三个 self-hosted generations 字节一致

生成并保留最终收敛的编译器：

```powershell
python bootstrap_fixed_point.py -o build\epic.exe
```

### 重建 v0 bootstrap compiler

`v0` 分支包含 Python stage-0、与 self-hosted `src/` 对齐的语言实现，以及 bootstrap 构建入口。脚本将目标 revision 检出到临时 detached worktree，在干净源码上运行完整不动点构建，随后清理 worktree：

这是发布与复现路径，不是日常编译路径；临时 worktree 用来隔离当前工作区的未提交改动。

```powershell
python build_epic_v0.py
```

产物：

```text
build/bootstrap-v0/epic-v0.exe
```

后续编译器、GC 或后端开发可以用该 v0 compiler 作为稳定 seed，并检查当前源码能否再次收敛：

```powershell
python bootstrap_fixed_point.py --seed build/bootstrap-v0/epic-v0.exe
```

`v0` 是可演进的 bootstrap 分支。它的 Python `bootstrap/` 与 Epic `src/` 必须保持语言语义一致；当前两边都支持 `embed "path"`，并让 `>>` / `>>=` 对有符号整数生成算术右移、对无符号整数生成逻辑右移。`>>>` / `>>>=` 不属于语言。

## 当前边界

Epic 当前仍有以下明确边界：

- 仅面向 Windows x64；尚无跨平台 ABI 承诺
- MIR 是 LLVM 风格，但并非 LLVM IR 兼容
- `ptr` 是公开 opaque address scalar；`ptr(top_level_function)` 可用于 owner-thread 同步 WinAPI callback，但不提供解引用、间接调用或隐式地址算术
- 尚无完整的 SSA / phi-node 优化器流水线
- 尚无通用汇编器或通用寄存器分配器
- 旧的 NASM 文本汇编后端路径已归档，不再活跃

## 仓库布局

```text
src/                用 Epic 编写的编译器模块和工具
runtime/            MIR 运行时辅助代码和后端运行时支持
examples/           正向学习示例
tests/              测试、验收入口与负向用例
docs/               设计笔记与实现契约
editors/            编辑器集成资源
tools/              开发辅助脚本与可选本地工具（如 lld-link.exe）
build/              忽略的本地构建输出
```

早期阶段的自举目录保存在 Git 历史与标签中。存档标签：`staged-bootstrap-archive-2026-06-30`、`python-asm-archive-2026-07-02`。

## 运行测试

```powershell
python tests/run.py                    # 模块级编译测试
python tests/examples/run.py           # examples/ 正向示例
python bootstrap_fixed_point.py   # 从 v0 分支 seed 开始的自举不动点检查
```

模块级测试：

```powershell
python tests/mir/run.py
python tests/x64/run.py
python tests/lexer/run.py
python tests/parser/run.py
python tests/link/run.py
```

重复做自举性能实验时，可使用内容寻址缓存：

```powershell
python benchmark_self_host.py --label baseline
```

脚本把 seed compiler、canonical compiler 源码、嵌入的 runtime `.ep/.ir`、测量工具版本和宿主信息纳入 key，并在 `build/cache/self-host-benchmark/` 分层保存收敛编译器、原始日志、结构化结果和文本报告。输入未变时直接复用；需要重新取得当前环境下的 wall-time 样本时加 `--refresh`，此时仍会复用相同的收敛编译器；需要连 fixed point 一起强制重建时使用 `--rebuild`。

`test_*.py` 是可直接运行的脚本，非 pytest。

## 开发规则

- 修改编译器某个区域之前，先阅读对应的 `docs/` 文件。
- 保持示例正向友好；负向测试放在 `tests/<module>/fail/`。
- 倾向清晰的编译器代码，而非过早的性能优化。
- 不维护向前兼容；公开语义变更必须显式讨论，并在同一提交中更新设计文档与意图级测试。

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
src/epic.ep          编译器驱动
src/lexer.ep         词法分析器
src/parser.ep        语法解析器
src/sema.ep          语义分析
src/ast_to_mir.ep    AST -> MIR
src/mir.ep           类型化 MIR 模型与验证器
src/mir_to_x64.ep    MIR -> 结构化 X64IR
src/x64.ep           X64IR 模型与美化打印
src/machine.ep       X64IR -> 机器码字节 + COFF 记录
src/coff.ep          最小 AMD64 COFF 写入器
src/link.ep          最小 PE 链接器
```

当前语言由公开文档、examples、意图级测试和 self-hosted fixed point 共同约束。内部 MIR、runtime 与后端可以在保持公开行为的前提下独立演进。
