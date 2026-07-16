# Epic 实现说明 (Epic Implementation Notes)

本文档描述当前的实现。早期版本说明（impl-v0、impl-v1、impl-v2）保留在 git 历史及标签 `staged-bootstrap-archive-2026-06-30` 中，作为历史锚点。

## 仓库布局 (Repository Layout)

```
src/                Epic-written compiler modules and tools
runtime/            MIR runtime bundles
examples/           正向学习示例程序
tests/              self-hosted 模块测试、e2e 与负向用例
tools/              开发辅助脚本与可选本地工具
docs/               文档
```

Tree-sitter grammar 与 Zed extension 是下游适配，分别维护在独立仓库
`tree-sitter-epic` 和 `zed-epic`。

当前活跃实现只有 `src/` 下的 Epic self-hosted compiler。冻结的 Python stage-0
只存在于 `v0` 标签中，用于重建 `epic-v0.exe`；当前分支不维护双实现或阶段对拍。

Epic 自举源码在 typed AST dump 中保存规范化类型文本。`src/parser.ep` 的源码类型表达使用 `TypeExpr`
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

Parser 将构造器简写降低为与空初始化器相同的 AST 形式：`new S` → `new S {}`，`new A.V` → `new A.V {}`。Codegen 没有单独的简写路径。

## Epic 编译器 (Epic Compiler)

`src/` 包含完整的自托管编译器和工具源码。构建工具按路径排序自动发现 `src/*.ep`；`src/epic.ep` 仍是显式 main。主要阶段包括：

```text
src/lexer.ep
src/parser.ep
src/sema.ep
src/ast_to_mir.ep
src/mir*.ep
src/x64.ep
src/mir_to_x64.ep
src/machine.ep
src/coff.ep
src/link.ep
src/epic.ep
```

### 自托管状态

当前 `src/epic.ep` 是活跃 driver，能够使用 Epic 编写的 frontend、MIR lowering、X64IR lowering、machine emitter、COFF writer 和 linker 编译用户程序及自身。旧 `src/codegen_support.ep` / `src/codegen.ep` 的 NASM 文本汇编路线已经删除；不要把旧 driver 的历史状态套到当前同名的 `src/epic.ep` 上。

#### v0 bootstrap branch

`v0` 是可演进的 bootstrap 分支，只实现构建当前 `dev` 所需的最小源码语义，不作为当前公开 ABI 的第二份实现。它支持只读 `s[i]` 以编译新 frontend，但保留旧 `str`/slice bootstrap 布局。`>>` / `>>=` 按左值 signedness 选择 `sar` / `shr`，所有 shift count 都必须是 `i64`；当前 `dev` 对裸整数字面量由 sema 按左侧位宽静态检查，非字面量由 MIR lowering 生成运行时检查，`v0` 为保持 bootstrap 简单，对所有 count 一律生成运行时检查。`>>>` / `>>>=` 已删除，`embed "path"` 按包含源文件解析并嵌入原始字节。

`build_epic_v0.py` 从 `v0`（或显式 `--ref`）创建临时 detached worktree，并运行该 revision 自己的 fixed-point 构建。产物名为 `epic-v0-<full-commit-hash>.exe`；commit hash 是不可变缓存键，v0 前进时不会误用旧 seed。当前 seed 本身已嵌入其 runtime 资源，不依赖调用目录中的 `runtime/`。

## 验收检查 (Acceptance)

当前仓库的推荐验收入口是：

```powershell
python tests/run.py
python tests/examples/run.py
python bootstrap_fixed_point.py
```

`tests/run.py` 使用当前 self-hosted compiler 运行模块级意图测试和 e2e；`tests/examples/run.py` 验证正向用户示例；`bootstrap_fixed_point.py` 从 `v0` 分支 seed 验证当前编译器的不动点。

`build_epic_v0.py` 导出 `build/bootstrap-v0/epic-v0-<full-commit-hash>.exe`。`bootstrap_fixed_point.py --seed <compiler.exe>` 使用已有 Epic compiler 构建当前源码的连续世代；未指定 seed 时解析当前 v0 commit，自动复用或构建该 hash 对应的 seed。

Self-hosted `epic.exe` 从自身 `.rdata` 中的只读 inline string object 读取 `src/runtime_bundle.ep` 声明的 MIR bundles。当前工作目录无需包含 `runtime/`。CLI 默认只打印最终成功信息和错误；`--verbose` 打开阶段、timing 与 stats 输出。

## 工具链 (Toolchain)

当前默认使用 `src/link.ep` 生成 PE；`src/machine.ep` 和 `src/coff.ep` 直接生成 COFF object，不依赖外部汇编器或系统 SDK import library。

