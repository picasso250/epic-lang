# 原则

- 新 feature / bug fix / refactor 完成之后，git 提交 并 push。
- 马斯克五步工作法。（第一步：质疑需求；第二步：删掉所有可能的部件；第三步：简化与优化；第四步：加速周转；第五步：自动化）
- 不要向前兼容。
- 用性能换代码清晰。

## 开发流程

- 旧目录化 bootstrap 链保存在 git 历史和 tag `staged-bootstrap-archive-2026-06-30`，只作为历史锚点。
- 当前仓库根目录就是当前语言实现的项目根。
- `bootstrap/` 是当前语言的 Python reference compiler。
- `src/` 是当前 Epic 自举编译器源码和 Epic 工具源码。
- `runtime/`、`examples/`、`docs/`、`editors/`、`tree-sitter-epic/` 都服务当前语言实现。
- `epic-bootstrap.py` 是 `test_bootstrap_fixed_point.py` 的薄封装；当前 bootstrap 模型是 `Python reference compiler -> Epic compiler -> Epic compiler`。
- 当前测试入口（按推荐顺序）：
  - `python tests/run.py`             # 模块级测试体系
  - `python test_examples_py.py`      # examples/ 正向学习示例
  - `python tests/mir/run.py`          # MIR 测试
  - `python tests/x64/run.py`          # X64 后端测试
- 不要运行：
  - `python -m pytest`（不是 pytest 体系）
  - `test_*bootstrap*.py`（bootstrap 自举测试战略性放弃）
- `examples/` 只放正向、典型、适合初学者学习的示例程序，不放负向测试。
- 负向测试放 `tests/<module>/fail/`。
- typed AST 不单独建顶层测试目录；它属于 sema 输出契约，测试放 `tests/sema/`。
- `tests/lexer/pass/all.ep` 是 lexer 规格样本，覆盖所有 token 种类。
- `tests/lexer/pass/token_list.txt` 由 `bootstrap/lexer.py` 生成，人眼 review 后提交。
  更新方式：`python tests/lexer/run.py --regen`
- 不要为了新 feature 同步维护旧目录化版本；需要历史行为时看 tag 或旧提交。
- `test_*.py` 是可直接运行的脚本测试，不是 pytest 测试；不要把 `python -m pytest` 当作支持入口。

## 现状

- Python reference compiler ok `python test_examples_py.py`
- 未来再 eat dog food ，现在先让py实现ok，正在去 nasm.exe 化
- 我们现在战略性放弃ep自举，只攻py实现 `test_*bootstrap*.py` 一概不用跑。跑了也会失败。