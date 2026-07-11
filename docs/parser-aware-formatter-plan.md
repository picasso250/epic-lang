# Parser-aware formatter plan

目标：把 `tools/epicfmt.py` 从 brace/text formatter 改成 parser-aware formatter，避免格式化生成当前语言 parser 不能接受的源码。

## 原则

- 不向前兼容旧格式器行为。
- Formatter 以语法结构为准，不靠 `{` / `}` 文本拆行猜测结构。
- Comment 必须保留；comment 不进入语义 AST 主干，但 formatter 要知道它们的位置。
- Formatter 输出必须能被当前 Epic parser 重新解析。

## 最小长期路线

1. 升级 token
   - 从 tuple token 过渡到结构化 token。
   - 记录 `kind`、`text`、`line`、`col`、`start`、`end`。
   - lexer 支持可选保留 comment token。

2. 升级 parser 位置信息
   - AST node 记录 `start` / `end` token 或 source span。
   - compiler 路径可以继续忽略 comment。
   - formatter 路径使用 comment + span 做排版。

3. 建立 comment 归属
   - leading comments：节点前连续注释。
   - trailing comments：同一行尾注释。
   - detached comments：与节点间有空行的注释块。

4. 写 AST printer
   - Program / type / struct / fun。
   - statement。
   - expression，包含 precedence，避免重印后语义变化。
   - match pattern、struct init、array literal、f-string。

5. Formatter 验证
   - `python tools/epicfmt.py -w` 写入前先 parse formatted text。
   - 增加 formatter fixture 测试。
   - 对 `src/*.ep` 跑 formatter 后再跑：
     - `python tests/examples/run.py`
     - `python test_bootstrap_fixed_point.py`

## 参考模型

接近 `gofmt`：AST 决定代码结构，comment group 作为带源码位置的 trivia 被 printer 重新插回。
