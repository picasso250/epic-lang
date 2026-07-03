# Epic 语言设计 (Epic Language Design)

本文档描述当前的 Epic 语言。早期版本说明（design-v0、design-v1、design-v2）保留在 git 历史及标签 `staged-bootstrap-archive-2026-06-30` 中，作为历史锚点。

## 方向 (Direction)

Epic 是一门面向 Windows x64 的小型 C-like 系统语言（systems language）。它的设计围绕：**全程序编译 (whole-program compilation)**、函数和结构体边界上的显式类型、字符串/结构体/动态数组的堆分配引用值，以及一个用 Epic 编写的自举编译器 (self-hosted compiler)。

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
| `i32`   | 有符号 32 位整数，当前实现使用 8 字节槽存储 |
| `u32`   | 无符号 32 位整数，当前实现使用 8 字节槽存储 |
| `i64`   | 有符号 64 位整数                        |
| `u64`   | 无符号 64 位整数                        |
| `str`   | 字符串描述符（只读表面；下层 u8[] buffer 通过 bytes() 可变） |
| `Name`  | 堆分配的结构体引用               |
| `T[]`   | 堆分配的动态数组描述符 (dynamic array descriptor) |
| `map[str]T` | 堆分配的映射表（str 键）           |
| `void`  | 仅用于函数返回类型                      |

`str`、用户结构体、动态数组和映射表具有引用语义。赋值和参数传递复制引用，而非对象内容。没有按值复制结构体或数组的语义。

### 内置全局变量 (Built-in Globals)

| 名称   | 类型     | 含义                                                        |
|--------|----------|-------------------------------------------------------------|
| `argv` | `str[]`  | 命令行参数，`argv[0]` 是可执行文件名                   |

## 函数 (Functions)

函数定义使用显式的参数和返回类型：

```epic
fun add(a: i64, b: i64): i64 {
    return a + b
}
```

Epic 函数最多有 4 个参数。普通 Epic 调用最多有 4 个参数；编译器内置的 WinAPI 调用可按其白名单签名使用更多参数。`void` 函数可以使用 `return` 或自然结束。`void` 函数中不允许 `return expr`。

程序入口函数必须为：

```epic
fun main(): void {
}
```

从 `main` 末尾自然结束时以状态 `0` 退出。非零退出使用 `exit(code)`。

## 表达式与语句 (Expressions and Statements)

### 字面量 (Literals)

- 整数字面量在可表示时会适配目标类型。负数不会被适配为无符号类型。
- `i32` 字面量范围为 `-2147483648..2147483647`；`u32` 字面量范围为 `0..4294967295`。
- `true` 和 `false` 是 `bool` 字面量。
- 字符串字面量产生 `str` 值。支持的转义：`\n \r \t \\ \" \' \0`。仅支持 ASCII。
- 字符字面量产生 `u8`。支持的转义同字符串。

### Let 声明 (Let Declarations)

`let` 支持可选的类型注解：

```epic
let b: u8 = 1
let ok: bool
let xs: u8[]
```

当右侧明显确定类型时，应省略注解。

不带初始化器的 `let x: T` 创建零值。对标量类型为 `0` 或 `false`。对 `str`、数组、map，创建对应的空值。结构体是 heap-only reference type，不允许 `let x: Struct` 这种无初始化声明；必须显式写 `new Struct` 或 `new Struct { ... }`。

内建容器零值是语义上的空容器。实现可以把 `str`、`T[]`、`map[str]T` 的存储槽保持为 `0`，并在使用点由编译器懒初始化空 header；这个 `0` 不是语言级 `nil`，用户代码不能观察它。用户结构体引用不同：省略的结构体引用字段保持 null，访问其字段会触发 null deref。

### 运算符 (Operators)

算术运算符 `+`、`-`、`*`、`/`、`%` 带检查，溢出或除零时退出程序。

比较运算符 `==`、`!=`、`<`、`<=`、`>`、`>=` 操作 `bool`，产生逻辑结果。

逻辑运算符 `&&`、`||`、`!` 操作 `bool`。整数没有隐式的布尔性；请写 `x != 0` 或 `bool(x)`。

