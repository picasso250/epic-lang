# Epic 语言设计 (Epic Language Design)

本文档描述当前的 Epic 语言。早期版本说明（design-v0、design-v1、design-v2）保留在 git 历史及标签 `staged-bootstrap-archive-2026-06-30` 中，作为历史锚点。

## 方向 (Direction)

Epic 是一门面向 Windows x64 的小型 C-like 系统语言（systems language）。它的设计围绕：**全程序编译 (whole-program compilation)**、函数和结构体边界上的显式类型、字符串/结构体/动态数组的堆分配引用值，以及一个用 Epic 编写的自举编译器 (self-hosted compiler)。

本实现不保留向前兼容性。语言变化时，编译器源码随当前设计一起演进。

## 程序模型 (Program Model)

一个程序由一组顶层 `struct`、`type`、`fun` 和 `extern` 声明组成。没有包（package）、可见性规则或按文件的命名空间。

当前驱动程序支持全程序源码合并：

```text
python epic.py --main main.ep main.ep lib.ep
```

所有输入文件中的顶层定义合并到一个全局命名空间。重名定义会被拒绝。当提供多个输入文件时，需要 `--main` 参数；只有所选主文件中的 `main` 函数被使用。

## 类型 (Types)

面向用户的类型：

| 类型    | 含义                                    |
|---------|-----------------------------------------|
| `bool`  | 逻辑值，`true` 或 `false`              |
| `u8`    | 无符号 8 位字节                         |
| `i16`   | 有符号 16 位整数                        |
| `u16`   | 无符号 16 位整数                        |
| `i32`   | 有符号 32 位整数                        |
| `u32`   | 无符号 32 位整数                        |
| `i64`   | 有符号 64 位整数                        |
| `u64`   | 无符号 64 位整数                        |
| `str`   | 字节字符串/文本值；支持字面量、内容相等、切片和分配式拼接 |
| `Name`  | 堆分配的结构体引用               |
| `T[]`   | 堆分配的动态数组描述符 (dynamic array descriptor) |
| `void`  | unit 类型，表示唯一的“无信息”值；常用于函数返回和副作用表达式 |

`str`、用户结构体和动态数组具有引用语义。赋值和参数传递复制引用，而非对象内容。没有按值复制结构体或数组的语义。`void` 是 unit 类型，但不能作为参数、local 绑定或数组元素类型使用。

### 内置全局变量 (Built-in Globals)

| 名称   | 类型     | 含义                                                        |
|--------|----------|-------------------------------------------------------------|
| `argv` | `str[]`  | 命令行参数，`argv[0]` 是可执行文件名                   |

## 函数 (Functions)

函数定义使用显式的参数和返回类型：

```epic
fun add(a: i64, b: i64): i64 {
    a + b
}
```

Epic 调用遵循 Windows x64 ABI：前四个整数参数使用寄存器，更多参数使用 8 字节栈槽。函数体是一个 block：非 `void` 函数可以用最后一个裸表达式作为返回值，也可以显式 `ret expr`；`void` 函数可以使用 `ret` 或自然结束，尾表达式如果存在必须是 `void`。

程序入口函数必须是不接收参数、返回 `void` 的 `main`：

```epic
fun main(): void {
}
```

自然结束时进程退出码为 `0`。需要其他退出状态时必须显式调用 `exit(code)`；入口函数本身不通过返回值表达进程状态。普通非 `void` 函数仍可使用 `ret expr` 或尾表达式返回值。

### 用户方法 (User Methods)

Epic 支持一个很小的用户方法语法，作为 receiver-first 调用形式：

```epic
struct Parser {
    pos: i64
}

fun (p: Parser) peek(): Token {
    ...
}

let tok = p.peek()
```

方法声明会被降低为普通全局函数符号：

```text
fun (p: Parser) peek(): Token  =>  Parser__peek(p: Parser): Token
p.peek()                       =>  Parser__peek(p)
```

规则：

- receiver 类型必须是用户定义的 `struct` 名称；第一版不支持 primitive、`str` 或 `T[]` receiver。
- receiver 作为降低后函数的第一个参数；Epic 的结构体本来就是 heap-backed reference，没有 Go 风格的值 receiver / 指针 receiver 区分。
- 不支持重载、继承、trait、virtual dispatch、method value、泛型方法或 fallback 到 `peek(p)`。
- struct receiver 的 `p.peek(args...)` 只查找 `Parser__peek(p, args...)`。
- 普通函数名允许包含 `__`，以兼容 runtime/helper 命名；method declaration 生成的 `Type__method` 如果与已有函数符号重复，按普通重复定义报错。
- 内置容器点调用仍由语义层优先识别；用户方法不覆盖这些内置点调用。

