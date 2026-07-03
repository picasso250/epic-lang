# Epic MIR 设计

本文档定义 Epic **目标** MIR。MIR 是删除 NASM 计划里的核心中间层，但它不是 NASM 文本的结构化包装，也不是完整 LLVM IR 兼容层。

MIR 的目标是：让编译链路从“直接生成巨大文本 ASM”改为“生成结构化 IR，再 lowering 到 LowMIR/X64MIR，最后输出 ASM pretty print 或机器码”。

> **关于 MIR 内部的 `I8` 类型**：本文多处示例使用 `i8` 作为 MIR 底层 byte storage type。
> 这是 MIR 内部表示，与 Epic 语言的 public type 无关。Epic 语言 public surface 只暴露 `u8` 作为 byte 类型，不提供 signed `i8`。
> MIR 的 `I8` 当前仍保留此名，后续可能重命名为 `BYTE` 或 `U8`。

对应路线见 `docs/remove-nasm-plan.md`。

## Target vs Current Implementation

本文档描述的 MIR 是 **目标设计**，不是当前 Python prototype 的真实快照。

| 方面 | 目标 MIR | 当前 Python prototype |
|------|----------|----------------------|
| High-level MIR ops | 禁止 `struct.new`、`field.load`、`field.store`、`array.push` | ✅ validator 已拒绝这些 op；`mir_codegen.py` 当前也未再发这些 op |
| Runtime helper call in MIR | 降到 MIR `call` + MIR helper function | ⚠️ 当前降到 MIR `call` + x64-backed runtime helper；helper 尚未是 `MirFunction` |
| Runtime helper impl | `MirFunction` 注入，走正常 MIR→X64 lowering | ❌ 当前全部手写在 `mir_lower._emit_*()` 中，作为 x64 asm 标签直接生成 |
| 注入策略 | 按需注入（`required_helpers` tracking） | ❌ 无条件注入全部 extern + 全部 helper 函数体 |
| struct layout | 显式 typed `MirStruct` dataclass 字段 | ⚠️ 已在 `MirProgram.structs` 上，但 schema 是 loose dict，不是 typed dataclass |
| symbol 拼写 | `@name` 统一规则 | ⚠️ `main`、`__ep_str_from_i64`、`ExitProcess` 混用，未统一到 `@` 前缀 |
| 命名 | 语义名：`i64_to_str`, `bool_to_str`, `bytes_to_str`, `str_to_bytes` | ✅ 前缀已分层 `__ep_*`/`__epx_*`，语义名留待后续 commit |
| 前缀分层 | `__epx_` = x64 primitive（`__epx_alloc`），`__ep_` = compiler-internal MIR helper（`__ep_str_eq`） | ✅ 已分离 |
| `alloca` 复合类型 | 只允许标量 `alloca`；struct/array/string 必须 heap 分配 | ✅ 当前实现已遵守此规则 |

> **使用本文档时请注意**：所有 code block 中的 MIR 示例是 target 格式，不代表当前 `mir_codegen.py` 的实际输出。当前实现的实际 MIR 行为通过 `docs/x64-instruction-subset.md`（lowering 后的 X64IR 合约）和 `docs/mir-lowering-contract.md`（lowering 规则）描述。

当前实现债的跟踪见 `docs/x64-instruction-subset.md §8 Design audit`。

## 1. 定位

Epic MIR 是一个 LLVM-like 的中层 IR，核心形态包括：

- module-level globals / imports / functions。
- function。
- basic block。
- terminator。
- typed value。
- 三地址指令。
- 显式 `load` / `store`。
- 显式 `gep` 地址计算。
- 显式 `br` / `condbr`。

MIR 不应该只是“结构化 x64 汇编”。如果 MIR 太贴近 x64，那么 `if`、`while`、`+`、`-`、比较、短路逻辑都会过早降成寄存器和跳转，后续调试、优化、自举实现都会不舒服。

MIR 也不应该保留 AST 级便捷语义。`struct.new`、`field.load`、`field.store`、`array.push` 这类 op 不能作为目标 MIR 合约；它们必须在 AST -> MIR 期间分解成 `call`、`gep`、`load`、`store`、branch 等低层操作，或者明确放进一个迁移期 HighMIR。

MIR 也不追求完整 LLVM IR 兼容。第一版只实现 Epic 当前需要的最小集合。