位运算符 `~`、`&`、`|`、`^` 和移位运算符 `<<`、`>>`、`>>>` 是低层操作，不经过检查。`>>` 对 `i64` 是算术移位，对无符号整数是逻辑移位。`>>>` 始终是逻辑移位。

### 整数转换 (Integer Conversions)

`i32(x)` 和 `u32(x)` 是显式、带检查的转换。`i32(x)` 要求值在
`-2147483648..2147483647` 内；`u32(x)` 要求值在 `0..4294967295` 内。
越界时程序以非零状态退出。非字面量跨整数类型赋给 `i32/u32` 必须写显式转换。

当前 Python reference compiler 的第一版 `i32/u32` 布局仍使用 8 字节槽；
`i32` 值保持 32 位有符号规范扩展后的 64 位值，`u32` 值保持 32 位无符号零扩展后的 64 位值。
算术、比较和移位沿用现有 64 位运算模型，结果不强制保持 32 位类型。

### 复合赋值 (Compound Assignment)

支持：`+=`、`-=`、`*=`、`/=`、`%=`、`<<=`、`>>=`、`>>>=`、`&=`、`|=`、`^=`。左侧表达式只求值一次。（`str += str` 已删除。使用 `u8[]` + `extend` + `str(bytes)` 显式拼接。）

### 控制流 (Control Flow)

- `if` / `else if` / `else`，条件为显式布尔表达式。
- `while`，条件为显式布尔表达式。
- `break` 和 `continue` 绑定到最近的 `while` 循环。
- `for i in start:end` — 半开递增区间，`start` 和 `end` 各求值一次，当 `i < end` 时执行。`continue` 跳到增量步骤。
- `return expr` / `return`。
- `exit(code)` — 立即以指定状态码结束进程；控制流分析视为终止路径。
- `panic "消息"` — 打印源码位置和消息，以非零状态退出。
- `assert cond` / `assert cond, "消息"` — 始终启用，失败时退出。

### 结构体初始化 (Struct Initialization)

结构体是 heap-only reference type。**局部变量不允许无初始化的结构体声明**：

```epic
let p: Pos         # 编译错误！必须用 new
let p = new Pos    # 合法，所有字段归零
```

```epic
struct Pos { line: i64; col: i64 }
let p = new Pos { line: 3, col: 9 }
let q = new Pos { line: 3 }     # 省略的字段被归零
let z = new Pos {}              # 所有字段为零
```

`new Ctor` 是 `new Ctor {}` 的简写。对于结构体，`Ctor` 是结构体名称。省略的字段被初始化为零值。

字段按名称指定。顺序无关。未知字段或重复字段是编译错误。

### 数组字面量 (Array Literals)

```epic
let xs = new i64[] { 1, 2, 3 }
let bs = new u8[] { 65, 66, 67 }
```

分配一个动态数组，其 `len` 和 `cap` 等于元素个数。`new T[n]` 分配一个空数组，容量至少为 `n` 个元素。

### ADT (代数数据类型, Algebraic Data Types) — 已移除

> **⚠ 历史特性 (Historical)**  
> ADT（代数数据类型）已从 Epic 自举核心移除。详见 [`self-host-core.md`](self-host-core.md)。
>
> 移除内容包括：`type` 定义、变体初始化 `new A.V { ... }`、ADT match payload binding。
> `match` 字面量分支保留。

### Match (模式匹配) — 仅保留字面量分支

> **⚠ ADT match 已移除**：ADT 变体分支已随 ADT 一同移除。匹配 payload binding 不再支持。详见 [`self-host-core.md`](self-host-core.md)。

`match` 是一个语句。支持字面量分支。

基本类型匹配：

```epic
match n {
    0:  { println("zero") }
    1:  { println("one") }
    else: { println("many") }
}
```

支持的检视类型：`i64`、`u64`、`u8`、`bool`、`str`。

规则：
- 每个分支在模式和主体之间使用冒号。
- `else` 可选，必须置于最后（如果存在）。
- 没有 fallthrough（向下穿透）。
- 不进行穷尽性检查 — 缺失的分支会产生运行时 panic。

### Map (映射表)

```epic
let ids = new map[str]i64
ids["main"] = 1
let id = ids["main"]
let ok = map_has(ids, "main")
```