从 `main` 末尾自然结束时以状态 `0` 退出。非零退出使用 `exit(code)`。

## 表达式与语句 (Expressions and Statements)

### 字面量 (Literals)

- 数字字面量永远是 `i64`，不根据目标类型改成 `u64`/`u32`/`i32`/`u16`/`i16`/`u8`。
- 数字字面量必须落在 `i64` 正数 token 可表示范围内：`0..9223372036854775807`。需要 `i64` 最小值请写 `0 - 9223372036854775807 - 1`。
- `u64`/`u32`/`u16`/`u8` 的最大值或 wrap 值必须通过显式转换和运算构造，例如 `u64(0) - u64(1)`、`u32(0) - u32(1)`。
- `true` 和 `false` 是 `bool` 字面量。
- 字符串字面量产生 `str`。当前字符串语义按字节定义，不提供 Unicode 字符索引。支持的转义：`\n \r \t \\ \" \' \0`。仅支持 ASCII。
- 字符字面量产生 `u8`。支持的转义同字符串。

### Let 声明 (Let Declarations)

`let` 仅允许出现在函数体内，支持可选的类型注解，但 local variable 必须带初始化器。顶层只允许 `fun`、`extern`、`struct` 和 `type` 声明；顶层/global `let` 已删除：

```epic
let b: u8 = 1
let ok = false
let xs = new u8[]
```

当右侧明显确定类型时，应省略注解；需要约束类型或消歧时保留注解。

不带初始化器的 `let x: T` 非法。Epic 不为 local variable 创建隐式零值；标量、容器、字符串和结构体引用都必须由字面量、`new`、函数调用或其他表达式显式初始化。

`let` 绑定是 lexical block scoped：只在当前 `{ ... }` block 及其内部嵌套 block 中可见。内层 block 可以 shadow 外层同名绑定；离开 block 后恢复外层绑定。

`str`、`T[]`、用户结构体和 ADT wrapper 都是 heap-backed reference 类型。对 null reference 执行 `len`、索引、切片、`push`、`pop`、`extend` 或字段访问是运行时错误；编译器不会在使用点自动 materialize 空容器。

Postfix `?` 是 reference non-null check：`expr?` 对 `expr` 求值一次，并返回该 reference 是否非 null。`expr` 必须是 reference 类型；`bool` 和整数不允许使用 `?`。`?` 不引入 truthiness，`if` / 条件 `for` 仍然只接受 `bool`；例如 `if foo.ok {}` 读取 bool 字段，`if foo.child? {}` 检查 reference 字段是否非 null。`foo.child?` 会读取 `foo.child`，所以若 `foo` 本身为 null，仍然会触发 null deref trap；它不会 deref `child`。

### 运算符 (Operators)

算术运算符 `+`、`-`、`*`、`/`、`%` 带检查，溢出或除零时退出程序。

整数支持 `==`、`!=`、`<`、`<=`、`>`、`>=`。`str` 只支持按字节内容比较的 `==` / `!=`；字符串排序比较 `<`、`<=`、`>`、`>=` 不属于当前语言语义。

逻辑运算符 `&&`、`||`、`!` 操作 `bool`。整数没有隐式的布尔性；请写 `x != 0` 或 `bool(x)`。

位运算符 `~`、`&`、`|`、`^` 是低层操作，不经过检查。移位运算符 `<<`、`>>` 的左侧可以是任意整数类型，右侧 shift count 必须是 `i64`；结果类型与左侧相同。`>>` 对有符号整数是算术移位，对无符号整数是逻辑移位，右侧类型不影响 `shl` / `sar` / `shr` 的选择。字面量 count 由 sema 按左侧位宽静态检查，必须满足 `0 <= count < bit_width`，非法程序编译失败；非字面量 count 在运行时检查相同范围。需要对有符号值做逻辑右移时，先显式转换为同宽无符号类型。

`left + right` 在两个操作数都是 `str` 时执行字符串拼接，分配并返回新的 `str`，不修改任一输入。不会把整数、布尔值或数组隐式转换为字符串；需要显式写 `str(value)` 或使用 f-string。`u8[] + u8[]` 不支持，可变字节缓冲使用 `dst.extend(src)`。

### 整数转换 (Integer Conversions)

