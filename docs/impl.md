# Epic 实现说明 (Epic Implementation Notes)

本文档描述当前的实现。早期版本说明（impl-v0、impl-v1、impl-v2）保留在 git 历史及标签 `staged-bootstrap-archive-2026-06-30` 中，作为历史锚点。

## 仓库布局 (Repository Layout)

```
bootstrap/          Python reference compiler（Python 参考编译器）
src/                Epic 自托管编译器源码
examples/           示例程序和回归测试
tools/              本地工具二进制；LLD-Link 可选
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
bootstrap/sema.py
bootstrap/mir_codegen.py
bootstrap/mir_lower.py
bootstrap/machine.py
```

驱动程序从仓库根目录读取源码，将构建输出写到 `build/` 下，执行：

```text
parse/merge -> semantic analysis -> MIR -> X64IR -> machine obj -> link
```

`compile_files()` 仍会写一个 `.asm` 形式的 X64IR pretty print 作为调试输出，
但 Python reference compiler 不再支持 `--backend asm`，也不再调用
`tools/nasm.exe`。旧 Python asm 后端已归档到 tag
`python-asm-archive-2026-07-02`，需要排查历史行为时从该 tag 对比。

`src/` 下的 Epic-written compiler 仍属于旧 NASM-oriented 自举线；本轮 Python
reference compiler 的 machine backend 先行，不同步维护 `src/`。

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

`codegen_support.ep` 拥有共享的 codegen 数据结构、底层汇编输出辅助函数以及类型辅助函数。`codegen.ep` 拥有 AST 收集、布局、表达式发射、语句发射、函数发射和程序发射。这种拆分利用了现有的全程序多文件编译模型。

## 验收检查 (Acceptance)

当前 Python reference compiler 验收检查：

```powershell
python test_examples_py.py
python tests/mir/run.py
python tests/x64/run.py
```

`test_*bootstrap*.py` 覆盖的是 Epic 自举线，不是当前去 NASM 化的 Python
machine backend 验收入口。

## 工具链 (Toolchain)

当前 Python reference compiler 工具链路径：

- `link.py`（Python PE 链接器，默认）
- `tools/lld-link.exe`（可选）
- Windows SDK 中的 `kernel32.lib` 和 `user32.lib`

## 运行时辅助代码 (Runtime Helpers)

Python machine backend 的运行时片段在 `bootstrap/x64_runtime.py` 和
`bootstrap/mir_runtime_helpers.py` 中发射。旧 `runtime/*.asm` 路线已删除。

## 类型降级 (Type Lowering)

| 用户类型    | 内部类型          |
|------------|-------------------|
| `bool`     | `bool`            |
| `u8`       | `u8`              |
| `i32`      | 8 字节整数槽，值保持 32-bit signed 规范扩展 |
| `u32`      | 8 字节整数槽，值保持 32-bit unsigned 规范扩展 |
| `i64`      | `i64`             |
| `u64`      | `u64`             |
| `str`      | `&str`            |
| `Token`    | `&Token`          |
| `u8[]`     | `&_slice_u8`        |
| `Token[]`  | `&_slice_Token`     |

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

> `str` 表面只读，但底层 buffer 可通过 `bytes()` 以 `u8[]` view 修改。
> 语言不承诺 string literal 物理不可变：相同内容的字面量可能共享同一 buffer，
> 修改 `bytes(s)` 的结果对所有共享 view 可见。

> ⚠ 当前 sema 不阻止 `s[i] = v` 或 `s[i] += v`。这不是去噪规则，而是实现简化。
> `str` 和 `u8[]` header 布局完全相同（`{data, len, cap}`，24 字节），
> 所以 `str(bytes)` 和 `bytes(str)` 都是 identity cast。

### 动态数组 (Dynamic Array)

```
_slice_T = {
    data,
    len: i64,
    cap: i64,
}
```

基本类型数组存储基本类型的值。结构体和 `str` 数组存储引用。

`str`、`T[]`、`map[str]T` 的存储槽可以为 `0`，表示尚未 materialize 的空容器。字段访问或其他容器使用点会插入 ensure：如果槽为 `0`，就写入一个空 header。slice/map header 的 backing storage 仍然懒分配：`push` 或 map set 首次写入时再分配 `data` / `entries`。

### 结构体 (Struct)