键类型固定为 `str`。Python reference compiler 当前支持 `map[str]i64`、`map[str]bool`、`map[str]str`。不存在的键查找返回该值类型的零值；`map_has(m, key)` 区分是否存在；`map_del(m, key)` 删除键并返回是否真的删除了已有项。

## 字符串与数组 (Strings and Arrays)

### 字符串布局 (String Layout)

`str` 带长度信息且以 NUL 结尾，以便与 Win32 互操作。`len(s)` 计数字节数，不包含尾部 NUL。字符串布局字段不是 public surface。

> ⚠ `str` 表面只读，但当前实现**不阻止** `s[i] = v` 或 `s[i] += v` 通过 sema。这是有意为之的实现简化。
> 正确做法是：`let b = bytes(s); b[i] = v`。未来自举编译器版本会用更严格的类型检查挡住直接值写入。
> 当前 Python reference compiler 依赖 `str` layout 与 `u8[]` 完全一致（{data, len, cap} 均为 24 字节），
> 使得 `str(bytes)` 和 `bytes(str)` 都是 identity cast，零分配零复制。

### 动态数组 (Dynamic Arrays)

`T[]` 是堆分配的引用值。

| 表达式                | 含义                                              |
|-----------------------|---------------------------------------------------|
| `new T[]`             | 空数组，容量为 0                                  |
| `new T[n]`            | 空数组，容量至少为 `n`                            |
| `push(a, x)`          | 追加并扩容                                        |
| `extend(dst: u8[], src: u8[])`    | 将一个字节数组的所有字节追加到另一个字节数组；其他类型使用 `for + push`               |
| `a[i]`                | 带边界检查的元素访问（推荐）                      |
| `len(a)`              | 当前长度（推荐）                                  |
| `cap(a)`              | 当前容量（推荐）                                  |

### 索引与切片 (Indexing and Slices)

索引带边界检查。对字符串使用 `s[i]` 返回 `u8`。

切片语法（复制语义，半开区间 `[start, end)`）：

> 注意：`s[i]`、`s[start:end]`、`==` / `!=` 是语法能力，不是 public builtin。它们内部 lower 到 compiler-internal helper（`str_get` / `str_slice` / `str_eq`），但这些 helper 用户不可直接调用。
>
> 切片当前仅支持 str 和 u8[]；其他数组需要复制部分元素时使用 for + push。

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

### 长度与容量 (Length and Capacity，内置函数)

| 内置函数                 | 含义                     |
|-------------------------|--------------------------|
| `len(s: str): i64`      | 字符串字节长度           |
| `len(xs: T[]): i64`     | 数组元素个数             |
| `cap(xs: T[]): i64`     | 数组容量                 |

`cap(str)` 非法。

### 过时写法

| 场景 | 推荐写法 | 底层/过时写法 |
|------|----------|---------------|
| 数组索引 | `a[i]` | `a.data[i]`（已从 public surface 删除） |
| 字符串索引 | `s[i]` | `s.data[i]`（已从 public surface 删除） |
| 长度 | `len(x)` | `x.len`（已从 public surface 删除） |
| 容量 | `cap(a)` | `a.cap`（已从 public surface 删除） |
| 切片 | `s[start:end]` / `bytes[start:end]`（必须显式写出 start 和 end；仅支持 str 和 u8[]） | 无 public 替代（`str_slice` 已从 public surface 删除） |
| 从 `u8[]` 构造字符串 | `str(bytes)` | `str_new(bytes.data, bytes.len)`（已从 public surface 删除） |
| 字符串相等 | `s1 == s2` | 无 public 替代（`str_eq` 已从 public surface 删除） |

**三档分类**：

1. **推荐语法** — 普通代码应使用：`a[i]`、`s[i]`、`len(a)`、`cap(a)`、`s[start:end]`、`bytes[start:end]`、`str(bytes)`、`new S`、`println(f"...")` 等。
2. **底层接口** — compiler / runtime 内部 helper 和 MIR helper 可使用布局；Epic 源码不可直接访问 `data/len/cap` layout 字段。
3. **历史写法** — 旧的 `a.data`、`s.data`、`x.len`、`a.cap` 字段访问已删除。

## 文件 IO（面向字节, byte-oriented）

