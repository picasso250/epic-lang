# Epic 语言设计 (Epic Language Design)

本文档描述当前的 Epic 语言。早期版本说明（design-v0、design-v1、design-v2）保留在 git 历史及标签 `staged-bootstrap-archive-2026-06-30` 中，作为历史锚点。

## 方向 (Direction)

Epic 是一门面向 Windows x64 的小型 C-like 系统语言（systems language）。它的设计围绕：**全程序编译 (whole-program compilation)**、函数和结构体边界上的显式类型、字符串/结构体/动态数组/ADT 的堆分配引用值，以及一个用 Epic 编写的自举编译器 (self-hosted compiler)。

本实现不保留向前兼容性。语言变化时，编译器源码随当前设计一起演进。

## 程序模型 (Program Model)

一个程序由一组顶层 struct、type 和 function 定义组成。没有导入（import）、包（package）、可见性规则或按文件的命名空间。

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
| `i64`   | 有符号 64 位整数                        |
| `u64`   | 无符号 64 位整数                        |
| `str`   | 不可变字节字符串描述符 (immutable byte string descriptor) |
| `Name`  | 堆分配的结构体或 ADT 引用               |
| `T[]`   | 堆分配的动态数组描述符 (dynamic array descriptor) |
| `map[str]T` | 堆分配的映射表（str 键）           |
| `void`  | 仅用于函数返回类型                      |

`str`、用户结构体、ADT、动态数组和映射表具有引用语义。赋值和参数传递复制引用，而非对象内容。没有按值复制结构体或数组的语义。

### 内置全局变量 (Built-in Globals)

| 名称   | 类型     | 含义                                                        |
|--------|----------|-------------------------------------------------------------|
| `argv` | `str[]`  | 命令行参数，`argv.data[0]` 是可执行文件名                   |

## 函数 (Functions)

函数定义使用显式的参数和返回类型：

```epic
fun add(a: i64, b: i64): i64 {
    return a + b
}
```

函数最多有 4 个参数。调用最多有 4 个参数。`void` 函数可以使用 `return` 或自然结束。`void` 函数中不允许 `return expr`。

程序入口函数必须为：

```epic
fun main(): void {
}
```

从 `main` 末尾自然结束时以状态 `0` 退出。非零退出需显式调用 `os.ExitProcess(code)`。

## 表达式与语句 (Expressions and Statements)

### 字面量 (Literals)

- 整数字面量在可表示时会适配目标类型。负数不会被适配为无符号类型。
- `true` 和 `false` 是 `bool` 字面量。
- 字符串字面量产生 `str` 值。支持的转义：`\n \r \t \\ \" \' \0`。仅支持 ASCII。
- 字符字面量产生 `u8`。支持的转义同字符串。

### Let 声明 (Let Declarations)

`let` 支持可选的类型注解：

```epic
let b: u8 = 1
let ok: bool
let token: Token
```

当右侧明显确定类型时，应省略注解。

不带初始化器的 `let x: T` 创建零值。对标量类型为零或 `false`。对 `str`、数组、结构体和 ADT，变量持有一个非空的描述符，其字段被归零；当 `.len` 为 `0` 时，`.data` 可能为 `0`。

### 运算符 (Operators)

算术运算符 `+`、`-`、`*`、`/`、`%` 带检查，溢出或除零时退出程序。

比较运算符 `==`、`!=`、`<`、`<=`、`>`、`>=` 操作 `bool`，产生逻辑结果。

逻辑运算符 `&&`、`||`、`!` 操作 `bool`。整数没有隐式的布尔性；请写 `x != 0` 或 `bool(x)`。

位运算符 `~`、`&`、`|`、`^` 和移位运算符 `<<`、`>>`、`>>>` 是低层操作，不经过检查。`>>` 对 `i64` 是算术移位，对无符号整数是逻辑移位。`>>>` 始终是逻辑移位。

### 复合赋值 (Compound Assignment)

支持：`+=`、`-=`、`*=`、`/=`、`%=`、`<<=`、`>>=`、`>>>=`、`&=`、`|=`、`^=`。左侧表达式只求值一次。`str += str` 执行字符串拼接。

### 控制流 (Control Flow)

