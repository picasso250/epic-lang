# Epic 语言工作日志

## 2026-06-25 项目启动 & 设计决议

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

### Bug 修复记录
- `default rel` 缺失：NASM 默认用绝对寻址导致 ACCESS_VIOLATION
- `_buf+r8-1` 超出 32-bit 位移：改成 `lea rax, [_buf-1]; mov [rax+r8], 10`
- `call GetStdHandle` 踩掉 r8：在 `_itoa_write` 里保存到 `[rbp-8]`
- 重复 `emit_fn_def`：删掉第一个残缺版本