```epic
read_file(path: str): u8[]
write_file(path: str, data: u8[]): i64
str(bytes: u8[]): str
bytes(s: str): u8[]
```

`read_file` 在失败时返回空的 `u8[]`。`str(u8[])` 是 zero-copy layout 重解释：把同 layout 的 `u8[]` 视为 `str` view，不分配不复制。`bytes(str)` 同理。

`str(bytes)` + `bytes(str)` 是对偶 cast，MIR 不需要知道。

> ⚠ 修改 `bytes(str)` 返回的 `u8[]` 会修改原 `str` 的底层 buffer。如果多个 `str` 共享同一 buffer（例如相同内容的字面量），修改对所有 view 可见。语言不承诺 string literal 物理不可变。

常规源码加载方式：

```epic
let source = str(read_file(path))
```

源码换行是语言/工具链契约的一部分：Epic source 接受 LF (`\n`) 和 CRLF (`\r\n`)。lexer 将 CR (`\r`) 当作普通空白跳过，只在 LF (`\n`) 上产生一个 `NEWLINE` token 并递增行号。因此 CRLF 与 LF 的 token 流等价；单独的 CR 不作为换行格式支持。

## 其他内置函数 (Other Builtins)

| 内置函数                               | 含义                                        |
|----------------------------------------|---------------------------------------------|
| `print(x): void`                       | 写入 `x` 的字符串表示（无换行）              |
| `println(x): void`                     | 写入 `x` 的字符串表示并追加换行              |
| `cstr(s: str): i64`                    | 检查并返回可传给 C API 的 NUL 结尾字节指针  |
| `system(cmd: str): i64`                | 执行命令，返回退出码                        |

以下 builtin 已从 public surface 删除，作为 compiler-internal helper 保留：

| 删除的 public builtin   | 替代方案                                    |
|------------------------|---------------------------------------------|
| `itoa(n)`              | `str(n)`                                    |
| `str_new(ptr, len)`    | `str(bytes)`                                |
| `str_get(s, i)`        | `s[i]`（语法）                              |
| `str_slice(s, start, end)` | `s[start:end]`（语法）                   |
| `str_eq(s1, s2)`       | `s1 == s2`（语法）                          |
| `str_find`             | 自己写 `u8[]` 扫描                          |
| `str_starts_with`      | 自己写 `u8[]` 扫描                          |
| `str_trim`             | 自己写 `u8[]` 扫描                          |
| `str_replace_char`     | 自己写 `u8[]` 扫描                          |
| `str_cat`              | `u8[]` + `extend` + `str(bytes)`            |
| `push(a: T[], x: T): void`             | 追加到动态数组                              |
| `extend(dst: u8[], src: u8[]): void`     | 仅支持 u8[]；其他数组需要追加多个元素时使用 for + push                                |

`cstr` 要求字符串内部数据指针非空、`len(s) >= 0`、`s[0:len(s)]` 不含 `0`，并且内部数据在 `len(s)` 位置以 `0` 结尾。检查失败时打印 `panic line N: invalid cstr` 并以状态 `1` 退出。

`os.*` 名称保留给编译器暴露的系统调用。WinAPI 调用使用 `os.<dll>.<Function>(...)`，DLL 段目前只支持 `kernel32` 和 `user32`，函数必须在编译器白名单内。FFI 参数统一按 `i64` 传递；C 字符串参数必须显式写 `cstr(...)`：

```epic
os.kernel32.Sleep(u32(1000))
let n = os.kernel32.lstrlenA(cstr("abc"))
let r = os.user32.MessageBoxA(0, cstr("hi"), cstr("Epic"), u32(0))
```

普通代码应使用 `exit(code)` 退出。`os.kernel32.ExitProcess(code)` 仍在 WinAPI 白名单内，但不作为日常写法。

## 自举模型 (Bootstrap Model)

```text
Python reference compiler -> Epic compiler -> Epic compiler
```

Python reference compiler 位于 `bootstrap/`。自托管的 Epic compiler 位于 `src/`。不动点测试（`test_bootstrap_fixed_point.py`）验证反复由 Epic 构建的编译器在字节级别保持一致。

分阶段的 v0/v1/v2 目录链是历史遗留。Git 标签保留了该链路；它不再是当前维护源码布局的一部分。