- `if` / `else if` / `else`，条件为显式布尔表达式。
- `while`，条件为显式布尔表达式。
- `break` 和 `continue` 绑定到最近的 `while` 循环。
- `for i in start:end` — 半开递增区间，`start` 和 `end` 各求值一次，当 `i < end` 时执行。`continue` 跳到增量步骤。
- `return expr` / `return`。
- `panic "消息"` — 打印源码位置和消息，以非零状态退出。
- `assert cond` / `assert cond, "消息"` — 始终启用，失败时退出。

### 结构体初始化 (Struct Initialization)

```epic
struct Pos { line: i64; col: i64 }
let p = new Pos { line: 3, col: 9 }
let q = new Pos { line: 3 }     # 省略的字段被归零
let z = new Pos {}              # 所有字段为零
```

`new Ctor` 是 `new Ctor {}` 的简写。对于结构体，`Ctor` 是结构体名称。省略的字段被初始化为零值。

```epic
let b = new Box
let b2 = new Box {}
```

字段按名称指定。顺序无关。未知字段或重复字段是编译错误。

### 数组字面量 (Array Literals)

```epic
let xs = new i64[] { 1, 2, 3 }
let bs = new u8[] { 65, 66, 67 }
```

分配一个动态数组，其 `len` 和 `cap` 等于元素个数。`new T[n]` 分配一个空数组，容量至少为 `n` 个元素。

### ADT (代数数据类型, Algebraic Data Types)

```epic
type Expr {
    Empty
    IntLit { value: i64 }
    Binary { op: str; left: Expr; right: Expr }
}
```

ADT 是引用类型。零值是第一个变体（variant），有效载荷归零。变体初始化使用具名花括号语法：

```epic
let e = new Expr.IntLit { value: 123 }
let empty: Expr
```

构造器简写同样适用于 ADT 变体：

```epic
let e = new Expr.Empty              # new Expr.Empty {} 的简写
let e2 = new Expr.Empty {}
```

`new AdtName` 不是 ADT 构造器；ADT 构造必须指定变体名称。

### Match (模式匹配)

`match` 是一个语句。支持字面量分支和 ADT 变体分支。

基本类型匹配：

```epic
match n {
    0:  { putstr("zero") }
    1:  { putstr("one") }
    else: { putstr("many") }
}
```

支持的检视类型：`i64`、`u64`、`u8`、`bool`、`str`。

ADT 匹配：

```epic
match e {
    Expr.IntLit { value: n }: { puti(n) }
    Expr.Binary { op, left, right }: { putstr(op) }
    else: { panic "unknown expr" }
}
```

规则：
- 每个分支在模式和主体之间使用冒号。
- `else` 可选，必须置于最后（如果存在）。
- 没有 fallthrough（向下穿透）。
- ADT 有效载荷模式按名称绑定字段（`{ value: n }` 或 `{ value }`）。
- 未知或重复的有效载荷绑定是编译错误。
- 不进行穷尽性检查 — 缺失的分支会产生运行时 panic。

### Map (映射表)

```epic
let ids = new map[str]i64
ids["main"] = 1
let id = ids["main"]
let ok = map_has(ids, "main")
```

键类型固定为 `str`。不存在的键查找返回该值类型的零值。

## 字符串与数组 (Strings and Arrays)

### 字符串布局 (String Layout)

`str` 带长度信息且以 NUL 结尾，以便与 Win32 互操作。`s.len` 计数字节数，不包含尾部 NUL。`s.data` 和 `s.len` 是底层字段；新代码应使用 `len()` 和切片语法。

### 动态数组 (Dynamic Arrays)

`T[]` 是堆分配的引用值。

| 表达式                | 含义                                              |
|-----------------------|---------------------------------------------------|
| `new T[]`             | 空数组，默认容量                                  |
| `new T[n]`            | 空数组，容量至少为 `n`                            |
| `push(a, x)`          | 追加并扩容                                        |
| `extend(dst, src)`    | 将一个数组的所有元素追加到另一个数组               |
| `a[i]`                | 带边界检查的元素访问（推荐）                      |
| `len(a)`              | 当前长度（推荐）                                  |
| `cap(a)`              | 当前容量（推荐）                                  |
| `a.data[i]`           | 底层 unchecked 元素访问，普通代码不推荐            |

### 索引与切片 (Indexing and Slices)

索引带边界检查。对字符串使用 `s[i]` 返回 `u8`。

切片语法（复制语义，半开区间 `[start, end)`）：

```epic
let a = s[start:end]
let b = s[start:]
let c = s[:end]
let d = s[:]
```