## 2. 编译链路

MIR 在编译链路里的主形态是内存中的结构化对象，不是字符串文本。

```text
lexer -> parser -> MIR struct -> LowMIR/X64MIR -> asm/machine -> link -> exe
```

第一版不实现 text MIR parser。

text MIR 只是 pretty printer 输出，用于：

- 调试。
- 审计。
- golden test。
- 人工比较 AST lowering 是否正确。

虽然 text MIR 不是主协议，但 pretty printer 不能丢失关键信息。默认输出完整类型、内存访问类型、call signature、global/import type。

未来如果实现 text MIR parser，可以允许人类手写时省略可推导类型；但 pretty printer 默认不省略。

## 3. 第一版设计原则

- 参考 LLVM IR 的核心结构，但不兼容 LLVM IR。
- 使用 basic block + terminator 表达控制流。
- 使用三地址临时值 + mutable local address，不直接做 SSA。
- 源码局部变量 lowering 成地址，例如 `%x.addr`。
- 表达式结果 lowering 成不可变临时 value，例如 `%x0`、`%x1`、`%sum`。
- 变量读取是 `load`。
- 变量赋值是 `store`。
- 结构体字段、数组元素、字符串数据等地址通过 `gep` 计算，再由 `load/store` 访问。
- heap 分配是普通 `call`，例如 `call ptr @epic.alloc(i64 %size)`；MIR 不提供 `struct.new`。
- 复合类型（struct/array/string）不能在栈上分配；所有复合类型实例必须通过 heap 分配的 `ptr` 访问，不可使用 `alloca` 分配。
- 指针类型采用现代 LLVM opaque pointer 思路：value 类型写 `ptr`，被访问类型由 `load/store/gep` 指令携带。
- bool 类型文本写作 `bool`，不写作 `i1`。
- block 引用写作 `label %name`，block 定义写作 `name:`。
- 函数、全局、import 这类 module-level symbol 使用 `@name`。
- import 和普通函数在 call 处不额外区分；它们在 module symbol table 里区分。
- text MIR pretty printer 默认打印完整类型信息。

## 4. 名字规则

### 4.1 Local value

局部 value 使用 `%` 前缀：

```text
%x0
%x1
%sum
%tmp3
```

这些 value 是不可变的。一个 value 一旦定义，后面不能被重新赋值。

### 4.2 Local variable address

源码局部变量的存储位置使用 `%name.addr`：

```text
%x.addr: ptr = alloca i64
```

`%x.addr` 表示变量 `x` 的地址/槽位，类似 C 里的 `&x`。

### 4.3 Block label

block 定义不带 `%`：

```text
then:
  ret i64 1
```

block 引用带 `%`，并带 `label` 类型：

```text
br label %then
condbr bool %c0, label %then, label %else
```

### 4.4 Module-level symbol

函数、全局变量、字符串常量、import 使用 `@` 前缀：

```text
@main
@foo
@str.0
@WriteFile
```

## 5. 类型

第一版 MIR 类型集合：

```text
i64
u64
i8
u8
bool
void
ptr
array N x T
struct Name
```

说明：

- `bool` 是 Epic MIR 的逻辑布尔类型，文本不写作 `i1`。
- `ptr` 是 opaque pointer，不携带 pointee type。
- `array N x T` 主要用于 global string / static data 描述，也可作为 `gep` 的 source element type。
- `struct Name` 用于结构体、字符串对象、map 等 layout 描述，也可作为 `gep` 的 source element type。
- validator 不能依赖 pointer pointee type；需要检查 `load/store` 的访问类型、`gep` 的 source element type 和 index 合法性。

第一版可以先只实际实现：

```text
i64
i8
bool
void
ptr
array N x i8
```

其余类型可以先作为设计占位。

## 6. 变量、地址和值

源码变量、MIR 地址和值是三种不同概念：

```text
源码变量 x      -> %x.addr 这个地址
读取 x          -> load 出一个值，比如 %x0
计算 x + 1      -> add 生成新值，比如 %x1
赋值 x = x + 1  -> store 回 %x.addr
```

示例：

```text
%x.addr: ptr = alloca i64
store i64 0, ptr %x.addr
%x0: i64 = load i64, ptr %x.addr
%x1: i64 = add i64 %x0, i64 1
store i64 %x1, ptr %x.addr
ret i64 %x1
```