`i16(x)`、`u16(x)`、`i32(x)`、`u32(x)`、`u8(x)` 是显式截断转换，不做运行时越界检查。
转换先保留目标位宽的低位，再按目标类型符号扩展或零扩展到内部 64-bit value representation。
例如 `u16(0) - u16(1)` 得到 `65535`，`i16(32767) + i16(1)` 得到 `-32768`，
`u32(0) - u32(1)` 得到 `4294967295`。
数字 token 仍必须落在正 `i64` 范围内；范围内的显式转换允许截断，例如
`u32(4294967296)` 得到 `0`。

非字面量跨整数类型赋值必须写显式转换；显式转换表达的是“我接受截断”。local、参数和临时值仍使用
64-bit value slots；struct 字段按真实位宽自然布局。算术、位运算、除余和移位会按结果类型规范化
`u8/u16/i16/u32/i32`；比较按左操作数类型选择 signed/unsigned 语义。

### 复合赋值 (Compound Assignment)

支持：`+=`、`-=`、`*=`、`/=`、`%=`、`<<=`、`>>=`、`&=`、`|=`、`^=`。赋值目标与普通赋值相同：局部变量、struct 字段或数组下标。定位左值所需的对象、数组和下标表达式按源码顺序各求值一次；随后读取目标旧值，再求值右侧表达式，执行运算并写回同一目标。窄整数结果在写回前按目标类型截断并符号扩展或零扩展。除 shift 外，复合整数运算要求左右类型完全相同；`<<=` / `>>=` 与普通 shift 一样要求右侧为 `i64`，因此 `u64_value >>= 8` 合法，而 `u64_value >>= u64(8)` 非法。`str += str` 不支持，需要显式写 `s = s + rhs`。

### 控制流 (Control Flow)

- `if` / `else if` / `else`，条件为显式布尔表达式；reference null-check 请写 `expr?`。
- `for cond` — 条件循环；`cond` 必须是显式布尔表达式，reference null-check 请写 `expr?`。
- `for i: start:end` — 范围循环，半开递增区间 `[start, end)`。`start` 和 `end` 必须是 `i64`，进入循环前按从左到右顺序各求值一次；之后修改边界来源不会改变本次循环次数。
- 范围 cursor `i: i64` 只在循环 body 内可见。每轮正常结束后自动加一；`continue` 先跳到增量步骤，`break` 立即退出。`start >= end` 时执行零次。不支持隐式倒序、step 或省略起点。
- Epic 当前没有 iterable/元素遍历协议。数组索引循环显式写 `for i: 0:len(xs)`；`in` 和 `while` 都不是关键字，可作为普通标识符。
- `break` 和 `continue` 绑定到最近的 `for` 循环。
- `ret expr` / `ret`。
- `exit(code)` — 立即以指定状态码结束进程；控制流分析视为终止路径。
- `panic "消息"` — 打印源码位置和消息，以非零状态退出。

`assert` 不是关键字或内建语句；需要运行时检查时显式写
`if !cond { panic "消息" }`。`assert` 可作为普通标识符。

Block 的最后一个裸表达式是该 block 的 value；没有尾表达式的 block 类型是 `void`。当前语法没有分号；如果 `void` 函数或 block 末尾需要丢弃一个非 `void` 表达式，写一个后续 statement（例如裸 `ret`）来避免它成为 block value。


### 内置容器点调用 (Builtin Container Dot Calls)

Epic 支持一小组内置容器点调用：

```epic
xs.push(x)
let last = xs.pop()
dst.extend(src)
```

这些不是通用用户方法系统；不支持重载、继承、trait 或方法值。`len`、`str`、`bytes` 保持函数调用形式。parser 统一把 `expr.ID(args)` 解析为 DotCall，语义层再识别数组操作或用户结构体方法。

`push`、`pop`、`extend` 不是全局保留名。没有 receiver 的 `push(...)`、`pop(...)`、`extend(...)` 按普通用户函数或 extern 解析；只有 `xs.push(...)`、`xs.pop()`、`xs.extend(...)` 获得数组内建语义。

### 结构体初始化 (Struct Initialization)

结构体是 heap-only reference type。local variable 必须显式初始化：

```epic
let p: Pos         # 编译错误！local variable 必须带初始化器
let p = new Pos    # 合法，分配对象；省略字段按默认存储值初始化
```

```epic
struct Pos { line: i64; col: i64 }
let p = new Pos { line: 3, col: 9 }
let q = new Pos { line: 3 }     # 省略的标量字段默认为 0 / false
let z = new Pos {}              # 所有标量字段为默认值
```

