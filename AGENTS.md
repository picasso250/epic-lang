# 原则

- 新 feature / bug fix / refactor 完成之后，git 提交 并 push。（如push被安全拦截，则不再尝试push）
- 马斯克五步工作法。（第一步：质疑需求；第二步：删掉所有可能的部件；第三步：简化与优化；第四步：加速周转；第五步：自动化）
- 不要向前兼容。
- 用性能换代码清晰。
- Python reference compiler 和 Epic 自举编译器的语言语义必须保持一致；当前 shift count 统一要求 `i64`；v0 对所有 count 一律生成运行时范围检查，`shl` / `sar` / `shr` 只由左操作数类型决定。未来只允许后端优化实现分叉。
- 测试原则：重视e2e，轻视白盒测试，让测试服务于意图，而不绑定具体实现。

## 开发流程

- 开发之前先读 docs/ 中的相关文档
- `bootstrap/` 是当前语言的 Python reference compiler。
- `src/` 是当前 Epic 自举编译器源码和 Epic 工具源码。
- `runtime/`、`examples/`、`docs/`、`editors/` 都服务当前语言实现。
- 当前测试入口（按推荐顺序）：
  - `python tests/run.py`             # 模块级测试体系
  - `python tests/examples/run.py`      # examples/ 正向学习示例
  - `python bootstrap_fixed_point.py`      # 构建并验证自举不动点
- `examples/` 只放正向、典型、适合初学者学习的示例程序，不放负向测试。
- 负向测试放 `tests/<module>/fail/`。
- `test_*.py` 是可直接运行的脚本测试，不是 pytest 测试；不要把 `python -m pytest` 当作支持入口。

## 现状

- 自举完成

## 提示

- git 的 CRLF 问题不需要解决，直接提交即可，不论是 python 还是 epic 都能兼容所有的 CRLF/LF
