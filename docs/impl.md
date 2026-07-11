# Epic 实现说明 (Epic Implementation Notes)

本文档描述当前的实现。早期版本说明（impl-v0、impl-v1、impl-v2）保留在 git 历史及标签 `staged-bootstrap-archive-2026-06-30` 中，作为历史锚点。

## 仓库布局 (Repository Layout)

```
bootstrap/          Python reference compiler（Python 参考编译器）
src/                Epic-written compiler modules and tools
examples/           正向学习示例程序
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
bootstrap/ast_to_mir.py
bootstrap/mir_to_x64.py
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

Python parser 直接在 AST 声明位置保存 `EpicType`，语义分析只负责校验和补齐
`resolved_type`，后端不再接受旧的字符串类型协议。`let` 的 initializer 是 parser
级必需项：AST 中不存在“缺 initializer、等待 sema 拒绝”的 `LetNode` 状态。

`src/` 下只保留仍活跃的 Epic-written compiler modules/tools。旧 `src/epic.ep` driver 依赖已删除的 NASM codegen 线，已从 active source 中移除；Python reference compiler 的 MIR -> X64IR -> machine backend 是当前默认编译管线。

Epic 自举源码当前仍在 typed AST dump 中保存规范化类型文本，以保持 Python/Epic
oracle 对拍稳定；但 `src/parser.ep` 的源码类型表达已经使用 `TypeExpr`
结构表示。每个 AST payload 在 parser 已知源码位置时直接以 `ast_meta(line)`
构造；literal value、name、child expression 等必需字段也在同一个 `new` 中给齐，
不再经过会产生半初始化节点的 `ast_new_*` placeholder constructor。
`AstMeta.resolved_type` 在 parse 阶段是真正的 null optional，`src/sema.ep` 从
`TypeExpr` 规范化并写入类型文本；typed AST dump 用 postfix `?` 安全观察它，
`src/ast_to_mir.ep` 则要求该字段已经存在，拒绝未经 sema 的 AST。
Self-hosted sema
直接保留 `AstStructDef[]`、`AstUnionDef[]`、`AstFunDef[]` 和已分析的
`AstLet[]`，通过线性查询读取声明及其 resolved metadata；它不再建立
通用哈希符号表或复制字段、参数和返回类型。少数 MIR lowering 辅助仍通过
`epic_type_*` 查询规范文本结构；声明位置不再保存手写拼接的 `[]` 类型字符串。

### 构造器简写 (Constructor Shorthand)

Python parser 将构造器简写降低为与空初始化器相同的 AST 形式：`new S` → `new S {}`，`new A.V` → `new A.V {}`。Codegen 没有单独的简写路径。

## Epic 编译器 (Epic Compiler)

`src/` 包含自托管编译器源码：

```
src/lexer.ep
src/parser.ep
src/link.ep              # Epic 链接器（独立工具，不属于编译器不动点检查）
```

### 自托管状态

`src/lexer.ep`、`src/parser.ep`、`src/sema.ep` 和 `src/link.ep` 仍保留为 Epic-written 工具源码。旧 `src/codegen_support.ep` / `src/codegen.ep` / `src/epic.ep` 走 NASM 文本汇编路线或依赖该路线，已删除；当前编译后端以 Python reference compiler 的 MIR -> X64IR -> machine path 为准。

## 验收检查 (Acceptance)

当前 Python reference compiler 验收检查：

```powershell
python test_examples.py
python tests/mir/run.py
python tests/x64/run.py
```

`test_*bootstrap*.py` 覆盖的是 Epic 自举线，不是当前去 NASM 化的 Python
machine backend 验收入口。

## 工具链 (Toolchain)

当前 Python reference compiler 工具链路径：

- `bootstrap/link.py`（Python PE 链接器，默认）
- `tools/lld-link.exe`（可选；仅用于没有源码 `extern` 的程序）
- Windows SDK 中的 `kernel32.lib` 和 `user32.lib`

## 运行时辅助代码 (Runtime Helpers)

运行时统一在 MIR 层表达。基础 helper body 提交在 `runtime/mir/helpers.mir`，复合数组、panic 和字符串 helper 写在 `runtime/*.ep`；Python reference compiler 和 Epic 自举编译器消费同一组来源。x64 后端不再附加手写运行时。

## 类型降级 (Type Lowering)

| 用户类型    | 内部类型          |
|------------|-------------------|
| `bool`     | `bool`            |
| `u8`       | `u8`              |
| `i32`      | 8 字节整数槽，值保持 32-bit signed 规范扩展 |
| `u32`      | 8 字节整数槽，值保持 32-bit unsigned 规范扩展 |
| `i64`      | `i64`             |
| `u64`      | `u64`             |
| `str`      | `&str` today; migration target is the same representation as `&_slice_u8` |
| `Token`    | `&Token`          |
| `u8[]`     | `&_slice_u8`        |
| `Token[]`  | `&_slice_Token`     |

用户程序不编写指针类型。`&T` 和 `&&T` 仅属于 codegen 内部类型。

## 运行时布局 (Runtime Layouts)

### `str` byte-string / shared byte-slice layout

```
str = {
    data: &u8,
    len: i64,
    cap: i64,
}

_slice_u8 = {
    data: &u8,
    len: i64,
    cap: i64,
}
```

当前实现保留独立的源码级 `str` 类型，但让它与 `u8[]` 共享运行时 header 布局。字符串字面量被深拷贝到堆存储中，末尾附加一个 NUL 字节。`len` 不包含 NUL；`cap` 至少覆盖 `len + 1` 的 NUL 结尾存储。空字符串在 `len = 0` 时可能 `data = 0`。

> 当前 `str` 是 byte-oriented string，不定义 UTF-8/Unicode 字符语义。
> 语言不承诺 string literal 物理不可变：相同内容的字面量可能共享同一 buffer，
> 修改 `bytes(s)` 的结果对所有共享 view 可见。
> `str` 和 `u8[]` header 布局完全相同（`{data, len, cap}`，24 字节），
> 所以 `str(bytes)` 和 `bytes(str)` 都是 identity cast。

### 动态数组 / Slice Header (Dynamic Array)

Epic 用户层的 dynamic array（`T[]`）和实现层的 slice header（`_slice_T`）是同一个容器概念：header 持有 `data`、`len`、`cap`，并拥有可增长的 backing storage。这里的 “slice header” 是运行时布局命名，不表示只有 view 语义。

```
_slice_T = {
    data,
    len: i64,
    cap: i64,
}
```

基本类型 dynamic array 存储基本类型的值。结构体和 `str` dynamic array 存储引用。

`str` 和 `T[]` 的存储槽可以为 `0`，表示 null reference。local variable 不允许省略初始化器，因此正常用户代码必须通过字面量、`new` 或函数返回值显式获得非 null 容器。编译器不再在容器使用点插入 materialize/ensure；对 null reference 执行 `len`、`cap`、索引、切片、`push`、`pop`、`extend` 或字段访问是运行时错误。slice header 的 backing storage 仍然懒分配：非 null 空 header 的 `data` 可在首次写入时再分配。

### 结构体 (Struct)

用户结构体字段使用固定的 8 字节槽位。字段偏移为 `index * 8`。结构体大小为 `field_count * 8`。`u8` 和 `bool` 字段在其 8 字节槽位内加载/存储一个字节。

### ADT (Algebraic Data Types)

ADT v1 使用 struct union lowering：

```text
Expr wrapper:
  tag
  payload pointer

payload:
  user-defined struct instance
```

编译器流程：

1. 收集所有 struct 定义。
2. 收集 `type Name = A | B | C` union 定义。
3. 验证 union member 都是 struct。
4. 为 wrapper 生成 tag namespace。
5. `new Expr(payload)` 生成 wrapper。
6. ADT `match` 根据 wrapper tag 分派，并绑定 payload struct。

不支持：

- primitive union member
- implicit boxing
- tag 访问
- union extension
- variant-specific constructor namespace

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

- **用户方法 v1**：Parser 将 `fun (p: Parser) peek(): Token` 解析为带 receiver metadata 的函数定义，并占用内部符号 `Parser__peek`。Sema 对 `p.peek(args...)` 先求 receiver 类型；如果是用户 struct `Parser`，只查 `Parser__peek(p, args...)`，不 fallback 到 `peek(p, args...)`。普通函数名允许包含 `__`；mangled method symbol 与已有函数重复时，复用普通重复定义错误。
- **Null check postfix**：Parser 将 `expr?` 解析为 `NullCheck`。Sema 只允许 reference 类型（`str`、array、struct、ADT wrapper），返回 `bool`。AST-to-MIR 对被检查表达式求值一次，然后发射 `icmp.ne <ptr>, null`；`?` 本身不 deref 被检查值，不触发 null trap。
- **方法边界**：第一版只支持用户 struct receiver，不支持 primitive / `str` / array receiver，不支持 overload、trait、inheritance、virtual dispatch、method value 或 generic method。所有 struct 都是 heap-backed reference，因此没有 value receiver / pointer receiver lowering split。

- **花括号语境 (Brace contexts)**：`new S { ... }` 在表达式位置表示初始化器；Parser 按语境解析，语义检查和 codegen 拒绝非法使用。
- **Match 冒号规则 (Match colon rule)**：每个 match 分支在模式和主体之间使用冒号。Parser 在语法级别强制此规则。
- **循环降级**：条件 `for` 解析为 `Loop` AST，降级为 condition/body/end blocks。`ForRange` 对 `start`、`end` 从左到右各求值一次并保存到 local slot，使用 condition/body/increment/end blocks；`continue` 指向 increment，`break` 指向 end。源码没有隐式数组迭代 AST 或 iterable 协议，数组索引必须显式写 `for i: 0:len(xs)`。
- **Map 删除**：内建 map 类型、语法、sema/codegen 分支和 MIR runtime helper 均已删除。需要名称查找的编译器代码使用显式数组与线性查询。
- **字符串运算**：`str == str` / `!=` 调用 `__ep_str_eq` 做按字节内容比较；`str + str` 调用 `__ep_str_cat`，分配新的 header 和连续字节区并复制两侧内容。字符串排序比较在 sema 拒绝；`str += str` 也拒绝，避免暗示原地扩容或共享 buffer 修改。

## 链接器 (Linker)

`bootstrap/link.py` 是默认的 Python PE 链接器，支持生成的示例所需的窄单对象 PE64 路径。`src/link.ep` 是一个面向相同路径的 Epic MVP 链接器，用当前 Epic 编译器编译。

也可以通过 `--linker lld-link` 使用 `lld-link`。

## 内置函数降级 (Builtin Lowering)

| 内置函数           | 实现方式                                    | 公开状态 |
|--------------------|---------------------------------------------|----------|
| `exit`             | `ExitProcess` 系统调用                      | 公开 |
| `print` / `println` | `WriteFile` + `GetStdHandle` 系统调用      | 公开 |
| `str(x)`           | 过渡期 formatting/view 操作：`str` identity；整数用 decimal helper；`bool` 用 `__ep_str_from_bool`；`u8[]` zero-copy view。struct、非 `u8[]` array 不支持 | 公开但准备收缩 |
| `str + str`         | `__ep_str_cat`，分配新字符串并复制两侧内容 | 公开语法 |
| `str == str` / `!=` | `__ep_str_eq` 内容比较；`!=` 对结果取反 | 公开语法 |
| `read_file`        | `__ep_read_file` helper，返回 `u8[]`        | 公开 |
| `write_file`       | `__ep_write_file` helper                    | 公开 |
| `str` / `u8[]` view | 显式 zero-copy layout reinterpret；源码类型保持不同 | 公开 |
| `bytes`            | zero-copy layout reinterpret                | 公开 |
| `str_slice`        | `__ep_str_slice` MIR helper                 | 🚫 已从 public surface 删除，internal helper |
| `str_starts_with`  | 自己写 `u8[]` 扫描                          | 🚫 已从 public surface 删除 |
| `str_find`         | 自己写 `u8[]` 扫描                          | 🚫 已从 public surface 删除 |
| `str_replace_char` | 自己写 `u8[]` 扫描                          | 🚫 已从 public surface 删除，helper 已删除 |
| `str_trim`         | 自己写 `u8[]` 扫描                          | 🚫 已从 public surface 删除，helper 已删除 |
| `xs.push(x)`      | 由 codegen 为动态数组发射                   | 公开容器点调用 |
| `xs.pop()`        | `u8[]`、word arrays 和 pointer arrays 分别用 `__ep_slice_u8_pop`、`__ep_slice_i64_pop`、`__ep_slice_ptr_pop`；空数组 panic | 公开容器点调用 |
| `dst.extend(src)`  | `u8[]`、word arrays 和 pointer arrays 分别用 `__ep_slice_u8_extend`、`__ep_slice_i64_extend`、`__ep_slice_ptr_extend` | 公开容器点调用 |
| `len` / `cap`      | 直接内联发射                                | 公开 |
| 切片语法           | 字符串用 `__ep_str_slice`（internal）；数组用复制循环 | 语法公开，helper internal |

小端加载/存储辅助函数不属于内置函数。`link.ep` 和示例使用 `u8[]`、`u64`、带检查的索引和位运算将其实现为普通的 Epic 函数。