`new Ctor` 是 `new Ctor {}` 的简写。对于结构体，`Ctor` 是结构体名称。初始化器允许只写部分字段。省略的标量字段默认为 `0` / `false`；省略的 reference 字段默认为 null，必须在使用前显式赋值或用 `field?` 检查。

字段按名称指定。顺序无关。未知字段或重复字段是编译错误。

结构体使用统一的 natural layout。字段按自身自然对齐放置，struct alignment 是所有字段 alignment 的最大值，
struct size 向该 alignment 取整。`u8/bool`、`i16/u16`、`i32/u32`、`i64/u64` 分别占
1、2、4、8 字节；reference 字段占 8 字节并按 8 字节对齐。当前不支持 packed struct。
结构体仍是 heap-backed reference type；统一布局不引入按值复制语义。

### 数组字面量 (Array Literals)

```epic
let xs = new i64[] { 1, 2, 3 }
let bs = new u8[] { 65, 66, 67 }
```

分配一个动态数组，其逻辑长度等于元素个数。`new T[n]` 创建长度为 `n` 的零初始化数组，可立即索引 `0` 到 `n - 1`。

### ADT (代数数据类型, Algebraic Data Types)

Epic 的 ADT v1 采用 **struct union** 模型：

```epic
struct LiteralExpr {
    value: str
    line: i64
}

struct BinaryExpr {
    op: str
    left: Expr
    right: Expr
    line: i64
}

type Expr = LiteralExpr | BinaryExpr
```

规则：

- union member 必须是用户定义的 `struct`。
- ADT 是封闭集合，定义后不能扩展。
- 不支持 primitive 直接作为 union member。
- 不支持隐式 struct -> ADT 转换。
- 构造必须显式：`new Expr(new LiteralExpr { ... })`。
- `Expr` 是独立 heap-backed wrapper 类型，构造后的静态类型就是 `Expr`，不保留内部 variant 类型信息。
- 不开放 tag/kind/is API，ADT 只能通过 `match` 解包。
- `match` 必须覆盖全部 variant，或者提供 `_` 分支；覆盖全部 variant 的 match 在控制流分析中视为穷尽分支。
- payload 仍然是普通 struct，可以作为函数参数类型。
- 不支持 union extension。


ADT field access 只支持两类：

- 在 `match` case 中绑定具体 variant，然后访问该 variant 的普通字段。
- 访问所有 variants 都直接声明的同名、同类型 common field。字段在所有 variants
  中索引一致时，lowering 直接按公共布局读取；索引不一致时按 tag 分派。

Struct 只支持显式命名字段。匿名 embedded field、递归字段提升及其歧义规则均不属于语言 surface；组合关系写成 `meta: Meta`，访问时显式写 `node.meta.line`。

不存在 ADT partial field-exists sugar；`node.name?` 现在表示“访问 `node.name` 后检查该 reference 是否非 null”，因此 `name` 必须是合法字段访问。variant-specific 字段请用 `match`。

`match` 使用 struct variant 名称进行匹配：

```epic
match e {
    LiteralExpr lit: {
        print(lit.value)
    }
    BinaryExpr b: {
        print(b.op)
    }
    _: {
    }
}
```

`match` 是一个语句。支持字面量分支。

基本类型匹配：

```epic
match n {
    0:  { println("zero") }
    1:  { println("one") }
    _: { println("many") }
}
```

支持的检视类型：`i64`、`u64`、`u8`、`bool`、`str`。

规则：
- 每个分支在模式和主体之间使用冒号。
- `_` 是唯一的默认分支拼法，可选且必须置于最后（如果存在）；`else:` 只属于 `if`，不属于 `match`。
- 没有 fallthrough（向下穿透）。
- 不进行穷尽性检查 — 缺失的分支会产生运行时 panic。

## 字符串与数组 (Strings and Arrays)

### `str` 与 `u8[]` 的语义边界

`str` 是保留的源码级字节字符串/文本类型；`u8[]` 是可变字节缓冲。字符串字面量产生 `str`，`==` / `!=` 做内容比较，`+` 分配并返回新的 `str`。`u8[]` 使用数组索引和 `push` / `pop` / `extend`，不获得隐式文本语义。

两者运行时布局分开：`str` 指向 inline `[len:i64][bytes...][NUL]` object，`u8[]` 使用可增长的 `{data, len, cap}` header。`bytes(str)` 与 `str(bytes)` 都深拷贝，不产生共享 mutable view。`len(s)` 计数字节数，不包含尾部 NUL；当前不做 UTF-8 校验或 Unicode 字符索引。详见 [`str-u8-layout-contract.md`](str-u8-layout-contract.md)。

