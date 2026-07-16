# Unified Type Declarations

本文档记录 Epic 在 v0 之后的类型声明方向。它是已接受的未来设计方向，不描述当前语言语法，也不要求 v0 实现兼容层。

## 决策

Epic 未来只使用 `type` 声明 nominal type。Product、unit sum 和 payload sum 是同一套类型构造的不同形态：

```epic
type Point = {
    x: i64
    y: i64
}

type TokenKind =
    EOF
  | ID
  | FUN

type Expr =
    Lit {
        value: i64
    }
  | Add {
        left: Expr
        right: Expr
    }
```

对应关系：

| 声明形态 | 类型结构 | 当前近似概念 |
|---|---|---|
| `type A = { ... }` | 单一 product | `struct A { ... }` |
| `type A = X \| Y` | unit sum | enum |
| `type A = X { ... } \| Y { ... }` | payload sum | ADT |

`enum` 不成为独立的顶层声明或全局关键字。全为 unit variant 的 sum type 自然承担 enum 的用途。

每个 `type` 都声明新的 nominal type。`type Point = { ... }` 不创建 structural type alias；两个字段完全相同的声明仍是两个不同类型。

## Variant namespace

Variant 属于其 sum type 的 namespace：

```epic
let kind = TokenKind.FUN
let expr = new Expr.Lit { value: 42 }
```

Payload variant 应当是可命名的具体类型，以便 match narrowing 能跨 helper 边界继续保留：

```epic
fun emit_lit(expr: Expr.Lit): void {
    println(str(expr.value))
}
```

这避免重新引入“调用者已经知道具体 variant，helper 却重新接收宽 union”的信息损失。

## Match

Unit sum 与 payload sum 使用同一套 `match`：

```epic
match kind {
    TokenKind.EOF: {}
    TokenKind.ID: {}
    TokenKind.FUN: {}
}

match expr {
    Expr.Lit lit: {
        emit_lit(lit)
    }
    Expr.Add add: {
    }
}
```

封闭 sum 应进行穷尽性检查；`_` 保持显式兜底分支。

## Source semantics and representation

统一源码模型不要求统一运行时布局：

| 类型形态 | 初始表示方向 |
|---|---|
| 单一 product | heap-backed reference，与当前 struct 类似 |
| unit sum | unboxed scalar tag |
| payload sum | tagged payload reference |

Unit sum 是独立 nominal type，不是整数 alias。第一版不开放 tag、ordinal、整数转换、算术、排序或位运算。内部 tag 分配和宽度不属于源码合约。

## v0 边界

v0 保留当前 `struct`、payload ADT 和字符串 `Token.kind`。v0 不加入以下过渡语法：

```epic
enum TokenKind = EOF | ID
type TokenKind: enum = EOF | ID
type TokenKind: i64 = EOF | ID
```

实现临时 enum surface 会迫使 Python reference、Epic 自举编译器、测试和文档迁移两次，并可能提前固定错误的 namespace、constructor 或 representation 语义。

## 实现前必须 grill

以下问题尚未决定，不能从示例语法反推实现：

- Product variant 是否允许独立 receiver method。
- Unit variant 与 payload variant 是否允许出现在同一个 sum 中。
- Payload sum 使用一层还是两层分配。
- Variant payload 是否内联于 tagged object。
- Common-field access 是否保留。
- Unit sum 作为未显式初始化的 struct 字段时采用什么默认值。
- Recursive product 与 recursive sum 的合法边界。
- Variant 与 type、function、field 名称的冲突规则。
- 是否允许复用已声明 product 作为 variant payload。

## 迁移原则

这次变化不提供向前兼容语法。实施时应一次性完成：

1. 确定 namespace、constructor、match 和 representation 语义。
2. 在 Python reference compiler 中实现完整语义。
3. 在 Epic 自举编译器中实现相同语义。
4. 将 compiler、runtime、examples 和 tests 迁移到统一声明。
5. 删除旧 `struct` 与旧 payload-union surface。
6. 运行模块测试、examples、e2e 和 bootstrap fixed point。

在这些决策完成以前，字符串 `Token.kind` 是有意保留的简单实现，不应成为引入临时 enum 语法的理由。
