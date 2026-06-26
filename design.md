# Epic v0 语言设计文档

## 〇、核心原则

**性能换便利。**

- struct 采用 64-bit 自然对齐，不做 compact 压缩
- array of struct 用指针数组（多一次跳转），换代码简洁
- array 总是在堆上分配
- `str` 总是深拷贝到堆上，包括字符串字面量在初始化时即深拷贝
- 所有堆分配序列统一用 `{data, len}` 16 字节 header
- 程序语法/语义可引入小的束缚以换实现便利，但仅当束缚确实降低实现复杂度时

---

## 一、{data, len} 统一布局

### 原则

Epic 中任意 **堆分配的定长序列** 均使用统一 16 字节 header，字段顺序与 Rust/Go 一致（`data` 在 offset 0，`len` 在 offset 8）：

| 偏移 | 字段 | 类型 | 含义 |
|------|------|------|------|
| 0 | `data` | 指针 | 指向元素数据的指针 |
| 8 | `len` | `i64` | 序列中元素个数 |

### 适用范围

| 类型名 | `data` 类型 | 产生方式 |
|--------|------------|---------|
| `str` | `&i8` | 字符串字面量（深拷贝后）、`str(bytes, len)`、`itoa(n)`、`listdir()` 返回的文件名 |
| `_arr_i64` | `&i64` | `new i64[n]` |
| `_arr_i8` | `&i8` | `new i8[n]` |
| `_arr_T`（struct） | `&&T` | `new Token[n]` |
| `_arr_str` | `&&str` | `listdir()` 返回的数组 |

`data` 指针类型取决于元素是否为 struct：
- 基本类型（`i64`/`i8`）：`&T`（单层指针）
- struct 类型：`&&T`（指针数组，每个元素再各自指向堆上的 struct）

`str` 和 `_arr_i8` 在二进制布局上完全一致（`{data: &i8, len: i64}`）。区别仅在类型系统的操作许可：`str` 不可下标赋值（不可变），`_arr_i8` 可。

### 实现策略

`Emitter` 新增方法 `_register_len_data_type(name, elem_ptr_type)`，`str` 和所有 `_arr_T` 均通过此入口注册。未来若加内建方法或改变字段名，只改一处。

---

## 二、`str` 类型

### 设计意图

`str` 是 Epic 内置的 **不可变字符串**。总是堆分配，不共享底层 buffer。

```
str = { data: &i8, len: i64 }
```

- `data`：指向堆上字节序列首地址的指针
- `len`：字节数（不含 null terminator，但 data 末尾保留 `\0` 以兼容 Win32 API）

### 字符串字面量语义

```epic
let s = "hello";
```

编译为运行时代码：从 `.data` 段读取字节，`HeapAlloc` 分配 header + data，memcpy 字节并补 `\0`，`s` 类型推断为 `&str`。

字符串字面量可在任意表达式位置出现，每次求值均深拷贝：

```epic
putstr("hello");          // 分配一次
if strcmp(s, "pat") {}    // 分配一次
while i < 100 {
    putstr("hello");      // 分配 100 次——应提到循环外
}
```

> 循环中重复分配是用户责任。编译器不设语法限制，以「性能换便利」原则让实现最简。

### 构造 str 的入口

| 入口 | 签名 | 说明 |
|------|------|------|
| `str(bytes, len)` | `str(bytes: &i8, len: i64) → &str` | 从裸字节深拷贝构造 |
| `itoa(n)` | `itoa(n: i64) → &str` | 整数→十进制字符串，堆分配返回 |
| 字符串字面量 | `"..."` | 表达式位置自动深拷贝，返回 `&str` |

### 与 C 字符串的关系

`data` 末尾保留 `\0`，以便 `lstrcmpA`、`lstrcpyA`、`CreateProcessA` 等 Win32 API 可直接使用 `str.data`。

### 不可变性

`str.data[i] = 'X'` 禁止。`str` 只读。需要原地修改字节用 `new i8[n]`。

### 删除的 builtin

| 删除项 | 原因 | 替代方案 |
|--------|------|---------|
| `strcpy(dst, src)` | str 深拷贝已由 `str(bytes, len)` 承担 | 写可变缓冲区用 fread/fwrite |
| `puti(n)` | `itoa(n) + putstr` 组合完整覆盖 | `putstr(itoa(n))` |

