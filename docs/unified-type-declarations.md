# Unified Type Declarations

本文档记录 Epic 统一 nominal type 声明的当前语义。Epic 不增加 `enum` 关键字；product、unit sum 与 named payload sum 都由 `type` 表达。

## 声明形态

```epic
type Point {
    x: i64
    y: i64
}

type TokenKind = EOF | ID | FUN

type Lit {
    value: i64
}

type Add {
    left: Expr
    right: Expr
}

type Expr = Lit | Add
```

| 声明形态 | 类型结构 |
|---|---|
| `type A { ... }` | product |
| `type A = X \| Y`，所有 member 都是已声明 product | named payload sum |
| `type A = X \| Y`，所有 member 都不是已声明 product | unit sum |

分类发生在收集全部 product 声明之后，因此不依赖源码先后顺序。部分 member 是 product、部分不是 product 的声明非法；重复 member 非法。Named sum 至少包含两个 member。

Product member 是可独立复用、可拥有 receiver method 的普通 nominal product。Epic 不支持 inline payload variant，例如 `type A = X { ... } | Y { ... }`；payload 必须先声明为 product。这条边界是有意的，不是待实现的临时缺口。

`type A = Existing` 保留给未来可能的 nominal alias，不解释为单成员 sum。独立的 `struct` 和 `enum` 关键字都不存在。

## Unit sum 值

Unit variant 始终通过 sum namespace 引用：

```epic
let kind = TokenKind.ID
if kind != TokenKind.EOF {
}
```

裸 `ID` 不根据赋值目标、比较另一侧或 match scrutinee 推断。不同 unit sum 可以复用同名 variant，例如 `TokenKind.ID` 与 `NodeKind.ID` 是不同类型的值。

Unit sum 是独立 nominal type，不是整数 alias。它支持：

- local、函数参数和返回值
- product 字段
- `T[]` 动态数组及其 `push`、`pop`、`extend`
- 同类型的 `==`、`!=`
- `match`

它不支持整数转换、ordinal/tag 观察、算术、排序、位运算、`str`/print/f-string 转换、postfix `?`、receiver method、extern ABI 或 `cptr`。不同 unit sum 即使 member 完全相同也不能比较或赋值。

## Match

Unit sum case 使用完整 namespace，不绑定 payload：

```epic
match kind {
    TokenKind.EOF: {}
    TokenKind.ID: {}
    TokenKind.FUN: {}
}
```

Payload sum 保留 product member 与 binding 形式：

```epic
match expr {
    Lit lit: {
        println(str(lit.value))
    }
    Add add: {}
}
```

两种封闭 sum 都必须覆盖全部 member，或提供 `_` 兜底。重复 case 非法。Unit case 写成 `ID value:` 非法，因为 unit variant 没有 payload。

## 构造与默认值

Payload sum 继续显式包装：

```epic
let expr: Expr = new Expr(new Lit { value: 42 })
```

Unit sum 不使用 `new`。声明顺序中的第一个 variant 是语言层面的零值；零初始化的 product 字段和 `new TokenKind[n]` 数组槽都取第一个 variant。除此之外，variant 的数值、位宽和 tag 分配不属于源码合约。

## 表示

| 类型形态 | 当前 v1 表示 |
|---|---|
| product | heap-backed reference |
| unit sum | unboxed 64-bit scalar tag |
| payload sum | heap-backed `{ tag, payload pointer }` wrapper |

Unit sum 的 product 字段和数组槽当前均占 8 bytes。未来后端可以在不改变第一 variant 为零值这一语义的前提下压缩存储宽度。

## 语法边界

Product 字段每行一个，不使用逗号；空 product 与单行单字段合法。Named sum 写在一个逻辑行内。Product 支持前向引用、自递归、mutual recursion 和 receiver method；sum 不支持 receiver。Product 初始化器支持全省略、部分指定和全指定字段。

以下过渡语法不属于语言：

```epic
enum TokenKind = EOF | ID
type TokenKind: enum = EOF | ID
type TokenKind: i64 = EOF | ID
```
