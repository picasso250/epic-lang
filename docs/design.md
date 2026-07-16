# Epic 语言设计 (Epic Language Design)

本文档描述当前的 Epic 语言。早期版本说明（design-v0、design-v1、design-v2）保留在 git 历史及标签 `staged-bootstrap-archive-2026-06-30` 中，作为历史锚点。

## 方向 (Direction)

Epic 是一门面向 Windows x64 的小型 C-like 系统语言（systems language）。它的设计围绕：**全程序编译 (whole-program compilation)**、函数和具名类型边界上的显式类型、字符串/具名字段类型/动态数组的堆分配引用值，以及一个用 Epic 编写的自举编译器 (self-hosted compiler)。

本实现不保留向前兼容性。语言变化时，编译器源码随当前设计一起演进。

当前 v0 已使用统一的 nominal `type` 声明表达 product 与 named payload sum。未来的 unit sum、inline payload variant 和 variant namespace 方向见 [`unified-type-declarations.md`](unified-type-declarations.md)。

## 程序模型 (Program Model)

一个程序由一组顶层 `type`、`fun` 和 `extern` 声明组成。没有包（package）、可见性规则或按文件的命名空间。

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
| `i32`   | 有符号 32 位整数，当前实现使用 8 字节槽存储 |
| `u32`   | 无符号 32 位整数，当前实现使用 8 字节槽存储 |
| `i64`   | 有符号 64 位整数                        |
| `u64`   | 无符号 64 位整数                        |
| `str`   | 字节字符串/文本值；支持字面量、内容相等、切片和分配式拼接 |
| `Name`  | 用户声明的 product 或 named sum 引用 |
| `T[]`   | 堆分配的动态数组描述符 (dynamic array descriptor) |
| `void`  | unit 类型，表示唯一的“无信息”值；常用于函数返回和副作用表达式 |

`str`、用户具名类型和动态数组具有引用语义。赋值和参数传递复制引用，而非对象内容。没有按值复制 product、sum wrapper 或数组的语义。`void` 是 unit 类型，但不能作为参数、local 绑定或数组元素类型使用。

### 内置全局变量 (Built-in Globals)

| 名称   | 类型     | 含义                                                        |
|--------|----------|-------------------------------------------------------------|
| `argv` | `str[]`  | 命令行参数，`argv[0]` 是可执行文件名                   |

## 函数 (Functions)

函数定义使用显式的参数和返回类型：

```epic
fun add(a: i64, b: i64): i64 {
    ret a + b
}
```

Epic 调用遵循 Windows x64 ABI：前四个整数参数使用寄存器，更多参数使用 8 字节栈槽。非 `void` 函数必须在所有可达路径上显式 `ret expr`；`void` 函数可以使用 `ret` 或自然结束。

程序入口函数必须是不接收参数、返回 `void` 的 `main`：

```epic
fun main(): void {
}
```

自然结束时进程退出码为 `0`。需要其他退出状态时必须显式调用 `exit(code)`；入口函数本身不通过返回值表达进程状态。普通非 `void` 函数使用 `ret expr` 返回值。

### 用户方法 (User Methods)

Epic 支持一个很小的用户方法语法，作为 receiver-first 调用形式：

```epic
type Parser = {
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

- receiver 类型必须使用 `type Name = { ... }` 声明；第一版不支持 sum、primitive、`str` 或 `T[]` receiver。
- receiver 作为降低后函数的第一个参数；product type 本来就是 heap-backed reference，没有 Go 风格的值 receiver / 指针 receiver 区分。
- 不支持重载、继承、trait、virtual dispatch、method value、泛型方法或 fallback 到 `peek(p)`。
- product receiver 的 `p.peek(args...)` 只查找 `Parser__peek(p, args...)`。
- 普通函数名允许包含 `__`，以兼容 runtime/helper 命名；method declaration 生成的 `Type__method` 如果与已有函数符号重复，按普通重复定义报错。
- 内置容器点调用仍由语义层优先识别；用户方法不覆盖这些内置点调用。

从 `main` 末尾自然结束时以状态 `0` 退出。非零退出使用 `exit(code)`。

## 表达式与语句 (Expressions and Statements)

### 字面量 (Literals)

- 数字字面量支持十进制以及带 `0x`/`0X` 前缀的十六进制；十六进制数字大小写均可。它永远是 `i64`，不根据目标类型改成 `u64`/`u32`/`i32`/`u8`。
- 数字字面量必须落在 `i64` 正数 token 可表示范围内：`0..9223372036854775807`（十六进制最大为 `0x7fffffffffffffff`）。需要 `i64` 最小值请写 `0 - 9223372036854775807 - 1`。
- `u64`/`u32`/`u8` 的最大值或 wrap 值必须通过显式转换和运算构造，例如 `u64(0) - u64(1)`、`u32(0) - u32(1)`。
- `true` 和 `false` 是 `bool` 字面量。
- 字符串字面量产生 `str`。当前字符串语义按字节定义，不提供 Unicode 字符索引。支持的转义：`\n \r \t \\ \" \' \0`。仅支持 ASCII。
- 字符字面量产生 `u8`。支持的转义同字符串。

