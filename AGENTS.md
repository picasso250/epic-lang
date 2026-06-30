# 原则

- 新 feature / bug fix / refactor 完成之后，git 提交 并 push。
- 马斯克五步工作法。（第一步：质疑需求；第二步：删掉所有可能的部件；第三步：简化与优化；第四步：加速周转；第五步：自动化）
- 不要向前兼容。

## 开发流程

- 旧目录化 bootstrap 链保存在 git 历史和 tag `staged-bootstrap-archive-2026-06-30`，只作为历史锚点。
- 当前仓库根目录就是当前语言实现的项目根。
- `bootstrap/` 是当前语言的 Python reference compiler。
- `src/` 是当前 Epic 自举编译器源码和 Epic 工具源码。
- `runtime/`、`examples/`、`docs/`、`editors/`、`tree-sitter-epic/` 都服务当前语言实现。
- `epic-bootstrap.py` 是 `test_bootstrap_fixed_point.py` 的薄封装；当前 bootstrap 模型是 `Python reference compiler -> Epic compiler -> Epic compiler`。
- 当前接受测试优先运行：
  - `python runtests.py --linker py`
  - `python test_bootstrap_fixed_point.py`
- 不要为了新 feature 同步维护旧目录化版本；需要历史行为时看 tag 或旧提交。
- `test_*.py` 是可直接运行的脚本测试，不是 pytest 测试；不要把 `python -m pytest` 当作支持入口。

## 现状

- Python reference compiler ok `python runtests.py --linker py`
- 正在 eat dog food . test_lexer_bootstrap.py 通过，其他还未通过