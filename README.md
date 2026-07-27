# Epic

引导链如下：

```text
Python v0 stage-0 -> Epic v1 -> Epic v2 -> Epic v3 -> Epic v4 -> Epic v4 fixed point
```

## 规范历史（Canonical history）

> 修正历史时，应将设计回溯到它合理归属的最早版本，而非技术上能够实现的最早版本。

## 构建（Build）

```powershell
python build_epic.py
```

该脚本将封存的本地 `v3` 分支解析为一个精确的 commit。当 `build/epic-v3-<hash>.exe` 已存在时直接复用；否则创建一个 detached v3 worktree，并调用该世代的 `build_epic.py`。生成的 v3 编译器随后编译当前的 v4 working tree。

默认输出为 `build/epic-v4.exe`。传入 `-o PATH` 可仅将最终的 v4 可执行文件复制到其他位置；相对路径从调用方的工作目录（calling working directory）解析。

## 文档（Documentation）

- [语言参考](docs/language.md)，包括内置数据结构与函数
- [编译器实现](docs/implementation.md)
- [垃圾收集器](docs/gc.md)

验证自托管 fixed point：

```powershell
python bootstrap_fixed_point.py
```

v3 构建的 v4 seed 编译第 1 代，然后第 1 代编译第 2 代。只有当第 1 代与第 2 代字节完全相同时检查才通过。

## 测试（Test）

```powershell
python tests/run.py
```

`examples/` 包含小型学习序列。更广泛的回归测试位于 `tests/e2e/pass/` 下。
