# Unified Type Declarations

本文档记录 Epic 统一类型声明的当前边界和后续方向。v0 已统一 product 与 named payload sum 的顶层声明；unit sum、inline payload variant 和 variant namespace 留给后续版本。

## 决策

Epic 只使用 `type` 声明 nominal type。v0 当前支持两种 RHS：

```epic
type Point = {
    x: i64
    y: i64
}

type Lit = {
    value: i64
}

type Add = {
    left: Expr
    right: Expr
}

type Expr = Lit | Add
```

对应关系：

| 声明形态 | 类型结构 | v0 状态 |
|---|---|---|
| `type A = { ... }` | 单一 product | 已支持 |
| `type A = X \| Y` | 由已声明 product 组成的 named payload sum | 已支持，至少两个 member |
| `type A = X \| Y`，其中 `X` / `Y` 未声明 product | unit sum | 未支持 |
| `type A = X { ... } \| Y { ... }` | inline payload sum | 未支持 |

`enum` 不成为独立的顶层声明或全局关键字。未来全为 unit variant 的 sum type 自然承担 enum 的用途。

每个 `type` 都声明新的 nominal type。`type Point = { ... }` 不创建 structural type alias；两个字段完全相同的声明仍是两个不同类型。

## Future variant namespace

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

## Future match extensions

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
| 单一 product | heap-backed reference |
| unit sum | unboxed scalar tag |
| payload sum | tagged payload reference |

Unit sum 是独立 nominal type，不是整数 alias。第一版不开放 tag、ordinal、整数转换、算术、排序或位运算。内部 tag 分配和宽度不属于源码合约。

## v0 边界

v0 删除了独立的 `struct` 关键字，`struct` 已恢复为普通标识符。当前 product 与 named sum 语法是：

```epic
type Point = {
    x: i64
    y: i64
}

type Expr = Lit | Add
```

Product 字段每行一个，不使用逗号；空 product 与单行单字段合法。Named sum 必须写在一个逻辑行内并至少有两个 member。Product 支持 receiver method、前向引用、自递归和 mutual recursion；sum 暂不支持 receiver。初始化器继续支持全省略、部分指定和全指定字段。

v0 不加入以下过渡语法：

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
- Unit sum 作为未显式初始化的 product 字段时采用什么默认值。
- Recursive product 与 recursive sum 的合法边界。
- Variant 与 type、function、field 名称的冲突规则。
- 是否允许复用已声明 product 作为 variant payload。

## Future migration principles

这次变化不提供向前兼容语法。实施时应一次性完成：

1. 确定 namespace、constructor、match 和 representation 语义。
2. 在 Python reference compiler 中实现完整语义。
3. 在 Epic 自举编译器中实现相同语义。
4. 将 compiler、examples 和 tests 迁移到扩展后的 sum 声明。
5. 删除当前 named-member payload-sum surface。
6. 运行模块测试、examples、e2e 和 bootstrap fixed point。

在这些决策完成以前，字符串 `Token.kind` 是有意保留的简单实现，不应成为引入临时 enum 语法的理由。