### Let 声明 (Let Declarations)

`let` 仅允许出现在函数体内，支持可选的类型注解，但 local variable 必须带初始化器。顶层只允许 `fun`、`extern` 和 `type` 声明；顶层/global `let` 已删除：

```epic
let b: u8 = 1
let ok = false
let xs = new u8[]
```

当右侧明显确定类型时，应省略注解；需要约束类型或消歧时保留注解。

不带初始化器的 `let x: T` 非法。Epic 不为 local variable 创建隐式零值；标量、容器、字符串和用户类型引用都必须由字面量、`new`、函数调用或其他表达式显式初始化。

`let` 绑定是 lexical block scoped：只在当前 `{ ... }` block 及其内部嵌套 block 中可见。内层 block 可以 shadow 外层同名绑定；离开 block 后恢复外层绑定。

`str`、`T[]`、用户结构体和 ADT wrapper 都是 heap-backed reference 类型。对 null reference 执行 `len`、索引、切片、`push`、`pop`、`extend` 或字段访问是运行时错误；编译器不会在使用点自动 materialize 空容器。

Postfix `?` 是 reference non-null check：`expr?` 对 `expr` 求值一次，并返回该 reference 是否非 null。`expr` 必须是 reference 类型；`bool` 和整数不允许使用 `?`。`?` 不引入 truthiness，`if` / 条件 `for` 仍然只接受 `bool`；例如 `if foo.ok {}` 读取 bool 字段，`if foo.child? {}` 检查 reference 字段是否非 null。`foo.child?` 会读取 `foo.child`，所以若 `foo` 本身为 null，仍然会触发 null deref trap；它不会 deref `child`。

### 运算符 (Operators)

算术运算符 `+`、`-`、`*`、`/`、`%` 带检查，溢出或除零时退出程序。

整数支持 `==`、`!=`、`<`、`<=`、`>`、`>=`。`str` 只支持按字节内容比较的 `==` / `!=`；字符串排序比较 `<`、`<=`、`>`、`>=` 不属于当前语言语义。

逻辑运算符 `&&`、`||`、`!` 操作 `bool`。整数没有隐式的布尔性；请写 `x != 0` 或 `bool(x)`。

位运算符 `~`、`&`、`|`、`^` 是低层操作，不经过检查。移位运算符 `<<`、`>>` 的左侧可以是任意整数类型，右侧 shift count 必须是 `i64`；结果类型与左侧相同。`>>` 对有符号整数是算术移位，对无符号整数是逻辑移位，右侧类型不影响 `shl` / `sar` / `shr` 的选择。Python 与 Epic sema 只检查 count 的类型为 `i64`；v0 为保持 bootstrap 实现简单，对字面量和非字面量一律在 MIR lowering 中生成 `0 <= count < bit_width` 的运行时范围检查。

`left + right` 在两个操作数都是 `str` 时执行字符串拼接，分配并返回新的 `str`，不修改任一输入。不会把整数、布尔值或数组隐式转换为字符串；需要显式写 `str(value)` 或使用 f-string。`u8[] + u8[]` 不支持，可变字节缓冲使用 `dst.extend(src)`。

### 整数转换 (Integer Conversions)