含义：

- `%x.addr` 是变量 `x` 的存储位置。
- `%x0` 是某一刻从 `%x.addr` 读出来的值。
- `%x1` 是 `%x0 + 1` 的计算结果。
- `%x0`、`%x1` 一旦定义就不再改变。
- 真正会改变的是 `%x.addr` 指向的位置里存放的内容。

这让第一版 MIR 不需要立即实现 SSA / phi，也能保持清晰的数据流。

## 7. Text MIR 打印原则

text MIR 是调试输出，不是主输入格式。因此 pretty printer 采用“信息完整优先”原则。

规则：

- 不为了短而省略类型。
- value result 显式打印结果类型。
- 普通指令的每个 operand 也显式打印类型。
- pointer operand 类型打印为 `ptr`；访问类型由 `load/store/gep` 自己打印。
- call 显式打印返回类型、callee 和参数类型。
- global/import 显式打印类型或签名。
- call 处不写 `import`；是否 import 由 module-level declaration 决定。

示例：

```text
%x.addr: ptr = alloca i64
store i64 0, ptr %x.addr
%x0: i64 = load i64, ptr %x.addr
%x1: i64 = add i64 %x0, i64 1
store i64 %x1, ptr %x.addr
ret i64 %x1
```

不采用省略形式：

```text
%x1 = add %x0, 1
%x0 = load %x.addr
```

未来 parser 可以接受省略形式，但 pretty printer 不输出省略形式。

## 8. Module 结构

一个 MIR module 包含：

```text
module
  imports
  globals
  functions
```

示例：

```text
import @ExitProcess: fn(i64) -> void
import @WriteFile: fn(ptr, ptr, i64, ptr, ptr) -> bool

@str.0: array 6 x i8 = global c"hello\00"

fn @main() -> i64 {
entry:
  ret i64 0
}
```

说明：

- `@ExitProcess` 和 `@WriteFile` 是 import，由 module import table 声明。
- call 处只写 `call ... @WriteFile(...)`，不写 `call import`。
- `@str.0` 是 global symbol。
- `@main` 是函数 symbol。

## 9. Function

函数文本格式：

```text
fn @name(param_type %param, ...) -> return_type {
entry:
  ...
}
```

示例：

```text
fn @add1(i64 %x) -> i64 {
entry:
  %r: i64 = add i64 %x, i64 1
  ret i64 %r
}
```

参数是 function entry 可用的 typed value。参数本身不可变。

如果源码参数需要作为可变局部变量使用，AST lowering 可以创建 `.addr` 并 store 初始值：

```text
fn @f(i64 %x) -> i64 {
entry:
  %x.addr: ptr = alloca i64
  store i64 %x, ptr %x.addr
  %x0: i64 = load i64, ptr %x.addr
  ret i64 %x0
}
```

## 10. Basic block 与 terminator

每个 block 包含普通指令和一个 terminator。

```text
block:
  instruction*
  terminator
```

第一版 terminator：

```text
br label %target
condbr bool %cond, label %then, label %else
ret void
ret T %value
```

规则：

- 每个 block 必须有且只有一个 terminator。
- terminator 必须是 block 最后一条指令。
- 普通指令不能出现在 terminator 后面。
- `condbr` 的 condition 类型必须是 `bool`。
- `ret` 类型必须匹配函数返回类型。

## 11. 指令集合

### 11.1 常量

```text
%v: i64 = const i64 123
%b: bool = const bool true
%c: i8 = const i8 65
%p: ptr = const ptr null
```

### 11.2 算术

```text
%r: i64 = add i64 %a, i64 %b
%r: i64 = sub i64 %a, i64 %b
%r: i64 = mul i64 %a, i64 %b
%r: i64 = div i64 %a, i64 %b
%r: i64 = mod i64 %a, i64 %b
```

第一版算术主要支持 `i64`。`u64`、`i8`、`u8` 可以后续补充或在 lowering 前扩展/截断。

### 11.2.1 指针整数转换

```text
%n: i64 = ptrtoint ptr %p to i64
```

第一版只需要 `ptr -> i64`，用于 LLVM-like `gep null, 1` 大小计算。反向 `inttoptr` 不作为当前目标需求。

### 11.3 比较