> `str` 只读；`s[i]` 是 checked `u8` read，写入必须先显式复制到 `u8[]`。
> string literal 与 `embed` 的 inline object 位于 `.rdata`；动态字符串是单个 GC object。

### 动态数组 (Dynamic Arrays)

`T[]` 是堆分配的引用值。

| 表达式                | 含义                                              |
|-----------------------|---------------------------------------------------|
| `new T[]`             | 空数组                                             |
| `new T[n]`            | 长度为 `n` 的零初始化数组                         |
| `a.push(x)`          | 追加并扩容                                        |
| `a.pop()`            | 删除并返回最后一个元素；空数组 runtime panic      |
| `dst.extend(src)`    | 追加相同元素类型数组；`u8[]` 还可直接追加 `str` bytes，无中间转换 |
| `a[i]`                | 带边界检查的元素访问（推荐）                      |
| `len(a)`              | 当前长度（推荐）                                  |

### 索引与切片 (Indexing and Slices)

索引带边界检查。`s[i]` 对 `str` 做只读 byte access 并返回 `u8`；下标赋值与复合赋值被拒绝。

切片语法（复制语义，半开区间 `[start, end)`）：

> `s[i]`、`s[start:end]`、`==` / `!=` 是语法能力，不是 public builtin。它们内部 lower 到 compiler-internal helper，但这些 helper 用户不可直接调用。
>
> `str` 和所有数组类型都支持复制式切片。数组切片返回相同的 `T[]` 类型；
> `str` 继续使用独立的字符串复制路径并维护末尾 NUL。

```epic
let a = s[start:end]
let b = s[start:len(s)]
let c = s[0:end]
let d = s[0:len(s)]
```

- 切片必须显式写出 start 和 end；端点省略语法暂不支持。
- `start < 0` 或 `end < 0` 会退出
- `start > end` 或 `end > len` 会退出
- 成功的切片会分配并复制
- 结构体、ADT wrapper 和 `str` 数组复制的是 8-byte 引用，因此切片是浅复制

### 长度 (Length，内置函数)

| 内置函数                 | 含义                     |
|-------------------------|--------------------------|
| `len(s: str): i64`      | 字符串字节长度           |
| `len(xs: T[]): i64`     | 数组元素个数             |

数组的实际预留容量和增长策略属于 runtime 私有实现，不是源码级可观察行为。Epic 不提供 public `cap()`。

### 过时写法

| 场景 | 推荐写法 | 底层/过时写法 |
|------|----------|---------------|
| 数组索引 | `a[i]` | `a.data[i]`（已从 public surface 删除） |
| 字符串字节索引 | `s[i]`（只读，返回 `u8`） | `s.data[i]`（已从 public surface 删除） |
| 长度 | `len(x)` | `x.len`（已从 public surface 删除） |
| 内部容量 | 无 public API | `a.cap`（已从 public surface 删除） |
| 切片 | `s[start:end]` / `array[start:end]`（必须显式写出 start 和 end） | 无 public 替代（`str_slice` 已从 public surface 删除） |
| 从 `u8[]` 构造字符串 | `str(bytes)` | `str_new(bytes.data, bytes.len)`（已从 public surface 删除） |
| 字符串相等 | `s1 == s2` / `s1 != s2` | 按字节内容比较；`str_eq` 已从 public surface 删除 |

**三档分类**：

1. **推荐语法** — 普通代码应使用：`a[i]`、`s[i]`、`len(a)`、`s[start:end]`、`bytes[start:end]`、`str(bytes)`、`new S`、`println(f"...")` 等。
2. **底层接口** — compiler / runtime 内部 helper 和 MIR helper 可使用布局；Epic 源码不可直接访问 `data/len/cap` layout 字段。
3. **历史写法** — 旧的 `a.data`、`s.data`、`x.len`、`a.cap` 字段访问已删除。

## 文件 IO（面向字节, byte-oriented）

```epic
read_file(path: str): u8[]
write_file(path: str, data: u8[]): i64
str(bytes: u8[]): str
bytes(s: str): u8[]
```

`read_file` 在失败时返回空的 `u8[]`。当前实现写在 `runtime/file.ep`，路径通过 `cstr(str)`、buffer 通过 `cptr(u8[])` 传给同步 WinAPI；`write_file` 返回 WinAPI 报告的写入字节数，打开失败返回 `-1`。`str(u8[])` 与 `bytes(str)` 都深拷贝逻辑字节，转换后两侧独立。