用户结构体字段使用固定的 8 字节槽位。字段偏移为 `index * 8`。结构体大小为 `field_count * 8`。`u8` 和 `bool` 字段在其 8 字节槽位内加载/存储一个字节。

### ADT (代数数据类型, Algebraic Data Types) — 已移除

> **⚠ 历史特性 (Historical)**  
> ADT 已从 Epic 自举核心移除。详见 [`self-host-core.md`](self-host-core.md)。
>
> 旧实现使用 16 字节 header（tag + payload pointer），已从 Python reference compiler 中清除。

## 代码生成模型 (Codegen Model)

Python reference compiler 后端发射结构化 X64IR，再编码为 AMD64 COFF object，
面向 Windows x64。

- 进程入口符号：`_start`
- 调用遵循 Windows x64 ABI（最多 4 个寄存器参数）
- 堆分配通过运行时辅助代码使用 Win32 heap API
- 每个函数为表达式中间结果预留临时局部变量
- 每个语句开始时重置临时变量
- 调用参数在加载到 `rcx`、`rdx`、`r8`、`r9` 之前从左到右求值到临时变量

### 降级说明 (Lowering Notes)

- **花括号语境 (Brace contexts)**：`new S { ... }` 在表达式位置表示初始化器；Parser 按语境解析，语义检查和 codegen 拒绝非法使用。
- **Match 冒号规则 (Match colon rule)**：每个 match 分支在模式和主体之间使用冒号。Parser 在语法级别强制此规则。
- **Map 降级**：Python reference compiler 将 `map[str]i64`、`map[str]bool`、`map[str]str` 降级为 str-keyed word map。entry 为 `{key, value, occupied}` 三个 word，key 比较调用 `__ep_str_eq`。`m[key] = value` 插入或覆盖，满时扩容。不存在的键查找返回值类型零值。`map_has` 区分是否缺失，`map_del` 使用 swap-delete 并返回是否删除成功。`new map[str]T { ... }` 降级为一次 map new 加按源码顺序执行的 map set。

## 链接器 (Linker)

`link.py` 是默认的 Python PE 链接器，支持生成的示例所需的窄单对象 PE64 路径。`src/link.ep` 是一个面向相同路径的 Epic MVP 链接器，用当前 Epic 编译器编译。

也可以通过 `--linker lld-link` 使用 `lld-link`。

## 内置函数降级 (Builtin Lowering)

| 内置函数           | 实现方式                                    | 公开状态 |
|--------------------|---------------------------------------------|----------|
| `exit`             | `ExitProcess` 系统调用                      | 公开 |
| `print` / `println` | `WriteFile` + `GetStdHandle` 系统调用      | 公开 |
| `str(n)`           | `__ep_str_from_i64` / `__ep_str_from_bool` 等 helper | 公开 |
| `system`           | `__ep_system_cmd` helper                    | 公开 |
| `read_file`        | `__ep_read_file` helper，返回 `u8[]`        | 公开 |
| `write_file`       | `__ep_write_file` helper                    | 公开 |
| `str` (`u8[]`)     | zero-copy layout reinterpret                | 公开 |
| `bytes`            | zero-copy layout reinterpret                | 公开 |
| `str_slice`        | `__ep_str_slice` MIR helper                 | 🚫 已从 public surface 删除，internal helper |
| `str_starts_with`  | 自己写 `u8[]` 扫描                          | 🚫 已从 public surface 删除 |
| `str_find`         | 自己写 `u8[]` 扫描                          | 🚫 已从 public surface 删除 |
| `str_replace_char` | 自己写 `u8[]` 扫描                          | 🚫 已从 public surface 删除，helper 已删除 |
| `str_trim`         | 自己写 `u8[]` 扫描                          | 🚫 已从 public surface 删除，helper 已删除 |
| `push`             | 由 codegen 为动态数组发射                   | 公开 |
| `extend`           | 字节数组用 `__ep_slice_u8_extend`；其他类型用复制循环 | 公开 |
| `len` / `cap`      | 直接内联发射                                | 公开 |
| 切片语法           | 字符串用 `__ep_str_slice`（internal）；数组用复制循环 | 语法公开，helper internal |

小端加载/存储辅助函数不属于内置函数。`link.ep` 和示例使用 `u8[]`、`u64`、带检查的索引和位运算将其实现为普通的 Epic 函数。