```text
%c: bool = icmp.eq i64 %a, i64 %b
%c: bool = icmp.ne i64 %a, i64 %b
%c: bool = icmp.lt i64 %a, i64 %b
%c: bool = icmp.le i64 %a, i64 %b
%c: bool = icmp.gt i64 %a, i64 %b
%c: bool = icmp.ge i64 %a, i64 %b
```

`icmp.*` 返回 `bool`。

### 11.4 逻辑

```text
%r: bool = and bool %a, bool %b
%r: bool = or bool %a, bool %b
%r: bool = not bool %a
```

短路语义不由 `and` / `or` 指令表达。源码里的 `&&` / `||` 由 AST lowering 生成 basic blocks 和 `condbr`。

### 11.5 内存

```text
%x.addr: ptr = alloca i64
%x0: i64 = load i64, ptr %x.addr
store i64 %x0, ptr %x.addr
```

规则：

- `alloca T` 返回 `ptr`。
- `load T, ptr` 返回 `T`。
- `store T value, ptr addr` 无返回值。
- `load/store` 的 value type 由指令显式携带；pointer 自身不携带 pointee type。

### 11.6 地址计算

MIR 使用 LLVM-like `gep` 表达地址计算。`gep` 只计算地址，不访问内存；字段读取必须是 `gep` 后接 `load`，字段写入必须是 `gep` 后接 `store`。

```text
%p: ptr = gep i8, ptr %base, i64 %byte_offset
%p: ptr = gep i64, ptr %base, i64 %index
%field: ptr = gep struct Pair, ptr %obj, i64 0, i32 1
```

规则：

- `gep SourceType, ptr base, indices...` 返回 `ptr`。
- `SourceType` 是地址计算使用的元素或聚合类型，不是 pointer pointee type。
- `gep` 不做 bounds check，不读写内存。
- 结构体字段使用常量字段 index；数组/指针元素可以使用运行期 index。
- 运行期 bounds check 必须由显式 `icmp` / `condbr` / panic call 等指令表达。

### 11.7 heap 对象与 aggregate 访问

目标 MIR 不提供 `struct.new`、`field.load`、`field.store`。heap 上的 struct 分配和初始化应分解为大小计算、allocator call、字段地址计算和 store。

复合类型的访问必定通过指向 heap 的 `ptr` 间接进行。MIR 不允许使用 `alloca` 在栈上分配 struct/array/string；`alloca` 只能用于标量（`i64`、`i8`、`bool`）或指向复合类型的指针槽位。

现代 LLVM 默认使用 opaque pointer；Epic MIR 也采用这个方向。因此不需要 typed pointer 时代常见的 `i8* -> %MyStruct* bitcast`。

示例：

```text
import @epic.alloc: fn(i64) -> ptr

fn @make_pair(i64 %a, i64 %b) -> ptr {
entry:
  %size_ptr: ptr = gep struct Pair, ptr null, i64 1
  %size: i64 = ptrtoint ptr %size_ptr to i64
  %obj: ptr = call ptr @epic.alloc(i64 %size)
  %f0: ptr = gep struct Pair, ptr %obj, i64 0, i32 0
  store i64 %a, ptr %f0
  %f1: ptr = gep struct Pair, ptr %obj, i64 0, i32 1
  store i64 %b, ptr %f1
  ret ptr %obj
}
```

读取字段：

```text
%f1: ptr = gep struct Pair, ptr %obj, i64 0, i32 1
%value: i64 = load i64, ptr %f1
```

Array header、string header 都按同样规则处理：layout 由 `struct` / `array` 类型描述，地址由 `gep` 计算，访问由 `load/store` 完成。复杂操作如 `array.push` 应 lowering 成显式控制流和内存操作，或者是普通 runtime call，例如 `call void @array_push_i64(ptr %arr, i64 %value)`。

### 11.8 调用

函数调用：

```text
%r: i64 = call i64 @foo(i64 %x, i64 %y)
call void @print(i64 %x)
%ok: bool = call bool @WriteFile(ptr %h, ptr %buf, i64 %len, ptr %written, ptr %ov)
```

规则：

- callee 使用 `@name`。
- call 处不区分 import / Epic function / runtime helper。
- callee kind 由 module-level declaration 决定。
- 参数类型必须匹配 callee signature。
- 返回类型必须匹配 callee signature。