这两个显式转换连接文本与可变字节缓冲边界，但不会消除 `str` 这个独立源码类型。

`str(x)` 只支持 `str`、整数、`bool`、`u8[]`。其中 `str(u8[])` 深拷贝为 read-only inline string object；`str(i64)` / `str(u64)` / `str(u8)` / `str(bool)` 是显式转换。`str(struct)`、`str(i64[])`、`str(str[])` 和 `str(bool[])` 不属于语言 surface。f-string 插值 `{expr}` 使用同一套 `str(expr)` 可转换性规则。


`u8[].extend(str)` 直接把 string bytes 复制进可变 buffer，不创建中间 `u8[]`。`str` 自身只读，不提供 `extend`。

常规源码加载方式：

```epic
let source = str(read_file(path))
```

源码换行是语言/工具链契约的一部分：Epic source 接受 LF (`\n`) 和 CRLF (`\r\n`)。lexer 将 CR (`\r`) 当作普通空白跳过，只在 LF (`\n`) 上产生一个 `NEWLINE` token 并递增行号。因此 CRLF 与 LF 的 token 流等价；单独的 CR 不作为换行格式支持。

## 其他内置函数 (Other Builtins)

| 内置函数                               | 含义                                        |
|----------------------------------------|---------------------------------------------|
| `print(x: str): void`                  | 写入字符串（无换行）；不做隐式 `str(x)`      |
| `println(x: str): void`                | 写入字符串并追加换行；不做隐式 `str(x)`      |
| `cptr(x): ptr`                         | 返回 bool、整数或 `ptr` 数组 backing data，或 FFI-safe struct payload 的 borrowed 地址；拒绝 `str` |
| `cstr(s: str): ptr`                    | 返回 `s + 8`，即首字节的同步 borrowed pointer；末尾有 NUL，允许内嵌 NUL |

以下 builtin 已从 public surface 删除。只有语法 lowering 必需的操作继续保留为 compiler-internal helper；普通库式字符串算法不保留内部 helper：

| 删除的 public builtin   | 替代方案                                    |
|------------------------|---------------------------------------------|
| `itoa(n)`              | `str(n)`                                    |
| `str_new(ptr, len)`    | `str(bytes)`                                |
| `str_get(s, i)`        | 已删除；使用 `s[i]`                         |
| `str_slice(s, start, end)` | `s[start:end]`（语法）                   |
| `str_eq(s1, s2)`       | `s1 == s2`（语法）                          |
| `str_find`             | 自己写 `u8[]` 扫描；未来可提供 `s.find(...)` 方法 |
| `str_starts_with`      | 自己写 `u8[]` 扫描；未来可提供 `s.starts_with(...)` 方法 |
| `str_trim`             | 自己写 `u8[]` 扫描；未来可提供 `s.trim()` 方法 |
| `str_replace_char`     | 自己写 `u8[]` 扫描                          |
| `str_cat`              | `s1 + s2`（语法；分配新 `str`）             |
| `a.push(x)`             | 追加到动态数组                              |
| `a.pop()`              | 删除并返回最后一个元素；空数组 panic            |
| `dst.extend(src)`     | 追加相同元素类型数组；`u8[]` 还可直接追加 `str`                |

`cptr` 接受元素为 `bool`/整数/`ptr` 的数组和非空 FFI-safe 用户 struct，并拒绝 `str`。`cptr(T[])` 读取 `{data,len,cap}` header 的 `data`；空数组自然返回 `ptr(0)`。数组 data 按元素的自然宽度连续存放：`bool/u8=1`、`i16/u16=2`、`i32/u32=4`、`i64/u64/ptr=8`。`cptr(struct)` 直接返回 non-moving heap payload 地址。`cptr` 不做 null、长度、容量或内容检查，不分配、不复制，也不转移所有权。外部代码必须按静态元素表示访问数组；Win32 `BOOL[]` 应使用 `i32[]`，一字节 `BOOLEAN[]` 才对应 `bool[]` 或 `u8[]`。

`cptr` 拒绝 `str[]`、struct/union 数组、嵌套数组等 managed-reference 元素数组。Epic 的这些数组保存连续的 8-byte managed reference，不能充当 WinAPI 所要求的 inline C struct 数组；需要显式指针数组时先构造 `ptr[]`。当前语言不提供 inline aggregate array。

