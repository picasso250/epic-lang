# 原则

- 新 feature / bug fix / refactor 完成之后，git 提交 并 push。（如push被安全拦截，则不再尝试push）
- 马斯克五步工作法。（第一步：质疑需求；第二步：删掉所有可能的部件；第三步：简化与优化；第四步：加速周转；第五步：自动化）
- 不要向前兼容。
- 用性能换代码清晰。
- Python reference compiler 和 Epic 自举编译器 的语法界面不同，现阶段完全相同，未来后端会分叉（后端优化在ep上做 ）
- 测试原则：重视e2e，轻视白盒测试，让测试服务于意图，而不绑定具体实现。

## 开发流程

- 开发之前先读 docs/ 中的相关文档
- `bootstrap/` 是当前语言的 Python reference compiler。
- `src/` 是当前 Epic 自举编译器源码和 Epic 工具源码。
- `runtime/`、`examples/`、`docs/`、`editors/` 都服务当前语言实现。
- 当前测试入口（按推荐顺序）：
  - `python tests/run.py`             # 模块级测试体系
  - `python tests/examples/run.py`      # examples/ 正向学习示例
  - `python test_bootstrap_fixed_point.py` # 自举 不动点
- `examples/` 只放正向、典型、适合初学者学习的示例程序，不放负向测试。
- 负向测试放 `tests/<module>/fail/`。
- `test_*.py` 是可直接运行的脚本测试，不是 pytest 测试；不要把 `python -m pytest` 当作支持入口。

## 现状

- 自举完成

## 提示

- git 的 CRLF 问题不需要解决，直接提交即可，不论是 python 还是 epic 都能兼容所有的 CRLF/LF
