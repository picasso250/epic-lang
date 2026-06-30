# Epic 实现说明 (Epic Implementation Notes)

本文档描述当前的实现。早期版本说明（impl-v0、impl-v1、impl-v2）保留在 git 历史及标签 `staged-bootstrap-archive-2026-06-30` 中，作为历史锚点。

## 仓库布局 (Repository Layout)

```
bootstrap/          Python reference compiler（Python 参考编译器）
src/                Epic 自托管编译器源码
runtime/            NASM 运行时辅助代码
examples/           示例程序和回归测试
tools/              NASM、LLD-Link
docs/               文档
editors/            编辑器支持
tree-sitter-epic/   Tree-sitter 语法
```

## Python 参考编译器 (Python Reference Compiler)

`bootstrap/` 包含 Python 实现：

```
bootstrap/epic.py
bootstrap/lexer.py
bootstrap/parser.py
bootstrap/ast_nodes.py
bootstrap/codegen.py
```

驱动程序从仓库根目录读取源码，将构建输出写到 `build/` 下，附加 `runtime/` 中的运行时辅助代码，用 `tools/nasm.exe` 汇编，然后通过 `link.py`（Python 链接器）或 `tools/lld-link.exe` 链接。

### 构造器简写 (Constructor Shorthand)

Python parser 将构造器简写降低为与空初始化器相同的 AST 形式：`new S` → `new S {}`，`new A.V` → `new A.V {}`。Codegen 没有单独的简写路径。

## Epic 编译器 (Epic Compiler)

`src/` 包含自托管编译器源码：

```
src/epic.ep
src/lexer.ep
src/parser.ep
src/codegen_support.ep
src/codegen.ep
src/link.ep              # Epic 链接器（独立工具，不属于编译器不动点检查）
```

### Codegen 拆分

`codegen_support.ep` 拥有共享的 codegen 数据结构、底层汇编输出辅助函数、运行时辅助代码发射以及类型辅助函数。`codegen.ep` 拥有 AST 收集、布局、表达式发射、语句发射、函数发射和程序发射。这种拆分利用了现有的全程序多文件编译模型。

## 验收检查 (Acceptance)

核心验收检查：

```powershell
python test_examples_py.py
python test_bootstrap_fixed_point.py
```

Lexer/parser/codegen 自举检查：

```powershell
python test_lexer_bootstrap.py
python test_parser_bootstrap.py
python test_codegen_bootstrap.py
```

## 工具链 (Toolchain)

当前工具链路径：

- `tools/nasm.exe`
- `tools/lld-link.exe`
- `link.py`（Python PE 链接器，默认）
- Windows SDK 中的 `kernel32.lib` 和 `user32.lib`

## 运行时辅助代码 (Runtime Helpers)

驱动程序在发射的程序汇编代码之后附加运行时汇编辅助代码：

```
runtime/str_alloc.asm
runtime/bytes.asm
runtime/str_cat.asm
runtime/str_slice.asm
runtime/str_replace_char.asm
runtime/str_starts_with.asm
runtime/str_find.asm
runtime/str_trim.asm
runtime/extend_i8.asm
runtime/itoa.asm
runtime/argv.asm
runtime/system.asm
runtime/read_file.asm
runtime/write_file.asm
```

## 类型降级 (Type Lowering)

| 用户类型    | 内部类型          |
|------------|-------------------|
| `bool`     | `bool`            |
| `u8`       | `u8`              |
| `i64`      | `i64`             |
| `u64`      | `u64`             |
| `str`      | `&str`            |
| `Token`    | `&Token`          |
| `u8[]`     | `&_arr_u8`        |
| `Token[]`  | `&_arr_Token`     |

用户程序不编写指针类型。`&T` 和 `&&T` 仅属于 codegen 内部类型。

## 运行时布局 (Runtime Layouts)

### 字符串 (String)

```
str = {
    data: &u8,
    len: i64,
}
```

字符串字面量被深拷贝到堆存储中，末尾附加一个 NUL 字节。`len` 不包含 NUL。空字符串在 `len = 0` 时可能 `data = 0`。