## 运行时辅助代码 (Runtime Helpers)

运行时统一表示为普通 MIR function。基础 helper body、array 与 panic helper 提交在 `runtime/mir/helpers.ir`，GC 在 `runtime/mir/gc.ir`；string 和 file helper 作为标准 Epic source 与用户程序一起 parse/sema/lower。`src/runtime_bundle.ep` 将这些文件嵌入编译器；x64 后端不附加手写运行时。

GC 实现在 `runtime/mir/gc.ir`，使用单线程 non-moving conservative
mark-sweep。managed payload 由 `__ep_alloc` 统一登记；collector 扫描活动栈和
显式全局 root，并通过临时地址表识别 managed base pointer。完整不变量和限制见
`docs/gc.md`。

## 类型降级 (Type Lowering)

| 用户类型    | 内部类型          |
|------------|-------------------|
| `bool`     | `bool`            |
| `u8`       | 64-bit value；struct/storage lane 为 1 byte |
| `i16`      | 64-bit value；struct/storage lane 为 2 bytes，读取时符号扩展 |
| `u16`      | 64-bit value；struct/storage lane 为 2 bytes，读取时零扩展 |
| `i32`      | 64-bit value；struct/storage lane 为 4 bytes，读取时符号扩展 |
| `u32`      | 64-bit value；struct/storage lane 为 4 bytes，读取时零扩展 |
| `i64`      | `i64`             |
| `u64`      | `u64`             |
| `str`      | `&str`；指向 inline `{len, bytes..., NUL}` object |
| `Token`    | `&Token`          |
| `u8[]`     | `&_slice`         |
| `Token[]`  | `&_slice`         |

用户程序不编写指针类型。`&T` 和 `&&T` 仅属于 codegen 内部类型。

## 运行时布局 (Runtime Layouts)

### `str` read-only inline byte-string layout

```
str = {
    len: i64,
    bytes: u8[len],
    terminator: u8,
}

_slice = {
    data: &u8,
    len: i64,
    cap: i64,
}
```

`str` value 指向 object base。长度位于 offset 0，字节从 offset 8 开始，最后附加一个不计入 `len` 的 NUL。动态非空字符串只分配一个 `8 + len + 1` byte GC object；空结果可复用静态空字符串。字符串字面量与 `embed` 将整个 object 发射到 `.rdata`。

> 当前 `str` 是 byte-oriented string，不定义 UTF-8/Unicode 字符语义。
> `str` 只读；`s[i]` 只提供 checked `u8` read。
> `str(u8[])` 与 `bytes(str)` 都深拷贝，不共享可变 storage。

### 动态数组 / Slice Header (Dynamic Array)

Epic 用户层的 dynamic array（`T[]`）和实现层唯一的 `_slice` header 是同一个容器概念：header 持有 `data`、`len`、`cap`，并拥有可增长的 backing storage。所有数组类型共享这一份 24-byte layout metadata；这里的 “slice header” 是运行时布局命名，不表示只有 view 语义。

`cap` 字段及数组增长策略完全属于 runtime 私有实现。源码层不提供 `cap()`，用户程序只能观察逻辑长度和元素行为。

```
_slice = {
    data,
    len: i64,
    cap: i64,
}
```

基本类型 dynamic array 使用自然宽度槽：`u8/bool=1`、`i16/u16=2`、
`i32/u32=4`、`i64/u64=8` bytes。结构体、union、`str` 和其他引用数组使用
8-byte 引用槽；aggregate payload 不 inline 到 backing storage。`len` / `cap`
始终按元素计数，lowering 在每次 runtime 调用中显式传入 `slot_size`。

`str` 和 `T[]` 的存储槽可以为 `0`，表示 null reference。local variable 不允许省略初始化器，因此正常用户代码必须通过字面量、`new` 或函数返回值显式获得非 null 容器。编译器不再在容器使用点插入 materialize/ensure；对 null reference 执行 `len`、索引、切片、`push`、`pop`、`extend` 或字段访问是运行时错误。slice header 的 backing storage 仍然懒分配：非 null 空 header 的 `data` 可在首次写入时再分配。

### 结构体 (Struct)

用户结构体使用统一的 natural layout。前端按字段真实 storage size/alignment 计算 offset，最终 size
向最大 alignment 取整，并把 `size`、`align`、每字段 `offset` 显式写入 MIR。scalar/reference 的
storage size 分别为 1/2/4/8 字节；reference 始终按 8 字节对齐。后端不再从 field index 推导 offset。