- 省略 `start` = `0`，省略 `end` = `.len`
- `start < 0` 或 `end < 0` 会退出
- `start > end` 或 `end > len` 会退出
- 成功的切片会分配并复制

### 长度与容量 (Length and Capacity，内置函数)

| 内置函数                 | 含义                     |
|-------------------------|--------------------------|
| `len(s: str): i64`      | 字符串字节长度           |
| `len(xs: T[]): i64`     | 数组元素个数             |
| `cap(xs: T[]): i64`     | 数组容量                 |

`cap(str)` 非法。

### 底层接口与过时写法

Epic 保留一批底层接口，主要服务于 compiler、runtime、linker 和 bootstrap 代码。普通应用代码不应优先使用这些接口。

| 场景 | 推荐写法 | 底层/过时写法 |
|------|----------|---------------|
| 数组索引 | `a[i]` | `a.data[i]` |
| 字符串索引 | `s[i]` | `s.data[i]` |
| 长度 | `len(x)` | `x.len` |
| 容量 | `cap(a)` | `a.cap` |
| 切片 | `s[start:end]` / `a[start:end]` | `str_slice(s, start, end)` |
| 从 `u8[]` 构造字符串 | `str(bytes)` | `str_new(bytes.data, bytes.len)` |

> `a.data[i]` 是底层 unchecked 访问，仅适合明确需要绕过边界检查或处理 runtime layout 的代码。新代码默认使用 `a[i]`。
>
> `s.data`、`s.len`、`a.data`、`a.len`、`a.cap` 暂时仍是可访问字段，但属于 layout 暴露，不应作为普通代码风格。
>
> `str_new(ptr, len)` 接受任意 `ptr`（指针）+ `len`，不能完全被 `str(u8[])` 替代；它在底层代码中保留为合法 escape hatch。

**三档分类**：

1. **推荐语法** — 普通代码应使用：`a[i]`、`s[i]`、`len(a)`、`cap(a)`、`s[start:end]`、`a[start:end]`、`str(bytes)`、`new S`、`println(f"...")` 等。
2. **底层接口** — compiler / runtime / linker / bootstrap 可用，但也不推荐使用，普通代码绝不推荐：`a.data[i]`、`s.data`、`s.len`、`a.len`、`a.cap`、`str_new(ptr, len)`、`str_slice(s, start, end)`。
3. **历史写法** — 仍可解析/运行，但新代码不应写；未来可删除。（当前尚无明确归入此类的语法。）

## 文件 IO（面向字节, byte-oriented）

```epic
read_file(path: str): u8[]
write_file(path: str, data: u8[]): i64
str(bytes: u8[]): str
bytes(s: str): u8[]
```

`read_file` 在失败时返回空的 `u8[]`。`str(u8[])` 复制整个数组长度并追加尾部 NUL。常规源码加载方式：

```epic
let source = str(read_file(path))
```

## 其他内置函数 (Other Builtins)

| 内置函数                               | 含义                                        |
|----------------------------------------|---------------------------------------------|
| `putc(c: i64): void`                   | 写入一个字节                                |
| `putstr(s: str): void`                 | 写入字符串字节                              |
| `itoa(n: i64): str`                    | 整数转堆分配字符串                          |
| `str_new(bytes, len): str`             | 从底层缓冲区复制 `len` 个字节创建字符串     |
| `str_starts_with(s, prefix): i64`      | 若 `s` 以 `prefix` 开头则为真               |
| `str_find(s, needle): i64`             | 第一个字节的索引，或 `-1`                   |
| `str_trim(s): str`                     | 去除前导/尾随 ASCII 空白字符                |
| `system(cmd: str): i64`                | 执行命令，返回退出码                        |
| `push(a: T[], x: T): void`             | 追加到动态数组                              |
| `extend(dst: T[], src: T[]): void`     | 追加所有元素                                |

`os.*` 名称保留给编译器暴露的系统/运行时调用。`os.ExitProcess(code)`、`os.WriteFile` 等被特别识别。

## 自举模型 (Bootstrap Model)

```text
Python reference compiler -> Epic compiler -> Epic compiler
```

Python reference compiler 位于 `bootstrap/`。自托管的 Epic compiler 位于 `src/`。不动点测试（`test_bootstrap_fixed_point.py`）验证反复由 Epic 构建的编译器在字节级别保持一致。

分阶段的 v0/v1/v2 目录链是历史遗留。Git 标签保留了该链路；它不再是当前维护源码布局的一部分。
