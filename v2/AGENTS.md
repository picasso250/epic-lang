- win32 api确实难。但我们可以充分利用工具，你有gcc，你可以写一个简单的win api c程序（不要开任何优化），然后编译成汇编！然后你可以看了。
- 新 feature / bug fix / refactor 完成之后，git 提交 并 push。
- 马斯克五步工作法。（第一步：质疑需求；第二步：删掉所有可能的部件；第三步：简化与优化；第四步：加速周转；第五步：自动化）

## v2 开发流程

- v2 是由 v1 编译器锚点编译的下一代源码目录。
- 根目录 `epic-bootstrap.py` 当前只保证生成 `build\v0.exe` 和 `build\v1.exe`；v2 还没有新 feature，暂时不要求顶层 bootstrap 生成 `v2.exe`。
- v2 的版本测试在 `v2/` 目录内运行，并使用根目录 `build\v1.exe` 作为 previous compiler anchor。
- v2 只记录相对 v1 的设计和实现差异；没有差异时不要复制一份 v1 设计。