Epic 表达式值仍统一经过 64-bit value representation：窄字段 load 后符号扩展或零扩展，store 时仅写目标
lane。heap allocation 使用显式 struct size；`gep struct` 的 element stride 同样使用该 size。

Extern FFI 可把只含整数 scalar 字段的非空用户 product 作为同步 borrowed pointer 参数。Sema 在 extern 声明处拒绝 `bool`、reference、nested product 和 named sum 字段；AST-to-MIR 将该参数类型降低为 `ptr`，现有 Windows x64 call lowering 直接传 payload 地址。该规则不表示 C by-value aggregate，也不允许 product 返回。

源码 `ptr(function_name)` 由 Sema 在 lexical local 未命中时解析为普通顶层函数地址；main、extern、builtin 和 method symbol 被拒绝。AST-to-MIR 直接产生 `ptr` 类型的 function symbol operand。MIR DCE 在 call edge 之外也扫描 instruction 与 terminator operand 中的内部 function symbol，保留只通过地址引用的函数。x64 lowering 将该 operand 发射为 `lea reg, [symbol]`，沿用现有 RIP-relative text relocation。

`MirParam.source_type` 保存被统一 64-bit MIR value lane 擦除前的源码参数类型。lowering 先建立 address-taken function 索引；只有这些函数在共享真实入口把 `bool/u8/i16/u16/i32/u32` 的寄存器和栈参数按自然宽度 load 并扩展到 64 bit。直接调用专用函数不额外生成入口规范化，`i64/u64/ptr/reference` 也不改写。callback 没有 thunk、closure 或 runtime helper。

### ADT (Algebraic Data Types)

ADT v1 使用 tagged payload lowering：

```text
Expr wrapper:
  tag
  payload pointer

payload:
  user-defined product instance
```

编译器流程：

1. 收集所有 `type Name { ... }` product 定义。
2. 收集 `type Name = A | B | C` sum 定义。
3. 验证 sum member 都是 product。
4. 为 wrapper 生成 tag namespace。
5. `new Expr(payload)` 生成 wrapper。
6. ADT `match` 根据 wrapper tag 分派，并绑定 payload struct。

不支持：

- primitive sum member
- implicit boxing
- tag 访问
- sum extension
- variant-specific constructor namespace

## 代码生成模型 (Codegen Model)

Epic compiler 后端发射结构化 X64IR，再编码为 AMD64 COFF object，
面向 Windows x64。

- 进程入口符号：`_start`
- 调用遵循 Windows x64 ABI：前 4 个整数/指针参数使用寄存器，其余参数写入 caller stack area
- 堆分配通过运行时辅助代码使用 Win32 heap API
- 每个函数为表达式中间结果预留临时局部变量
- 每个语句开始时重置临时变量
- 调用参数在加载到 `rcx`、`rdx`、`r8`、`r9` 之前从左到右求值到临时变量

### 降级说明 (Lowering Notes)

- **用户方法 v1**：Parser 将 `fun (p: Parser) peek(): Token` 解析为带 receiver metadata 的函数定义，并占用内部符号 `Parser__peek`。Sema 对 `p.peek(args...)` 先求 receiver 类型；如果 `Parser` 使用 `{ ... }` 声明，只查 `Parser__peek(p, args...)`，不 fallback 到 `peek(p, args...)`。普通函数名允许包含 `__`；mangled method symbol 与已有函数重复时，复用普通重复定义错误。
- **Null check postfix**：Parser 将 `expr?` 解析为 `NullCheck`。Sema 只允许 reference 类型（`str`、array、product、sum wrapper），返回 `bool`。AST-to-MIR 对被检查表达式求值一次，然后发射 `icmp.ne <ptr>, null`；`?` 本身不 deref 被检查值，不触发 null trap。
- **方法边界**：第一版只支持使用 `{ ... }` 声明的 product receiver，不支持 sum / primitive / `str` / array receiver，不支持 overload、trait、inheritance、virtual dispatch、method value 或 generic method。所有 product 都是 heap-backed reference，因此没有 value receiver / pointer receiver lowering split。

