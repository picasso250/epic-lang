- win32 api确实难。但我们可以充分利用工具，你有gcc，你可以写一个简单的win api c程序（不要开任何优化），然后编译成汇编！然后你可以看了。
- 新 feature / bug fix / refactor 完成之后，git 提交 并 push。
- 马斯克五步工作法。（第一步：质疑需求；第二步：删掉所有可能的部件；第三步：简化与优化；第四步：加速周转；第五步：自动化）

## v1 开发流程

- v1 主线开发默认抛弃 Python 编译器路径；不要为了 v1 feature 同步维护 `lexer.py` / `parser.py` / `codegen.py` / `epic.py`。
- v1 的 EP 源码由 v0 编译器编译：先切到 `v0` 分支完成两阶段自举拿到 `build\v0.exe`，再切回 `v1` 用 `build\v0.exe` 编译 v1。
- 只有当 v0 编译器本身有 bug、导致 v1 无法可靠前进时，才回 `v0` 分支修复 Python 和 EP 两套实现，提交并 push 后再合并回 `v1`。
- v1 分支上的新语言能力优先修改 `.ep` 编译器源码、runtime 和设计文档；Python 文件在 v1 中视为历史 bootstrap 参考，不是主实现。
