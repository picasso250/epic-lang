# 原则

- 新 feature / bug fix / refactor 完成之后，git 提交 并 push。（如push被安全拦截，则不再尝试push）
- 马斯克五步工作法。（第一步：质疑需求；第二步：删掉所有可能的部件；第三步：简化与优化；第四步：加速周转；第五步：自动化）
- 不要向前兼容。
- 用性能换代码清晰。
- 当前活跃实现只有 Epic 自举编译器；冻结的 Python stage-0 仅保留在 `v0` 标签中。
- 不要修改或移动 `v0` 标签。冻结 v0 会把无符号 `>>` 错降为 `sar`；当前 bootstrap 仅因相关用法随后 `& u64(255)` 才安全。不要在 bootstrap-sensitive 的 `src/` / `runtime/` 中新增一般无符号右移依赖；详见 `docs/impl.md`。
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

- 基线优先运行 `python benchmark_self_host.py --label <name>`。脚本按 seed exe、canonical compiler 源码、runtime `.ep/.mir`、测量工具和宿主指纹生成内容 key，并分层缓存 fixed-point compiler 与 3 次等价 benchmark 到 `build/cache/self-host-benchmark/`；输入未变时直接呈现缓存结果。需要同日实时重测时使用 `--refresh`，它仍复用相同的收敛编译器。
- `test_bootstrap_fixed_point.py` 的三代编译由不同代编译器执行，不能直接当作三次等价性能样本。先运行一次 fixed point 验证收敛，再复用收敛编译器测量同一 workload。
- wall time 使用外部高精度计时（例如 Python `time.perf_counter_ns()`）；编译器内部的 `GetTickCount64()` 适合阶段诊断，不适合判断约 1% 以内的差异。
- 性能对比测 3 次并报告 median；如果 3 次不能显示稳定、显著的变化，直接结论为“性能变化不显著”，不要增加到 9 次或 15 次继续追逐噪声。
- A/B 必须使用相同源码、相同 seed、相同参数和相同输出位置条件；同时报告 wall time、X64 items、`.text` bytes 和最终 exe size。

## 现状

- 自举完成

## 提示

- git 的 CRLF 问题不需要解决，直接提交即可，不论是 python 还是 epic 都能兼容所有的 CRLF/LF