返回地址只在 owner 仍可达且外部调用遵守同步 borrowed 契约时有效。任意数组的 backing data 都可能被 `push` / `extend` 等扩容操作替换，因此任何可能增长数组的操作后必须重新调用 `cptr(array)`。`new bool[n]`、`new integer[n]` 和 `new ptr[n]` 可作为同步 WinAPI output buffer；其中 `u16[]` 可承载显式构造并自行 NUL 结尾的 UTF-16 code units。`cstr(str)` 返回 inline object 中 offset 8 的首字节；末尾 NUL 由 string invariant 保证，内嵌 NUL 合法。外部代码通过该 pointer 修改字符串属于 FFI contract violation。

### Extern FFI

源码使用顶层声明描述 Windows x64 ABI 导入：

```epic
extern "kernel32.dll" fun Sleep(milliseconds: u32): void
extern "kernel32.dll" fun GetTickCount64(): u64
extern "kernel32.dll" fun lstrcmpA(left: ptr, right: ptr): i32
```

extern scalar 参数和返回值允许 `u8`、`i16`、`u16`、`i32`、`u32`、`i64`、`u64` 和 opaque `ptr`，返回类型还可为 `void`。`DWORD`/`UINT` 使用 `u32`，C `int`/`LONG` 使用 `i32`，64 位整数使用对应的 `i64/u64`，地址、handle 和可空 C pointer 使用 `ptr`；窄整数返回值在调用边界立即规范化到 Epic 的 64-bit value representation。

extern 参数还可使用非空的 FFI-safe 用户 struct。此时源码参数 `value: T` **固定表示同步 borrowed `T*`**，不是 C by-value `T`；lowering 直接传递 Epic heap-backed struct payload 的稳定地址。FFI-safe struct 的字段只允许整数 scalar 或 opaque `ptr`，不允许 `bool`、`str`、array、其他 struct 或 ADT。Win32 `BOOL` 应写作 `i32`，一字节 `BOOLEAN` 才写作 `u8`。nested C struct 第一版使用字段 flatten，C union/bitfield 使用相同大小的整数 raw storage 表达。

struct extern 返回值和 struct by-value 参数均不支持。只有在用户已经独立确认目标 ABI 把 1/2/4/8 字节 aggregate 放在普通整数 lane 时，才可把它手工声明成对应整数并用位运算解码；未使用高位必须由用户 mask。Epic 不公开 `sizeof`；需要 `cbSize`/`dwLength` 时使用目标 ABI 文档或独立布局工具取得常量。

extern struct pointer 和 `cptr(...)` 结果只在同步调用期间借用。外部函数不得在返回后保存该地址，不得释放或取得所有权，也不得交给外部线程或异步操作继续访问。

### Raw Function Address 与 WinAPI Callback

`ptr(function_name)` 返回源码定义的顶层普通函数的真实 `.text` 入口地址。lexical local 优先：如果当前作用域已有同名 local，`ptr(name)` 仍执行原有的 `i64` / `u64` / `ptr` 到 `ptr` 转换。`main`、extern、builtin、方法和未知名称不能取地址；函数名在 `ptr(...)` 之外也不是普通表达式。

函数地址擦除全部签名信息，可以赋给 local、比较、存入 `ptr` struct 字段或 `ptr[]`，也可以传给 extern。Epic 不支持 `p(args)` 形式的间接调用，不生成 callback thunk，也不检查参数数量、参数类型或返回类型是否匹配外部 API 的 callback ABI。该匹配责任完全属于调用者。

Windows x64 使用统一调用约定。address-taken 函数在真实入口把 `bool` / `u8` / `i16` / `u16` / `i32` / `u32` 参数规范化为 Epic 的 64-bit value representation，前四个寄存器参数和后续 8-byte 栈参数都遵循同一规则；`i64` / `u64` / `ptr` / managed reference 保留传入值。函数地址和直接调用共享同一入口，在进程生命周期内稳定。

第一版只支持在 Epic owner OS thread 上同步重入的 callback，例如 `WndProc`、消息循环 dispatch 和同步枚举。此类 callback 可以调用普通 Epic 函数和分配对象。thread-pool callback、异步 WinHTTP completion 等 foreign-thread callback 不受支持，runtime 不提供 thread guard；用户必须保证外部 API 不会从其他线程进入 Epic。

raw `ptr` 不拥有 callback context，也不会替 managed 对象保活。需要 context 时应由用户保持 owner 可达，并遵守同步 borrowed 契约。managed root handle、`ptr -> reference` 恢复、closure、callback 类型和动态间接调用均不属于当前语言。