`i32(x)`、`u32(x)`、`u8(x)` 是显式截断转换，不做运行时越界检查。
转换先保留低位，再按目标类型规范化：`i32(x)` 保留低 32 位并符号扩展回当前 8 字节槽；
`u32(x)` 保留低 32 位并零扩展；`u8(x)` 保留低 8 位并零扩展。
例如 `u32(0) - u32(1)` 得到 `4294967295`，`i32(2147483647) + i32(1)` 得到 `-2147483648`。
显式整数转换不放宽数字字面量范围；`u64(18446744073709551615)`、`u32(4294967296)`、`i32(2147483648)` 都非法。

非字面量跨整数类型赋给 `i32/u32/u8` 必须写显式转换；显式转换表达的是“我接受截断”。
当前 Python reference compiler 的 `i32/u32/u8` 布局仍使用 8 字节槽。
算术、位运算、除余和移位会按结果类型规范化 `u8/u32/i32`；比较按左操作数类型选择 signed/unsigned 语义。

### 编译期文件嵌入 (Embed)

`embed "path"` 是类型为 `str` 的编译期表达式。路径必须是字符串字面量，并相对包含该表达式的源文件目录解析。文件必须存在；内容按原始字节映射为 Epic `str`，与普通字符串字面量一样进入可执行文件的 `.data`。 编译器自身用该机制嵌入标准 Epic runtime source 与 MIR helper bundle，因此生成的编译器不依赖工作目录中的 `runtime/`。

```epic
let runtime_source = embed "../runtime/file.ep"
```

### 复合赋值 (Compound Assignment)

支持：`+=`、`-=`、`*=`、`/=`、`%=`、`<<=`、`>>=`、`&=`、`|=`、`^=`。左侧表达式只求值一次。除 shift 外，复合整数运算要求左右类型完全相同；`<<=` / `>>=` 与普通 shift 一样要求右侧为 `i64`，因此 `u64_value >>= 8` 合法，而 `u64_value >>= u64(8)` 非法。`str += str` 不支持，需要显式写 `s = s + rhs`。

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

Block 是 statement 序列，不产生 value。裸表达式在 block 的任何位置都是 expression statement，其结果会被丢弃。当前语法没有分号；换行或右花括号结束 statement。


### 内置容器点调用 (Builtin Container Dot Calls)

Epic 支持一小组内置容器点调用：

```epic
xs.push(x)
let last = xs.pop()
dst.extend(src)
```

这些不是通用用户方法系统；不支持重载、继承、trait 或方法值。`len`、`str`、`bytes` 保持函数调用形式。parser 统一把 `expr.ID(args)` 解析为 DotCall，语义层再识别数组操作或用户结构体方法。

`push`、`pop`、`extend` 不是全局保留名。没有 receiver 的 `push(...)`、`pop(...)`、`extend(...)` 按普通用户函数或 extern 解析；只有 `xs.push(...)`、`xs.pop()`、`xs.extend(...)` 获得数组内建语义。

### 具名字段类型初始化 (Named-field Type Initialization)

`type Name = { ... }` 声明 heap-only reference type。local variable 必须显式初始化：

```epic
let p: Pos         # 编译错误！local variable 必须带初始化器
let p = new Pos    # 合法，分配对象；省略字段按默认存储值初始化
```

```epic
type Pos = {
    line: i64
    col: i64
}
let p = new Pos { line: 3, col: 9 }
let q = new Pos { line: 3 }     # 省略的标量字段默认为 0 / false
let z = new Pos {}              # 所有标量字段为默认值
```

`new Ctor` 是 `new Ctor {}` 的简写。`Ctor` 是用 `{ ... }` 声明的类型名称。初始化器允许只写部分字段。省略的标量字段默认为 `0` / `false`；省略的 reference 字段默认为 null，必须在使用前显式赋值或用 `field?` 检查。

字段按名称指定。顺序无关。未知字段或重复字段是编译错误。

### 数组字面量 (Array Literals)

```epic
let xs = new i64[] { 1, 2, 3 }
let bs = new u8[] { 65, 66, 67 }
```

分配一个动态数组，其逻辑长度等于元素个数。`new T[n]` 创建长度为 `n` 的零初始化数组，可立即索引 `0` 到 `n - 1`。

### ADT (代数数据类型, Algebraic Data Types)

Epic 的 ADT v1 是由已声明 product 组成的 named sum：

