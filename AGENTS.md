- win32 api确实难。但我们可以充分利用工具，你有gcc，你可以写一个简单的win api c程序（不要开任何优化），然后编译成汇编！然后你可以看了。
- 新 feature / bug fix / refactor 完成之后，git 提交 并 push。
- 马斯克五步工作法。（第一步：质疑需求；第二步：删掉所有可能的部件；第三步：简化与优化；第四步：加速周转；第五步：自动化）
- 不要向前兼容。

## 目录化版本开发流程

- `main` 是主干分支；版本用目录表达，不再用 `v0` / `v1` / `v2` 分支做日常开发。
- `v0/`、`v1/`、`v2/` 各自保留完整项目根目录形态；版本源码、runtime、examples、测试和版本文档都放在对应目录内。
- 仓库根目录不是任何一个语言版本。根目录只保留全仓库规则、总览、跨版本日志、共享工具目录、`tree-sitter-epic/` 和跨版本 bootstrap 脚本。
- 根目录 `tools/` 是本地共享工具目录，供各版本脚本使用；不要把构建产物放进版本源码目录之外长期维护。
- 根目录 `epic-bootstrap.py` 负责串联 bootstrap：先在 `v0/` 得到 fixed-point 编译器并复制为 `build/v0.exe`，再用它编译 `v1/` 得到 `build/v1.exe`，再用 `v1.exe` 编译 `v1/link.ep` 得到 `build/link.exe`，并同步到 `v2/build/`。
- `main` 不重复运行各版本完整测试；版本测试在对应版本目录里运行。
- v1 主线开发默认抛弃 Python 编译器路径；不要为了 v1 feature 同步维护 `lexer.py` / `parser.py` / `codegen.py` / `epic.py`。
- v1 的 EP 源码由 v0 编译器编译。当前 v1 源码使用 v0 语法，因此不要尝试用 `v1.exe` fixed-point 编译当前 v1 源码。
- 只有当 v0 编译器本身有 bug、导致 v1 无法可靠前进时，才修改 `v0/` 的 Python 和 EP 两套实现。