```epic
extern "kernel32.dll" fun EnumSystemLocalesEx(callback: ptr, flags: u32, context: ptr, reserved: ptr): i32

fun visit(locale: ptr, flags: u32, context: ptr): i32 {
    ret i32(0)
}

fun main(): void {
    EnumSystemLocalesEx(ptr(visit), u32(0), ptr(0), ptr(0))
}
```

`ptr` 是公开的 64-bit opaque address scalar。它可用于变量、参数、返回值、struct 字段、`ptr[]` 和 extern ABI；只支持同类型的 `==` / `!=`，不支持直接算术、位运算、排序比较、解引用、字段访问、下标或 postfix `?`。地址运算必须显式经过整数：`ptr(u64(base) + offset)`。只允许 `ptr(i64/u64)` 与 `i64/u64(ptr)` 双向 bit-pattern 转换；空地址写作 `ptr(0)`，`INVALID_HANDLE_VALUE` 可写作 `ptr(u64(0) - u64(1))`。`ptr` 不拥有内存，也不延长外部资源或 managed allocation 的生命周期。

extern 不提供隐式字符串或 buffer 转换；字符串调用者必须显式使用 `cstr(...)`，array/struct 调用者使用 `cptr(...)`。DLL 名必须是非空编译期字符串，不能包含 `$` 或 NUL；函数名是声明中的精确符号名。`os.*` 语法已删除。

同名 extern 可以重复声明，但 DLL、参数数量、每个 canonical 参数类型和 canonical 返回类型必须完全一致；参数名不参与等价判断。等价声明在 sema 中折叠为一个导入，任一签名或 DLL 差异都会报告 conflicting extern declaration。

源码 extern 通过自带 PE linker 的编码导入符号传递 DLL metadata，因此 Python 驱动下要求默认的 `--linker py`；`lld-link` 仍可用于没有源码 extern 的程序。普通退出继续使用 `exit(code)`。

## 编译期文件嵌入 (Compile-time Embed)

`embed "path"` 是类型为 `str` 的编译期表达式。路径必须是字符串字面量，并相对包含该表达式的 Epic 源文件目录解析；当前工作目录不参与语义。文件不存在时编译失败。文件内容按原始字节映射到 Epic 的 byte-oriented `str`，允许 NUL 和非 UTF-8 字节，并像普通字符串 literal 一样以 inline object 进入可执行文件 `.rdata`。

```epic
let source = embed "../runtime/file.ep"
let raw = bytes(embed "asset.bin")
```

`src/runtime_bundle.ep` 是编译器内置 runtime 资源的唯一清单。标准 runtime Epic source 和 MIR bundle 都由该文件嵌入，因此收敛后的 `epic.exe` 不需要磁盘上的 `runtime/` 才能编译普通程序。

## 演进与版本标签 (Evolution and Tags)

当前 `dev` 分支不承诺源码、MIR、ABI 或工具行为的向前兼容。语言仍处于主动设计阶段；当更简单、
更一致的模型需要破坏旧行为时，可以直接替换旧设计，不保留兼容分支或迁移层。

每次破坏性变更必须在同一提交中：

- 更新本文档及相关实现文档；
- 更新正向、负向或意图级测试；
- 删除旧语义，而不是同时维护两套规则。

Git 标签是可复现的历史里程碑，不是当前分支的兼容承诺。`v0` 是维护 bootstrap seed 与 Python stage-0 的分支；`v1` 标签记录完成自举与自动 GC 的里程碑。内部与公开设计都可继续演进。

## 自举模型 (Bootstrap Model)

```text
v0 branch epic-v0.exe -> current Epic compiler -> current Epic compiler
```

当前活跃编译器只位于 `src/`。`v0` 分支维护 Python stage-0 与可复现 seed，只覆盖构建当前 `dev` 所需的最小源码语义，不承诺当前公开 ABI；`build_epic_v0.py` 可在 detached worktree 中重建并校验 seed。当前 `dev` 不维护 Python oracle 或阶段 lockstep。

当前活跃验收入口包括 `python tests/run.py`、`python tests/examples/run.py` 和 `python test_bootstrap_fixed_point.py`。模块测试覆盖各阶段的意图与 canonical fixture，examples 和 e2e 约束公开行为，不动点测试连续使用生成的 Epic 编译器重新编译自身并检查输出稳定。

分阶段的 v0/v1/v2 目录链是历史遗留；它不再是当前维护源码布局的一部分。
