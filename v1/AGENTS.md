- win32 api确实难。但我们可以充分利用工具，你有gcc，你可以写一个简单的win api c程序（不要开任何优化），然后编译成汇编！然后你可以看了。
- 新 feature / bug fix / refactor 完成之后，git 提交 并 push。
- 马斯克五步工作法。（第一步：质疑需求；第二步：删掉所有可能的部件；第三步：简化与优化；第四步：加速周转；第五步：自动化）

## v1 开发流程

- v1 主线开发默认抛弃 Python 编译器路径；不要为了 v1 feature 同步维护 `lexer.py` / `parser.py` / `codegen.py` / `epic.py`。
- v1 的 EP 源码由根目录 `build\v0.exe` 编译；这个编译器由 `..\v0` 的 fixed-point bootstrap 产生。
- 当前 v1 源码使用 v0 语法，因此不要尝试用 `v1.exe` fixed-point 编译当前 v1 源码。
- 只有当 v0 编译器本身有 bug、导致 v1 无法可靠前进时，才修改 `..\v0` 的 Python 和 EP 两套实现。
- v1 的新语言能力优先修改 `.ep` 编译器源码、runtime 和设计文档；Python 文件在 v1 中视为历史 bootstrap 参考，不是主实现。