示例：

```text
import @WriteFile: fn(ptr, ptr, i64, ptr, ptr) -> bool

fn @main() -> i64 {
entry:
  %ok: bool = call bool @WriteFile(ptr %h, ptr %buf, i64 %len, ptr %written, ptr %ov)
  ret i64 0
}
```

## 12. 控制流示例

### 12.1 if

Epic 源码：

```text
let a = 1;
let b = 2;
if a < b {
  return a + b;
} else {
  return b - a;
}
```

MIR：

```text
fn @main() -> i64 {
entry:
  %a.addr: ptr = alloca i64
  %b.addr: ptr = alloca i64
  store i64 1, ptr %a.addr
  store i64 2, ptr %b.addr
  %a0: i64 = load i64, ptr %a.addr
  %b0: i64 = load i64, ptr %b.addr
  %c0: bool = icmp.lt i64 %a0, i64 %b0
  condbr bool %c0, label %then, label %else

then:
  %a1: i64 = load i64, ptr %a.addr
  %b1: i64 = load i64, ptr %b.addr
  %x: i64 = add i64 %a1, i64 %b1
  ret i64 %x

else:
  %b2: i64 = load i64, ptr %b.addr
  %a2: i64 = load i64, ptr %a.addr
  %y: i64 = sub i64 %b2, i64 %a2
  ret i64 %y
}
```

### 12.2 while

Epic 源码：

```text
let x = 0;
while x < 10 {
  x = x + 1;
}
return x;
```

MIR：

```text
fn @main() -> i64 {
entry:
  %x.addr: ptr = alloca i64
  store i64 0, ptr %x.addr
  br label %loop

loop:
  %x0: i64 = load i64, ptr %x.addr
  %c0: bool = icmp.lt i64 %x0, i64 10
  condbr bool %c0, label %body, label %done

body:
  %x1: i64 = add i64 %x0, i64 1
  store i64 %x1, ptr %x.addr
  br label %loop

done:
  %r: i64 = load i64, ptr %x.addr
  ret i64 %r
}
```

### 12.3 short-circuit &&

源码：

```text
if a != 0 && b != 0 {
  return 1;
}
return 0;
```

MIR：

```text
fn @main() -> i64 {
entry:
  %a0: i64 = load i64, ptr %a.addr
  %c0: bool = icmp.ne i64 %a0, i64 0
  condbr bool %c0, label %rhs, label %else

rhs:
  %b0: i64 = load i64, ptr %b.addr
  %c1: bool = icmp.ne i64 %b0, i64 0
  condbr bool %c1, label %then, label %else

then:
  ret i64 1

else:
  ret i64 0
}
```

说明：短路由 block 和 `condbr` 表达，不用普通 `and` 指令表达。

## 13. 数据模型草案

Python 原型可以用 dataclass 表示。

```text
MirProgram
  imports: list[MirImport]
  globals: list[MirGlobal]
  structs: list[MirStruct]
  functions: list[MirFunction]

MirImport
  name: str                  # @WriteFile
  signature: MirSignature
  dll: str?                  # 可选，后端/PE writer 可能需要

MirGlobal
  name: str                  # @str.0
  type: MirType
  init: MirGlobalInit

MirStruct
  name: str                  # Pair / str / _slice_i64
  fields: list[MirField]
  size: int?                 # 可选缓存；可以由 layout pass 计算

MirField
  name: str
  type: MirType

MirFunction
  name: str                  # @main
  params: list[MirParam]
  return_type: MirType
  blocks: list[MirBlock]

MirParam
  name: str                  # %x
  type: MirType

MirBlock
  name: str                  # entry / then / else
  instructions: list[MirInst]
  terminator: MirTerminator

MirInst
  result: MirValue?          # None for store / call void etc.
  op: MirOp
  operands: list[MirOperand]
  type: MirType?             # result type or primary op type
  comment: str?

MirTerminator
  Br(target: MirBlockRef)
  CondBr(cond: MirValue, then_target: MirBlockRef, else_target: MirBlockRef)
  Ret(value: MirOperand?)

MirOperand
  Value(name, type)
  ConstInt(value, type)
  ConstBool(value)
  ConstNull(type=ptr)
  Global(name, type)
  Function(name, signature)
  Import(name, signature)
  Label(name)

MirType
  I64
  U64
  I8
  U8
  Bool
  Void
  Ptr
  Array(count: int, elem: MirType)
  Struct(name: str)
```