- **花括号语境 (Brace contexts)**：`new S { ... }` 在表达式位置表示初始化器；Parser 按语境解析，语义检查和 codegen 拒绝非法使用。
- **Match 冒号规则 (Match colon rule)**：每个 match 分支在模式和主体之间使用冒号。Parser 在语法级别强制此规则。
- **循环降级**：条件 `for` 解析为 `Loop` AST，降级为 condition/body/end blocks。`ForRange` 对 `start`、`end` 从左到右各求值一次；cursor 保存到 local slot，不可变的 `end` 直接作为跨 block MIR value 复用，使用 condition/body/increment/end blocks；`continue` 指向 increment，`break` 指向 end。源码没有隐式数组迭代 AST 或 iterable 协议，数组索引必须显式写 `for i: 0:len(xs)`。
- **复合赋值降级**：Parser 为所有 `op=` 语句生成 `AstAssignOp`；Sema 只接受类型完全相同的整数左值和右值。AST-to-MIR 对局部变量保存其 slot 地址；对字段先求值 object 并计算一次 `gep` 地址；对数组下标先求值并保存 base 与 index。随后读取旧值，再求值 RHS，发射对应整数 MIR op并按目标窄整数类型规范化。数组写回会用保存的 base/index 重新调用 `__ep_slice_at`，避免 RHS 扩容同一数组后使用失效的 backing 地址；base 和 index 表达式本身不会重复求值。
- **Map 删除**：内建 map 类型、语法、sema/codegen 分支和 MIR runtime helper 均已删除。普通小集合仍使用显式数组；MIR 函数/extern 与 machine symbol 的热查找使用 `src/util.ep` 中固定容量、开放寻址的 `NameIndex`，名称本身继续保存为 `str`。
- **字符串运算**：`s[i]` 调用 `__ep_str_at` 做 checked byte read；`str == str` / `!=` 调用 `__ep_str_eq` 做按字节内容比较；`str + str` 调用 `__ep_str_cat` 并产生新的 inline object。字符串下标写入、排序比较与 `str += str` 均在 sema 拒绝。

## 链接器 (Linker)

`src/link.ep` 是当前默认的窄单对象 PE64 linker，并由 Epic compiler 自身编译。

## 内置函数降级 (Builtin Lowering)

| 内置函数           | 实现方式                                    | 公开状态 |
|--------------------|---------------------------------------------|----------|
| `exit`             | `ExitProcess` 系统调用                      | 公开 |
| `print` / `println` | `WriteFile` + `GetStdHandle` 系统调用      | 公开 |
| `str(x)`           | `str` identity；整数用 decimal helper；`bool` 用 `__ep_str_from_bool`；`u8[]` 通过 `__ep_str_from_bytes` 深拷贝。product、非 `u8[]` array 不支持 | 公开 |
| `str + str`         | MIR `__ep_str_cat` 一次分配最终 inline string，并用至多两次 `RtlMoveMemory` 复制两侧内容 | 公开语法 |
| `str == str` / `!=` | `__ep_str_eq` 内容比较；`!=` 对结果取反 | 公开语法 |
| `read_file`        | MIR `__ep_read_file`，一次分配结果 slice，用栈上 `u32` 接收实际读取数 | 公开 |
| `write_file`       | MIR `__ep_write_file`，用栈上 `u32` 接收实际写入数 | 公开 |
| `str(u8[])`        | 深拷贝为只读 inline string object | 公开 |
| `bytes(str)`       | 深拷贝为独立可变 `u8[]` | 公开 |
| `cptr` / `cstr`    | `cptr` 用于支持的 array/product；`cstr` 返回 `str` 首字节的同步 borrowed pointer | 公开 |
| `str_slice`        | `__ep_str_slice` MIR helper                 | 🚫 已从 public surface 删除，internal helper |
| `str_starts_with`  | 自己写 `u8[]` 扫描                          | 🚫 已从 public surface 删除 |
| `str_find`         | 自己写 `u8[]` 扫描                          | 🚫 已从 public surface 删除 |
| `str_replace_char` | 自己写 `u8[]` 扫描                          | 🚫 已从 public surface 删除，helper 已删除 |
| `str_trim`         | 自己写 `u8[]` 扫描                          | 🚫 已从 public surface 删除，helper 已删除 |
| `xs.push(x)`      | `__ep_slice_push_slot(slice, slot_size)` 返回槽地址；lowering 发出静态宽度 store | 公开容器点调用 |
| `xs.pop()`        | `__ep_slice_pop_slot(slice, slot_size)` 返回槽地址；lowering 发出静态宽度 load；空数组 panic | 公开容器点调用 |
| `dst.extend(src)`  | 同类型数组调用 `__ep_slice_extend`；`u8[].extend(str)` 调用 `__ep_slice_extend_str` 直接复制，无中间 byte array | 公开容器点调用 |
| `len`              | 直接内联发射                                | 公开 |
| 切片语法           | 字符串用 `__ep_str_slice`；所有数组用 `__ep_slice_copy_range` 块复制 | 语法公开，helper internal |

小端加载/存储辅助函数不属于内置函数。`link.ep` 和示例使用 `u8[]`、`u64`、带检查的索引和位运算将其实现为普通的 Epic 函数。
