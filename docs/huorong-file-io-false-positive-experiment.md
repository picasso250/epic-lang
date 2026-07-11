# 火绒文件 I/O 误报规避实验记录

日期：2026-07-11

## 背景

在提交 `7ca8ac6`（`refactor: move x64 runtime into MIR`）之后，部分使用 Epic 文件 I/O runtime helper 的正常 Windows x64 程序会被火绒识别为：

```text
Trojan/ShellLoader.ar!crit
rule id: C79A558BA0AE9469
```

已知受影响的测试包括：

- `tests/e2e/pass/m11_file.ep`
- `tests/e2e/pass/m24_read_file.ep`
- `tests/e2e/pass/m26_write_file.ep`
- `tests/e2e/pass/v1_byte_io_endian.ep`

先前证据表明，自带 Python PE linker 与 LLD-Link 生成的不同 PE 文件都可能命中同一规则。因此，本次实验检查一个更具体的假设：误报是否由 `__ep_read_file` 和 `__ep_write_file` 经通用 MIR → X64 lowering 后形成的机器码形态触发。

## 实验假设

将以下两个 helper 从通用 MIR lowering 改为后端专门化的手写 X64 lowering，可能改变机器码形态并避开火绒规则：

- `__ep_read_file`
- `__ep_write_file`

实验没有恢复整套旧 X64 runtime。MIR 中仍保留两个 helper 的定义，以维持语义、可达性分析、ABI 校验和 WinAPI 依赖；只有最终 X64 发射改为专用路径。

该实现仅用于 A/B 验证，实验结束后不保留代码。

## 实验实现

临时增加了一个专用 X64 file runtime emitter，并在 Python reference backend 的 `MirLower.lower()` 中按函数名分派：

```text
__ep_read_file  -> 专用 X64 emitter
__ep_write_file -> 专用 X64 emitter
其他函数         -> 通用 MIR lowering
```

基础验证结果：

```text
python tests/mir/run.py   PASS
python tests/x64/run.py   PASS
```

完整 e2e 在项目 worktree 内运行结果：

```text
77 passed, 0 failed, 0 skipped
```

## 生成物差异

### 原通用 MIR lowering 版本

| 文件 | 大小 | SHA-256 |
|---|---:|---|
| `m11_file.exe` | 11264 | `3104CC50B41AE5CA1C8E1AE0BE3F1028872BDEEAFDE0B0A4F7E80F0A0FB75D1D` |
| `m24_read_file.exe` | 10240 | `03D997E87FD4F62A9CD3ECBDB22F61EB2CB6F80D2EC85AEFD4843B6E360B3B9F` |
| `m26_write_file.exe` | 10752 | `AE3B7D7BC9D3F801F24C9C69174238A52206BB5E46C826492BE5B7C259DD0F7E` |
| `v1_byte_io_endian.exe` | 19456 | `3B552BCFABC9FD2E8C026CFA5CD9D4E75A3FC5E8D04D13EE9DB96DA7BFA9D85C` |

### 专用 X64 helper 版本

| 文件 | 大小 | SHA-256 |
|---|---:|---|
| `m11_file.exe` | 10752 | `344D9927E6E40D779E38F44ACC3F7D3DA4331944FBBC672E3B5FACF6900AA4FC` |
| `m24_read_file.exe` | 10240 | `B25463DF2333CE53F961360B70F2573F877374144916B3703AA4CC63A3D19D57` |
| `m26_write_file.exe` | 10240 | `98C58B5E0AEEBCB60B67EBDD004E3DC8AB570F30AFC320846F63AFB5907AC584` |
| `v1_byte_io_endian.exe` | 18944 | `C5652498CE508B0AE4D6AC2E631A50482E5454D954FEE4F8DB4E3324E68CE61B` |

这些变化证明专用 lowering 确实产生了不同的 PE 内容，但不能单独证明规避成功。

## 初次观察及其问题

专用版本在以下 worktree 中直接执行时没有弹出新的火绒警告：

```text
C:\Users\MECHREV\projects\epic-lang-pe-hardening
```

`m11_file.exe` 当时正常输出：

```text
42
2
```

最初曾据此推测专用 lowering 没有命中规则。这个结论后来被证明无效。

最初的设置页确实显示过以下目录级选项：

```text
不扫描指定程序的动作：C:\Users\MECHREV\projects\
```

但该设置存在时，第一次 e2e 仍然对四个 file I/O EXE 报毒，因此它没有阻止本次病毒查杀，不能解释后续的“无弹窗”。用户随后对四次报警逐一点击了“信任”。火绒的信任区后来明确显示，加入信任的是 `build/tests/e2e/pass/` 下四个具体 EXE 的完整文件路径：