```epic
type LiteralExpr = {
    value: str
    line: i64
}

type BinaryExpr = {
    op: str
    left: Expr
    right: Expr
    line: i64
}

type Expr = LiteralExpr | BinaryExpr
```

规则：

- sum member 必须是使用 `{ ... }` 声明的类型。
- ADT 是封闭集合，定义后不能扩展。
- 不支持 primitive 直接作为 sum member。
- 不支持隐式 product -> sum 转换。
- 构造必须显式：`new Expr(new LiteralExpr { ... })`。
- `Expr` 是独立 heap-backed wrapper 类型，构造后的静态类型就是 `Expr`，不保留内部 variant 类型信息。
- 不开放 tag/kind/is API，ADT 只能通过 `match` 解包。
- `match` 必须覆盖全部 variant，或者提供 `_` 分支。
- payload 仍然是普通 product，可以作为函数参数类型。
- 不支持 sum extension。


ADT field access 只支持两类：

- 在 `match` case 中绑定具体 variant，然后访问该 variant 的普通字段。
- 访问所有 variants 都直接声明的同名、同类型 common field。字段在所有 variants
  中索引一致时，lowering 直接按公共布局读取；索引不一致时按 tag 分派。

Product type 只支持显式命名字段。匿名 embedded field、递归字段提升及其歧义规则均不属于语言 surface；组合关系写成 `meta: Meta`，访问时显式写 `node.meta.line`。

不存在 ADT partial field-exists sugar；`node.name?` 现在表示“访问 `node.name` 后检查该 reference 是否非 null”，因此 `name` 必须是合法字段访问。variant-specific 字段请用 `match`。

`match` 使用 product member 名称进行匹配：

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

当前两者运行时 header 相同，均为 `{data, len, cap}`，因此显式 `str(bytes)` / `bytes(str)` 是零拷贝 view。共享布局不代表源码类型相同，也不引入隐式赋值转换。`len(s)` 计数字节数，不包含尾部 NUL；当前不做 UTF-8 校验、不提供 Unicode 字符索引，也不承诺不可变。详见 [`str-u8-layout-contract.md`](str-u8-layout-contract.md)。

> 当前 Python reference compiler 依赖 `str` layout 与 `u8[]` 完全一致（{data, len, cap} 均为 24 字节），
> 使得 `str(bytes)` 和 `bytes(str)` 都是 identity cast，零分配零复制。
> 按字节读取或修改必须显式转成 byte view：`let b = bytes(s); b[i] = v`。

### 动态数组 (Dynamic Arrays)

`T[]` 是堆分配的引用值。

| 表达式                | 含义                                              |
|-----------------------|---------------------------------------------------|
| `new T[]`             | 空数组                                             |
| `new T[n]`            | 长度为 `n` 的零初始化数组                         |
| `a.push(x)`          | 追加并扩容                                        |
| `a.pop()`            | 删除并返回最后一个元素；空数组 runtime panic      |
| `dst.extend(src)`    | `dst` 和 `src` 必须是相同元素类型的 `T[]`；将 `src` 的当前元素追加到 `dst` |
| `a[i]`                | 带边界检查的元素访问（推荐）                      |
| `len(a)`              | 当前长度（推荐）                                  |

### 索引与切片 (Indexing and Slices)

索引带边界检查。`str` 支持只读字节下标 `s[i] -> u8`；字符串下标赋值与复合赋值会被拒绝。

切片语法（复制语义，半开区间 `[start, end)`）：

> 注意：`s[i]` 已删除；按字节读取字符串必须显式写 `bytes(s)[i]`。`s[start:end]`、`==` / `!=` 仍是语法能力，不是 public builtin。它们内部 lower 到 compiler-internal helper（`str_slice` / `str_eq`），但这些 helper 用户不可直接调用。
>
> 切片当前仅支持 str 和 u8[]；其他数组需要复制部分元素时使用 for + `.push(...)`。

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
| 字符串字节索引 | `bytes(s)[i]` | `s[i]` 和 `s.data[i]`（已从 public surface 删除） |
| 长度 | `len(x)` | `x.len`（已从 public surface 删除） |
| 内部容量 | 无 public API | `a.cap`（已从 public surface 删除） |
| 切片 | `s[start:end]` / `bytes[start:end]`（必须显式写出 start 和 end；仅支持 str 和 u8[]） | 无 public 替代（`str_slice` 已从 public surface 删除） |
| 从 `u8[]` 构造字符串 | `str(bytes)` | `str_new(bytes.data, bytes.len)`（已从 public surface 删除） |
| 字符串相等 | `s1 == s2` / `s1 != s2` | 按字节内容比较；`str_eq` 已从 public surface 删除 |