注意：

- text MIR 打印 pointer operand 为 `ptr %x.addr`。
- memory access type 放在 `load/store/gep` 指令上，不放在 pointer type 上。
- validator 根据 operand type 判断是否是 pointer，并根据指令携带的访问类型检查结果和值类型。
- struct / array layout 是 MIR module 的显式合约，不能通过动态挂载 `program.structs` 传给 lowering。

## 14. Validator 第一版

第一版 validator 至少检查：

- 每个 function 至少有一个 block。
- block 名称唯一。
- 每个 block 有且只有一个 terminator。
- terminator 只出现在 block 末尾。
- value 使用前已定义。
- value 名称在 function 内唯一。
- `load T, ptr` 的地址 operand 必须是 `ptr`，result 必须是 `T`。
- `store T value, ptr addr` 的 value 类型必须是 `T`，addr 必须是 `ptr`。
- `gep SourceType, ptr base, indices...` 的 base 必须是 `ptr`，result 必须是 `ptr`，indices 必须匹配 `SourceType`。
- `ptrtoint ptr -> i64` 类型匹配。
- `add/sub/mul/div/mod` 两个 operand 类型一致，result 类型一致。
- `icmp.*` 两个 operand 类型一致，result 是 `bool`。
- `condbr` condition 是 `bool`。
- `ret` 类型匹配 function return type。
- `call` 参数和返回值匹配 callee signature。
- `@name` 必须能在 function/global/import symbol table 中找到。
- `label %name` 必须能在当前 function block table 中找到。

## 15. SSA 决策

第一版不直接做 SSA + phi/block params，而是使用“三地址临时值 + mutable local address”。

好处：

- 实现简单。
- 贴近当前 codegen 的 stack slot 模型。
- `if`、`while`、变量赋值不需要立即处理 phi。
- 后续如果要优化，可以再做 mem2reg / SSA 化。

代价：

- 数据流不如 SSA 纯净。
- 未来做优化前可能需要额外 pass。

保留未来升级方向：

```text
mutable local address MIR -> mem2reg -> SSA MIR
```

但这不是删除 NASM 的必要前置条件。

## 16. MIR 到 LowMIR/X64MIR

MIR 不直接等于 x64。后端分层：

```text
AST
  -> MIR                 # block / condbr / add / sub / load / store / gep
  -> LowMIR / X64MIR     # 显式寄存器、栈槽、真实跳转、调用序列
  -> machine code        # 字节、label、fixup、import thunk
  -> PE exe
```

MIR lowering 负责：

- 把 structured MIR 控制流降成 label + jmp/conditional jmp。
- 把 `add/sub/icmp/load/store/gep/ptrtoint/call` 降到当前简单寄存器策略。
- 根据 module 的显式 struct layout 把 `gep struct` 降成 offset address calculation。
- 把局部变量和临时值分配到 stack slot 或固定寄存器约定。
- 把 Epic call / runtime call / WinAPI call 降成 Windows x64 ABI 调用序列。
- 保持 label、data、import 引用的结构化信息，不降级成字符串。

LowMIR / X64MIR backend 负责：

- ASM-like pretty print。
- x64 指令编码。
- rel32 / RIP-relative / import thunk fixup。
- 输出 COFF-like object 或 PE exe。

## 17. 第一批实现范围

第一批只需要能覆盖最小 examples：

- `return 0`。
- 整数常量。
- `add/sub`。
- local `let`。
- `if`。
- `while`。
- 普通函数调用。
- 最小 WinAPI import call。

建议顺序：

1. `MirProgram` / `MirFunction` / `MirBlock` / `MirInst` / `MirTerminator`。
2. text MIR pretty printer。
3. validator。
4. 手写 MIR smoke test。
5. AST -> MIR for `m1_exit.ep`。
6. MIR -> LowMIR pretty print。
7. LowMIR -> machine emitter。

## 18. 非目标

第一版不做：

- text MIR parser。
- 完整 SSA。
- phi / block params。
- 优化 pass。
- 完整 LLVM IR 兼容。
- 跨平台 ABI。
- 通用汇编器。
- 通用寄存器分配器。
