# Epic

Epic 是一门**编译快速、无需随附运行时、高表达力**的语言，当前在 Windows x64 上自举运行。

最终目标是达到 Go 级的编译速度和性能，拥有 GC 运行时，以及比 Go 更丰富的表达力——ADT、f-string、直接 WinAPI 导入等。
GC 将在后续版本加入。

## 快速上手

```epic
fun main(): void {
    println("Hello, Epic!")
}
```

仓库中的 `examples/00_hello_world.ep` 就是上面的程序。从源码构建自举编译器，然后编译并运行 Hello World：

```powershell
python bootstrap_fixed_point.py -o build\epic.exe
.\build\epic.exe examples\00_hello_world.ep -o build\hello.exe
.\build\hello.exe
```

第一条命令从 Python stage-0 启动完整 bootstrap，得到达到不动点的自托管编译器；之后直接用 `epic.exe` 编译用户程序。

输出：

```
Hello, Epic!
```

从 **examples/00_hello_world.ep** 到 **examples/08_builtin_fun.ep** 按编号渐进学习。

## 语言特性

- `if`/`else`、`for` 条件循环和范围循环、`break`/`continue`、`panic`
- 字面量和 ADT 的 `match`、`_` 默认分支
- `i64`、`u64`、`i32`、`u32`、`u8`、`bool`，带检查的算术运算，显式整数转换
- `str`：字节字符串、f-string、内容等值比较、切片、分配式拼接
- 动态数组 `T[]`：字面量、零初始化、索引、`push`/`pop`/`extend`
- 堆分配的具名字段类型：具名/部分初始化；省略的引用字段为 null
- 封闭 ADT：`type Name = A | B`，显式包装构造，公共字段直接访问
- 面向字节的文件 I/O、`argv`、进程退出、类型化的直接 WinAPI 导入

完整语言边界由 `docs/` 和意图级测试共同定义。

## 代码一览

**类型与方法：**

```epic
type Parser {
    pos: i64
}

fun (p: Parser) advance(): i64 {
    p.pos += 1
    ret p.pos
}

fun main(): void {
    let p = new Parser { pos: 0 }
    println(str(p.advance()))
}
```

**ADT 与 match：**

```epic
type LiteralExpr {
    value: i64
}

type BinaryExpr {
    op: str
}

type Expr = LiteralExpr | BinaryExpr

fun print_expr(expr: Expr): void {
    match expr {
        LiteralExpr lit: { println(f"literal {lit.value}") }
        BinaryExpr binary: { println(f"binary {binary.op}") }
    }
}

fun main(): void {
    print_expr(new Expr(new LiteralExpr { value: 42 }))
}
```

**直接调用 WinAPI：**

```epic
extern "kernel32.dll" fun GetTickCount64(): u64

fun main(): void {
    println(str(GetTickCount64()))
}
```

## 当前状态

Epic v0 是一个正在收敛的 early-stage 项目，当前：

- ✅ 自举完成，已验证字节一致的不动点
- ✅ 完整编译器栈：parse → sema → MIR → x64 → machine code → COFF → PE
- ✅ 可独立编译用户程序，生成原生 Windows exe（Hello World 仅 **5.5 KiB**）
- ✅ 可直接导入 Windows DLL 函数

近期方向：

- GC 运行时
- 跨平台支持（Linux）
- 更丰富的标准库

### 当前边界

- 仅面向 Windows x64；尚无跨平台 ABI 承诺
- MIR 是 LLVM 风格，并非 LLVM IR 兼容
- 尚无完整的 SSA / phi-node 优化器流水线
- 旧的 NASM 文本汇编后端已归档，不再活跃

## 从源码构建

### 自举不动点

项目已通过完整 bootstrap fixed-point 验证：Python reference compiler 编译 Epic compiler 源码得到 `epic-py.exe`，该编译器再编译同一份源码得到 `epic-epic.exe`；两条编译路径的产物字节一致。当前收敛编译器为 **743,936 bytes（0.71 MiB）**，SHA-256 为 `bd316a0d7e07911d3a405d4dc4cdca125a35cab5d8e97a9321971ab19d00123f`。

生成并保留最终收敛的编译器：

```powershell
python bootstrap_fixed_point.py -o build\epic.exe
```

`self-hosted epic.exe` 已内嵌标准 runtime 源码，编译用户程序时无需另行提供 runtime 文件。Python reference compiler（`bootstrap/`）是当前语言的判定基准（oracle）；自托管的 Epic compiler（`src/`）在默认路径下逐阶段复现 oracle 的行为。

## 仓库布局

```text
bootstrap/          Python 参考编译器（当前语言）
src/                用 Epic 编写的编译器模块和工具
runtime/            MIR 运行时辅助代码和后端运行时支持
examples/           正向学习示例
tests/              测试、验收入口与负向用例
docs/               设计笔记与实现契约
tools/              开发辅助脚本与可选本地工具（如 lld-link.exe）
build/              忽略的本地构建输出
```

编辑器适配独立维护在
[`tree-sitter-epic`](https://github.com/picasso250/tree-sitter-epic) 和
[`zed-epic`](https://github.com/picasso250/zed-epic)。

早期阶段的自举目录保存在 Git 历史与标签中。存档标签：`staged-bootstrap-archive-2026-06-30`、`python-asm-archive-2026-07-02`。

## 运行测试

```powershell
python tests/run.py                    # 模块级编译测试
python tests/examples/run.py           # examples/ 正向示例
python bootstrap_fixed_point.py        # 从 Python 开始构建并验证自举不动点
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
- 发布前允许破坏性变化，但公开语义变更必须显式讨论并同步更新设计文档与意图级测试。