**三档分类**：

1. **推荐语法** — 普通代码应使用：`a[i]`、`bytes(s)[i]`、`len(a)`、`s[start:end]`、`bytes[start:end]`、`str(bytes)`、`new S`、`println(f"...")` 等。
2. **底层接口** — compiler / runtime 内部 helper 和 MIR helper 可使用布局；Epic 源码不可直接访问 `data/len/cap` layout 字段。
3. **历史写法** — 旧的 `a.data`、`s.data`、`x.len`、`a.cap` 字段访问已删除。

## 文件 IO（面向字节, byte-oriented）

```epic
read_file(path: str): u8[]
write_file(path: str, data: u8[]): i64
str(bytes: u8[]): str
bytes(s: str): u8[]
```

`read_file` 在失败时返回空的 `u8[]`。`str(u8[])` 是 zero-copy layout 重解释：把同 layout 的 `u8[]` 显式视为 `str`，不分配不复制。`bytes(str)` 同理。

`str(bytes)` 与 `bytes(str)` 是显式的零拷贝 view 转换。它们连接文本与可变字节缓冲边界，但不会消除 `str` 这个独立源码类型。

`str(x)` 只支持 `str`、整数、`bool`、`u8[]`。其中 `str(u8[])` 是 bytes view/cast；`str(i64)` / `str(u64)` / `str(u8)` / `str(bool)` 是显示转换。`str(product)`、`str(i64[])`、`str(str[])` 和 `str(bool[])` 不属于语言 surface。f-string 插值 `{expr}` 使用同一套 `str(expr)` 可转换性规则。


> ⚠ 修改 `bytes(str)` 返回的 `u8[]` 会修改原 `str` 的底层 buffer。如果多个 `str` 共享同一 buffer（例如相同内容的字面量），修改对所有 view 可见。语言不承诺 string literal 物理不可变。

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
| `cstr(s: str): u64`                    | 检查并返回可传给 C API 的 NUL 结尾地址值    |

以下 builtin 已从 public surface 删除。只有语法 lowering 必需的操作继续保留为 compiler-internal helper；普通库式字符串算法不保留内部 helper：

| 删除的 public builtin   | 替代方案                                    |
|------------------------|---------------------------------------------|
| `itoa(n)`              | `str(n)`                                    |
| `str_new(ptr, len)`    | `str(bytes)`                                |
| `str_get(s, i)`        | 已删除；使用 `bytes(s)[i]`                  |
| `str_slice(s, start, end)` | `s[start:end]`（语法）                   |
| `str_eq(s1, s2)`       | `s1 == s2`（语法）                          |
| `str_find`             | 自己写 `u8[]` 扫描；未来可提供 `s.find(...)` 方法 |
| `str_starts_with`      | 自己写 `u8[]` 扫描；未来可提供 `s.starts_with(...)` 方法 |
| `str_trim`             | 自己写 `u8[]` 扫描；未来可提供 `s.trim()` 方法 |
| `str_replace_char`     | 自己写 `u8[]` 扫描                          |
| `str_cat`              | `s1 + s2`（语法；分配新 `str`）             |
| `a.push(x)`             | 追加到动态数组                              |
| `a.pop()`              | 删除并返回最后一个元素；空数组 panic            |
| `dst.extend(src)`     | 追加相同元素类型数组的当前元素                                |

`cstr` 要求字符串内部数据指针非空、`len(s) >= 0`、`s[0:len(s)]` 不含 `0`，并且内部数据在 `len(s)` 位置以 `0` 结尾。检查失败时打印 `panic line N: invalid cstr` 并以状态 `1` 退出。

### Extern FFI

源码使用顶层声明描述 Windows x64 ABI 导入：

```epic
extern "kernel32.dll" fun Sleep(milliseconds: u32): void
extern "kernel32.dll" fun GetTickCount64(): u64
extern "kernel32.dll" fun lstrcmpA(left: u64, right: u64): i32
```

