# Epic 语言工作日志

## 2026-06-25 项目启动 & 设计决议

### str 类型重构 (2026-06-26)
- `{len, data}` → `{data, len}`（data offset 0, len offset 8，从 Rust/Go）
- `str` 加入词法 (`STR` token) 和语法 (`parse_type`)
- 字符串字面量每次深拷贝（`_str_alloc`），返回 `&str`
- 类型推断：`let s = "..."` → `&str`
- 删 `puti`（替代：`putstr(itoa(n))`）
- 删 `strcpy`（替代：`str(bytes, len)` 深拷贝）
- 新增 `str(bytes, len)` builtin
- `itoa(n)` 改签名为 `itoa(n: i64) → &str`（堆分配）
- `system(cmd)`/`fopen(path)`/`listdir(pattern)` 改签名接收 `&str`
- `{len,data}` 统一入口：`_register_len_data_type()`
- `_call_prep` 修复：去 +8（适配 push rbp + sub rsp 后的真实对齐态）
- 所有 builtin Win32 调用改用 `_call_prep`/`_call_cleanup`
- `_itoa` 重写：本地标签 + 栈帧保存 volatile 状态，支持负数
- Bug 修：`push r14/r15` 后写 `[rbp-8]` 覆盖 saved `r14`
- Bug 修：`HeapAlloc` 踩 volatile `r10`/`r11` → ACCESS_VIOLATION
- 33/37 测试通过。剩余 4 crash：m10_str(strcmp)/m15_system/m16_listdir/runtests
  共同点：通过 `&str` 参数调 builtin，内部 syscall 路径待查

### 工具链
- NASM 3.01 (1.9 MB) → lld-link 22.1.8 (135.8 MB, 含 LLVM-C.dll) → .exe
- 工具存放于 `tools/` 目录
- Windows SDK kernel32.lib 位于 `C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\um\x64`
- 最小流水线已验证：nasm → lld-link → 1536 字节 exe，退出码 42

### 设计决议

| 层 | 决策 |
|----|------|
| 目标平台 | Windows x64，裸 `_start` |
| 语言名 | Epic，扩展名 `.ep`，编译器 `epicc.py` |
| 语法 | C-like 花括号，分号结尾，`//` 单行注释，`if` 必须带 `{}` |
| 类型 | 单一 `i64`，显式标注 |
| 特性 | 表达式 / 变量绑定 / 函数定义 / 分支 / 循环 (L0-L4) |
| 作用域 | 函数作用域 |
| 函数 | ≤4 参数，显式 `return` |
| 后端 | AST 直译 → x64 汇编，全栈变量，Windows x64 ABI |
| 内建函数 | `puti(i64)`, `putc(i64)`, `exit(i64)` — 直调 kernel32 |
| 字符串 | 编译器展开为一串 `putc` 或单次 `WriteConsoleA` |
| 架构 | 两阶段：Parser (词法+语法) → Emitter (语义+代码生成) |
| 错误处理 | 礼貌报错，遇错即停 |
| 函数解析 | 两 pass：pass1 收集签名，pass2 编译函数体（支持前向引用） |
| 运算符 | 完整 C 系优先级（7 级），`&&` `||` 短路求值，溢出不检测 |
| 调试 | llvm-objdump + printf 大法 |

### 里程碑

| M | 内容 | 状态 |
|:--|------|:--:|
| M1 | 最小流水线：exit(42) | ✅ 2026-06-25 |
| M2 | 表达式 | ✅ 2026-06-25 |
| M3 | 变量 | ✅ 2026-06-25 |
| M4 | 函数 | ✅ 2026-06-25 |
| M5 | 分支 | ✅ 2026-06-25 |
| M6 | 循环 | ✅ 2026-06-25 |
| M7 | 字符串 | ✅ 2026-06-25 |

### M8: i8 类型支持 (2026-06-25)
- 添加 `i8` 类型、`'X'` 字符字面量
- 栈上仍占 8 字节（对齐简化），自动 `movsx` 提升到 i64 运算
- 存储用 `al` / `cl` 等低字节，加载用 `movsx`

### M9: 静态数组 (2026-06-25)
- `let buf: i8[N]` 声明 → `.data` 段 `resb N`
- `buf[i]` 读：`lea + movsx`；写：`lea + mov [rcx], al`
- 仅支持全局数组（不传参），预扫描到 `.data` 段
- 无边界检查

