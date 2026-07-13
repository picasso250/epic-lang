# Small runtime helper MIR experiment

This experiment moves `runtime/array.ep` and `runtime/panic.ep` into
`runtime/mir/helpers.ir`. These helpers are small and stable, while keeping them as Epic
sources makes every compilation send them through lexing, parsing, sema, and AST-to-MIR.

The comparison uses the same v0 seed, host, compiler workload, arguments, output position,
and three-run benchmark contract. The baseline is `dev@0ade9e6`.

| Metric | Epic source | MIR bundle | Change |
|---|---:|---:|---:|
| wall samples | 1665.479 / 1724.657 / 1677.873 ms | 1579.080 / 1561.661 / 1572.279 ms | all experiment samples lower |
| wall median | 1677.873 ms | 1572.279 ms | -105.594 ms, -6.29% |
| internal median | 1672 ms | 1547 ms | -125 ms, -7.48% |
| X64 items | 147,804 | 147,699 | -105, -0.07% |
| `.text` bytes | 674,367 | 673,939 | -428, -0.06% |
| `.data` bytes | 89,800 | 91,357 | +1,557, +1.73% |
| exe size | 766,976 B | 768,000 B | +1,024 B, +0.13% |

The MIR text occupies more embedded data than the compact Epic sources, but it removes a
stable frontend workload and slightly reduces generated code. The 6.29% wall improvement is
clear across the three samples, while the final executable grows by one 1 KiB allocation
step. The experiment is retained in favor of compilation time.