extern 参数只允许 `i32`、`u32`、`i64`、`u64`，返回类型还可为 `void`。`DWORD`/`UINT` 使用 `u32`，C `int`/`LONG` 使用 `i32`，64 位整数使用对应的 `i64/u64`。32 位返回值在调用边界立即符号扩展或零扩展。

Epic 不公开 `ptr` 类型。外部指针、C 字符串地址、Windows handle 和其他 pointer-sized opaque value 使用 `u64` bit pattern；`0` 写作 `u64(0)`，`INVALID_HANDLE_VALUE` 可写作 `u64(0) - u64(1)`。这些值不能解引用，也不使用 postfix `?`；空地址检查显式写 `value != u64(0)`。

`cstr(s)` 返回 `u64`，并要求字符串不含内嵌 NUL。extern 不提供隐式字符串转换。DLL 名必须是非空编译期字符串，不能包含 `$` 或 NUL；函数名是声明中的精确符号名。`os.*` 语法已删除。

源码 extern 通过自带 PE linker 的编码导入符号传递 DLL metadata，因此 Python 驱动下要求默认的 `--linker py`；`lld-link` 仍可用于没有源码 extern 的程序。普通退出继续使用 `exit(code)`。

## v0 发布边界 (Release Boundary)

`v0` 分支正在收敛首次公开版本；创建发布 tag 前不承诺源码、ABI 或工具行为兼容。不可移动的发布 tag 冻结该版本的用户可见语言与工具行为，而不冻结实现的内部形状。

以下内容属于稳定边界：

- 本文档描述的源码语法、类型规则、求值语义和控制流行为；
- public 类型、运算符、builtin、数组点方法、`main` 入口签名和 source `extern` 形式；
- 已文档化 CLI 选项的含义和默认行为；
- 程序可观察行为，包括标准输出/错误输出的语义、退出状态、panic/边界检查触发条件；
- 诊断的意图和必要信息。具体措辞、标点、行序和格式不承诺逐字节稳定。

以下内容不属于稳定边界，可以为 GC、优化、可维护性或新后端而演进：

- AST、typed AST、MIR、X64IR 的文本格式、顺序和内部节点/操作名称；
- compiler/runtime 私有 helper 名称、调用约定、对象布局和私有 ABI；
- 分配器、GC、对象生命周期、内存布局和其他 runtime 实现策略；
- 指令选择、寄存器/栈布局、COFF/PE 字节、符号顺序和 linker 内部实现；
- Python reference compiler 与 self-hosted compiler 的模块划分、文件结构和中间数据结构；
- 性能、内存占用和未显式承诺的优化结果。

发布版本的边界不要求内部 lockstep 永久不变。内部表示可以重构；后续分支也可以显式改变公开语义，但必须在同一提交中更新设计文档和意图级测试，不能依赖旧行为的隐式兼容。

## 自举模型 (Bootstrap Model)

```text
Python reference compiler -> Epic compiler -> Epic compiler
```

Python reference compiler 位于 `bootstrap/`，是当前语言和默认编译管线的 oracle。自托管的 Epic compiler 位于 `src/`，第一目标不是优化，而是在默认模式下逐阶段复现 Python reference compiler 的行为。

默认自举管线是 lockstep、未优化的：lexer、parser、MIR、X64IR、object 等阶段应优先支持 Python/Epic 对拍。只要默认管线仍在追平阶段，Python reference compiler 不承担优化主线，Epic compiler 也不在默认路径中引入优化。

未来优化只属于显式优化模式（例如 `-O` / `--release`）。优化后的中间结果允许和 Python oracle 不同，但必须保留优化前 dump，使默认 oracle 对拍仍然可用。

当前活跃验收入口包括 `python tests/run.py`、`python tests/examples/run.py` 和 `python bootstrap_fixed_point.py`。模块级测试负责 Python/self-hosted 各阶段对拍与 e2e 行为；examples 验证面向用户的正向程序；不动点构建连续使用生成的 Epic 编译器重新编译自身，并检查后续世代输出稳定。

分阶段的 v0/v1/v2 目录链是历史遗留。Git 标签保留了该链路；它不再是当前维护源码布局的一部分。