### 工具
- `runtests.py`: 自动测试框架，扫描 `# EXIT` / `# STDOUT` 标注，13/13 通过 (2026-06-25)
- 注释语法改为 `#`，输出改为 `WriteFile` (可重定向捕获)

### M10: 字符串表达式 + builtin (2026-06-25)
- `"..."` 在表达式位置返回 `.data` 段地址（null-terminated）
- `putstr(ptr)`, `strcmp(a, b)`, `strcpy(dst, src)` builtin

### M11: 文件 I/O (2026-06-25)
- `fopen(path, mode)`, `fread(fd, buf, len)`, `fwrite(fd, buf, len)`, `fclose(fd)`
- 数组名作表达式返回 `.data` 地址

### PE linker `link.py` (2026-06-25)
- 自写 PE linker：COFF 解析 → PE 生成，替代 lld-link (68MB → 8KB)
- 支持 REL32 relocation（import + section-relative），thunk + IAT
- 基础功能通（8/13 测试），扩展 import（lstrlenA 等）待修
- 产出的 .exe 约 2KB（vs lld-link 的 2.5KB）

### Bug 修复记录
- `default rel` 缺失：NASM 默认用绝对寻址导致 ACCESS_VIOLATION
- `_buf+r8-1` 超出 32-bit 位移：改成 `lea rax, [_buf-1]; mov [rax+r8], 10`
- `call GetStdHandle` 踩掉 r8：在 `_itoa_write` 里保存到 `[rbp-8]`
- 重复 `emit_fn_def`：删掉第一个残缺版本

### linker bug 修复 (2026-06-26)
- **EntryPoint 偷懒**：`AddressOfEntryPoint` 写死 `.text` 开头。M4/M8 的函数排在 `_start` 前面时炸。
  修复：从 COFF symbol table 找 `_start` section/value，计算 `entry_rva`。
- **短名 import 漏掉**：COFF ≤8 字符名字不进 string table，直接塞 symbol record name 字段。
  旧代码用 `name_off is not None` 过滤 import，漏掉 `lstrlenA/lstrcmpA/lstrcpyA/ReadFile`。
  修复：`section==0 && aux==0` 即视为 import。
- 两刀下去 → 8/13 → 13/13 全绿

### M12: struct 类型 (2026-06-26)
- `struct Name { field: type; ... }` 顶层定义
- `let p: Point;` 无初始值声明（`=` 变可选）
- `p.x` 字段读 / `p.x = expr` 字段写
- C 自然对齐布局，预扫描动态计算帧大小
- 暂不支持：struct 传参/返回、struct 字面量、嵌套 struct、struct 赋值
- 测试 15/15 通过

### 语法清理 (2026-06-26)
- `fn` → `fun`
- `if/while (cond)` → `if/while cond`（去括号）
- `m8_i8_fn.ep` 用 `&&` 替代嵌套 `if`

### M13: 指针 + 堆分配 (2026-06-26)
- 指针类型 `&T`（`&i64`, `&Node`）
- 堆分配 `new Node` → `HeapAlloc`（HEAP_ZERO_MEMORY）
- 取地址 `&expr` → `lea rax, [addr]`
- 解引用 `*expr` → `mov rax, [rax]`（纯读值，非左值）
- 自动解引用：对 `&T` 变量做 `.field` 访问自动 `mov rax, [rbp+slot]` 加载指针
- 指针传参：`fun f(p: &Point) -> i64`，指针用 1 个寄存器
- struct 禁止按值传参/返回（通过指针传递）
- 暂不支持：多级指针、free、struct 字面量
- 测试 18/18 通过

### M14: 动态数组 (2026-06-26)
- `new i64[n]` / `new i8[n]` / `new Token[n]`
- `xs.len` + `xs.data[i]` 下标访问，struct 数组自动取指针
- struct 数组 eager 分配：逐个 `new Token`（r12 非 volatile 保环）
- 删除静态数组 `let buf: i8[4096]`，`m9_array.ep` / `m11_file.ep` 重写
- 类型推断：`let xs = new i64[3]`
- 测试 21/21 通过

### M15: 自举准备 builtins (2026-06-26)
- `itoa(buf, n) → i64`：整数→十进制字符串，返回长度
- `strlen(s) → i64`：字符串长度（lstrlenA 包装）
- `system(cmd) → i64`：CreateProcessA + WaitForSingleObject + GetExitCodeProcess
- 测试 24/24 通过