### 动态数组 (Dynamic Array)

```
_arr_T = {
    data,
    len: i64,
    cap: i64,
}
```

基本类型数组存储基本类型的值。结构体和 `str` 数组存储引用。

### 结构体 (Struct)

用户结构体字段使用固定的 8 字节槽位。字段偏移为 `index * 8`。结构体大小为 `field_count * 8`。`u8` 和 `bool` 字段在其 8 字节槽位内加载/存储一个字节。

### ADT (代数数据类型, Algebraic Data Types)

ADT 值是指向 16 字节 header 对象的引用：

- header 槽位 0：数字标签（numeric tag，`i64`）
- header 槽位 1：指向堆分配的有效载荷对象的指针

有效载荷布局复用结构体字段布局规则。变体标签（variant tags）按声明顺序排列。ADT 零值是标签 `0` 加上第一个变体的零值有效载荷。

## 代码生成模型 (Codegen Model)

后端发射 NASM x64 汇编，面向 Windows x64。

- 进程入口符号：`_start`
- 调用遵循 Windows x64 ABI（最多 4 个寄存器参数）
- 堆分配通过运行时辅助代码使用 Win32 heap API
- 每个函数为表达式中间结果预留临时局部变量
- 每个语句开始时重置临时变量
- 调用参数在加载到 `rcx`、`rdx`、`r8`、`r9` 之前从左到右求值到临时变量

### 降级说明 (Lowering Notes)

- **花括号消歧义 (Brace disambiguation)**：出现在表达式或模式位置的后缀 `{ ... }` 始终被解析为初始化器或模式有效载荷候选。语义检查和 codegen 拒绝非法使用。
- **Match 冒号规则 (Match colon rule)**：每个 match 分支在模式和主体之间使用冒号。Parser 在语法级别强制此规则。
- **ADT match 降级**：对检视表达式求值一次，加载 tag，对变体标签做线性比较/跳转链，从 header 槽位 1 加载 `data`，按布局偏移绑定有效载荷字段，发射分支代码块。
- **Map 降级**：`map[str]T` 使用线性探测或基于动态数组的条目表。`m[key] = value` 插入或覆盖。不存在的键查找返回零值。`map_has` 区分是否缺失。

## 链接器 (Linker)

`link.py` 是默认的 Python PE 链接器，支持生成的示例所需的窄单对象 PE64 路径。`src/link.ep` 是一个面向相同路径的 Epic MVP 链接器，用当前 Epic 编译器编译。

也可以通过 `--linker lld-link` 使用 `lld-link`。

## 内置函数降级 (Builtin Lowering)

| 内置函数           | 实现方式                                    |
|--------------------|---------------------------------------------|
| `putc`             | `WriteFile` 系统调用                        |
| `putstr`           | 写入 `s.data` 共 `s.len` 个字节             |
| `itoa`             | `_itoa` 运行时辅助函数                      |
| `system`           | `_system` 运行时辅助函数                    |
| `read_file`        | `_read_file` 运行时辅助函数，返回 `u8[]`    |
| `write_file`       | 通过 `_write_file` 写入 `u8[]` 有效载荷     |
| `str` (`u8[]`)     | `_str_alloc` 运行时辅助函数                 |
| `bytes`            | `_bytes` 运行时辅助函数                     |
| `str_new`          | `_str_alloc` 运行时辅助函数                 |
| `str_slice`        | `_str_slice` 运行时辅助函数                 |
| `str_starts_with`  | `_str_starts_with` 运行时辅助函数           |
| `str_find`         | `_str_find` 运行时辅助函数                  |
| `str_trim`         | `_str_trim` 运行时辅助函数                  |
| `push`             | 由 codegen 为动态数组发射                   |
| `extend`           | 字节数组用 `_extend_i8`；其他类型用复制循环 |
| `len` / `cap`      | 直接内联发射                                |
| 切片语法           | 字符串用 `_str_slice`；数组用复制循环        |

小端加载/存储辅助函数不属于内置函数。`link.ep` 和示例使用 `u8[]`、`u64`、带检查的索引和位运算将其实现为普通的 Epic 函数。
