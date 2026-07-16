# 原则

- 新 feature / bug fix / refactor 完成之后，git 提交。（只 推送 dev 和 main）
- 马斯克五步工作法。（第一步：质疑需求；第二步：删掉所有可能的部件；第三步：简化与优化；第四步：加速周转；第五步：自动化）
- 不要向前兼容。
- 允许用性能换代码清晰。
- 当前活跃实现只有 Epic 自举编译器；Python stage-0 与可复现 seed 构建入口维护在 `v0` 分支。
- `v0` 是可演进的 bootstrap 分支，不是不可移动标签；它必须通过自身 fixed point 与已提交 SHA-256。`v0` 只实现构建当前 `dev` 所需的最小源码语义，不承诺当前公开 ABI：例如它支持只读 `s[i]` 以编译新 frontend，但保留旧 `str`/slice bootstrap 布局。当前 v0 已支持 `embed "path"` 与 `0x`/`0X` 十六进制整数；`>>` / `>>=` 按左值类型选择算术或逻辑右移，所有 shift count 必须是 `i64`。当前 `dev` 对裸整数字面量静态检查并消除检查，`v0` 为简化 bootstrap 对所有 count 一律生成运行时检查；`>>>` / `>>>=` 已删除。
- 测试原则：重视e2e，轻视白盒测试，让测试服务于意图，而不绑定具体实现。不好的测试，可以删。

## 开发流程

- 开发之前先读 docs/ 中的相关文档
- `src/` 是当前 Epic 自举编译器源码和 Epic 工具源码。
- `runtime/`、`examples/`、`docs/` 都服务当前语言实现；编辑器适配维护在独立仓库。
- 当前测试入口（按推荐顺序）：
  - `python tests/run.py`             # 模块级测试体系
  - `python tests/examples/run.py`      # examples/ 正向学习示例
  - `python bootstrap_fixed_point.py` # 从 v0 分支 seed 开始的自举不动点
- `examples/` 只放正向、典型、适合初学者学习的示例程序，不放负向测试。
- 负向测试放 `tests/<module>/fail/`。
- `test_*.py` 是可直接运行的脚本测试，不是 pytest 测试；不要把 `python -m pytest` 当作支持入口。

## 性能测量

- 当前未提交代码直接运行 `python bootstrap_fixed_point.py`；最后一次 `generation 2 -> generation 3` 编译既验证不动点，也输出唯一的 `profile:` 性能样本。
- 已提交基线运行 `python benchmark_self_host.py <revision>`。脚本以完整 dev commit hash 与当前完整 v0 commit hash 缓存完整 bootstrap stdout 到 `build/profile/`；缓存存在时直接读取。需要重测时删除对应 txt。
- wall time 使用外部高精度计时（例如 Python `time.perf_counter_ns()`）；编译器内部的 `GetTickCount64()` 适合阶段诊断，不适合判断约 1% 以内的差异。
- 性能只测一次；3% 以内视为噪声。既有实验中真正值得保留的优化通常接近或超过 10%，不要为追逐小差异增加样本。
- A/B 必须使用相同源码、相同 seed、相同参数和相同输出位置条件；同时报告 wall time、X64 items、`.text` / `.data` bytes 和最终 exe size。

## 现状

- 自举完成

## 提示

- git 的 CRLF 问题不需要解决，直接提交即可，不论是 python 还是 epic 都能兼容所有的 CRLF/LF