---

## 三、builtin 签名总览

### 字符串 builtin

| Builtin | 签名 | 说明 |
|---------|------|------|
| `putstr` | `putstr(s: &str) → void` | 输出到 stdout，读 `s.len` + `s.data` 调 WriteFile |
| `strlen` | `strlen(s: &str) → i64` | 返回 `s.len`（一条 mov 指令） |
| `strcmp` | `strcmp(a: &str, b: &str) → i64` | 提取 `a.data`/`b.data` 调 lstrcmpA |
| `str_new` | `str_new(bytes: &i8, len: i64) → &str` | 深拷贝构造 str |
| `itoa` | `itoa(n: i64) → &str` | 整数→十进制字符串（堆分配） |

### I/O builtin

| Builtin | 签名 | 说明 |
|---------|------|------|
| `fopen` | `fopen(path: &str, mode: i64) → i64` | 打开文件（提取 path.data），mode=0 读 mode=1 写 |
| `fread` | `fread(fd: i64, buf: &i8, len: i64) → i64` | 读入 buf，返回实际字节数 |
| `fwrite` | `fwrite(fd: i64, buf: &i8, len: i64) → i64` | 写出 len 字节，返回实际字节数 |
| `fclose` | `fclose(fd: i64) → void` | 关闭文件 |

### 系统 builtin

| Builtin | 签名 | 说明 |
|---------|------|------|
| `exit` | `exit(code: i64) → void` | 退出进程 |
| `putc` | `putc(c: i64) → void` | 输出单字符到 stdout |
| `system` | `system(cmd: &str) → i64` | 执行命令行（提取 cmd.data 传 CreateProcessA），返回 exit code |
| `listdir` | `listdir(pattern: &str, max: i64) → &_arr_str` | 列出文件（提取 pattern.data 传 FindFirstFileA），返回 str 数组 |

### 不提供的 builtin

| 项目 | 原因 |
|------|------|
| `free(ptr)` | v0 不管理内存生命周期，OS 退出时回收一切 |

---

## 四、词法与语法

### 新增关键字

`str` 加入词法表：`("STR", r'\bstr\b')`

### 类型语法

```epic
let s: &str = "hello";     // 显式标注
let s = "hello";           // 推断为 &str
fun echo(msg: &str) -> i64 {
    putstr(msg);
    return 0;
}
```

`str` 只以 `&str` 形式出现（指针类型）。Epic 不允许按值传 struct，`let s: str = ...` 报错。

---

## 五、典型用法示例

```epic
// 字符串字面量：自动深拷贝为 &str
let greeting = "Hello, Epic!";
putstr(greeting);

// 从文件读取为 str
let buf = new i8[4096];
let fd = fopen("data.txt", 0);
let n = fread(fd, buf.data, 4096);
fclose(fd);
let content = str_new(buf.data, n);
putstr(content);

// 整数转字符串
let s = itoa(42);
putstr(s);

// 比较字符串
if strcmp(greeting, "Hello, Epic!") == 0 {
    putstr("match!\n");
}

// 列出文件
let files = listdir("*.ep", 100);
let i = 0;
while i < files.len {
    putstr(files.data[i]);         // files.data[i] 是 &str
    putc(10);
    i = i + 1;
}
```

---

## 六、待迁移测试文件

| 文件 | 变更 |
|------|------|
| `m7_str.ep` | `puti(42)` → `putstr(itoa(42))` |
| `m10_str.ep` | `let s: i64 = "hello"` → `let s = "hello"` |
| `m11_file.ep` | `puti(...)` → `putstr(itoa(...))`；`fopen(path, mode)` 参数改为 `&str` |
| `m14_arr.ep` | `puti(...)` → `putstr(itoa(...))` |
| `m15_itoa.ep` | `itoa(buf.data, n)` → `let s = itoa(n); putstr(s)` |
| `m15_system.ep` | `system(cmd.data)` → `system(cmd)` |
| `m15_strlen.ep` | `let s: i64 = "hello"` → `let s = "hello"`；`puti(...)` → `putstr(itoa(...))` |
| `m16_listdir.ep` | `putstr(files.data[i].data)` → `putstr(files.data[i])`；`puti(...)` → `putstr(itoa(...))` |
| `runtests.ep` | `itoa` / `system` / `puti` 全部同步 |