- `m11_file.exe`
- `m24_read_file.exe`
- `m26_write_file.exe`
- `v1_byte_io_endian.exe`

目录级的“不扫描指定程序的动作”选项随后已经取消。专用 lowering 重新构建时虽然改变了这四个文件的内容和 SHA-256，却仍覆盖到相同的完整路径，因此火绒继续放行。这里真正污染实验的是四个精确 EXE 路径的信任项，而不是整个项目目录。

## 路径隔离验证

为了排除“火绒按具体 EXE 路径信任，而不是专用 helper 真正规避检测”的可能性，将专用版本的 `m11_file.exe` 原样复制到一个未列入信任区的随机 `%TEMP%` 路径，并改成新文件名。选择项目目录之外只是为了减少混杂因素；判别所必需的是使用新的完整文件路径，而不是必须离开项目目录：

```text
%TEMP%\epic-av-probe-<random>\renamed-file-io-probe.exe
```

复制前后 SHA-256 完全一致：

```text
344D9927E6E40D779E38F44ACC3F7D3DA4331944FBBC672E3B5FACF6900AA4FC
```

因此该步骤只改变：

- 文件路径；
- 文件名。

没有改变文件内容。

执行结果：

- 火绒再次报告病毒；
- 程序执行被阻止或干扰；
- 进程返回 `-1`；
- 没有输出预期的 `42` 和 `2`；
- 没有生成 `test_out.txt`；
- EXE 文件本身仍存在。

用户在火绒界面确认此次确实出现了病毒报警。

## 最终结论

本次实验不能证明专用 X64 helper 能规避火绒检测。相反，在未列入信任区的新完整路径上测试后，专用版本仍然被火绒报告为病毒。

当前可确认：

```text
通用 MIR lowering 的 file I/O helper：会报毒
专用手写 X64 file I/O helper：也会报毒
```

因此，单纯恢复旧式手写 `read_file` / `write_file` X64 helper，或者把它包装成一个很窄的后端专门化优化，并不能解决当前误报。

本实验也确认：

1. 火绒的信任行为不是只依赖文件 SHA-256。
2. 现有证据高度支持：信任项以 EXE 的完整文件路径为主要键。不同内容和不同 SHA-256 覆盖到已信任路径时仍被放行；同一 SHA-256 复制到新路径后再次报警。
3. 只有已列入信任区的四个具体 EXE 路径上的“无弹窗”结果无效。项目目录本身并未被整体排除；同目录中的新完整路径仍可用于测试。
4. `log.db` 和 `applog.db` 没有立即出现记录，不能作为实时“未命中”的可靠证明；界面报警和实际执行结果更直接。

## 后续实验规则

以后所有火绒 A/B 实验必须遵守：

1. 编译可以在项目 worktree 中完成。
2. 待测 EXE 必须使用一个未列入信任区的全新完整路径；可以位于项目目录内，也可以复制到随机临时目录。
3. 最稳妥的做法是同时使用新的目录和新的文件名，避免继承任何路径相关信任。
4. 复制前后核对 SHA-256，确保需要做路径隔离时文件内容保持不变。
5. 每个新样本只执行一次，记录火绒界面结果、退出码、输出文件和文件是否仍存在。
6. 不以已加入信任区的四个具体 EXE 路径上的正常执行作为“未命中”证据。
7. 不以火绒 SQLite 日志没有即时记录作为“未命中”证据。
8. A/B 样本应使用不同的新完整路径，避免一次“信任”操作污染后续测试；一旦某个路径被加入信任区，该路径应退出实验样本池。

## 可继续验证的方向

后续若继续定位，应在中立路径中分别测试：

- 仅调用 `read_file` 的最小程序；
- 仅调用 `write_file` 的最小程序；
- 只导入但不调用 `CreateFileA` / `ReadFile` / `WriteFile` 的程序；
- 直接通过源码 `extern` 调用相同 WinAPI 的程序；
- 对 file I/O helper 做真实的 CFG、栈槽或调用序列优化后产生的版本；
- 拆分 `CreateFileA + ReadFile/WriteFile + CloseHandle` 组合，确定规则需要的最小机器码特征。

所有这些实验都必须使用未列入火绒信任区的新完整文件路径；不要求离开项目目录，但随机临时目录通常更容易保证路径隔离。

## 实验代码处置

专用 X64 helper 代码仅用于本次验证。实验完成后：

- 恢复 `bootstrap/mir_to_x64.py`；
- 删除临时的专用 X64 file runtime 模块；
- 不将该实现作为产品代码保留。
