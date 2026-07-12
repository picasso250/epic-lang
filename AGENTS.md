# 原则

- 新 feature / bug fix / refactor 完成之后，git 提交 并 push。（如push被安全拦截，则不再尝试push）
- 马斯克五步工作法。（第一步：质疑需求；第二步：删掉所有可能的部件；第三步：简化与优化；第四步：加速周转；第五步：自动化）
- 不要向前兼容。
- 用性能换代码清晰。
- 当前活跃实现只有 Epic 自举编译器；冻结的 Python stage-0 仅保留在 `v0` 标签中。
- 测试原则：重视e2e，轻视白盒测试，让测试服务于意图，而不绑定具体实现。

## 开发流程

- 开发之前先读 docs/ 中的相关文档
- `src/` 是当前 Epic 自举编译器源码和 Epic 工具源码。
- `runtime/`、`examples/`、`docs/`、`editors/` 都服务当前语言实现。
- 当前测试入口（按推荐顺序）：
  - `python tests/run.py`             # 模块级测试体系
  - `python tests/examples/run.py`      # examples/ 正向学习示例
  - `python test_bootstrap_fixed_point.py` # 从冻结 v0 seed 开始的自举不动点
- `examples/` 只放正向、典型、适合初学者学习的示例程序，不放负向测试。
- 负向测试放 `tests/<module>/fail/`。
- `test_*.py` 是可直接运行的脚本测试，不是 pytest 测试；不要把 `python -m pytest` 当作支持入口。

## 性能测量

- `test_bootstrap_fixed_point.py` 的三代编译由不同代编译器执行，不能直接当作三次等价性能样本。先运行一次 fixed point 验证收敛，再复用收敛编译器测量同一 workload。
- wall time 使用外部高精度计时（例如 Python `time.perf_counter_ns()`）；编译器内部的 `GetTickCount64()` 适合阶段诊断，不适合判断约 1% 以内的差异。
- 默认先测 3 次并报告 median；这足以发现明显变化，但不足以证明很小的变化。
- 当差异小于 1%、三次结果方向不一致、或差异接近计时粒度时，改为 A/B 交错顺序并增加到 9 次；仍不能区分时最多增加到 15 次，然后将结论标为“未确认有变化”，不要继续堆样本。
- A/B 必须使用相同源码、相同 seed、相同参数和相同输出位置条件；同时报告 wall time、X64 items、`.text` bytes 和最终 exe size。

## 现状

- 自举完成

## 提示

- git 的 CRLF 问题不需要解决，直接提交即可，不论是 python 还是 epic 都能兼容所有的 CRLF/LF
