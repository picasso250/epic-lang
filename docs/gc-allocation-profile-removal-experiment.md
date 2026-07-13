# GC allocation-profile removal experiment

This local experiment deletes the permanent allocation-size profiler after its data has
already established the 8/16/24/32-byte slab classes and the >64-byte tail. The profile is
not required for allocation, marking, sweeping, or threshold selection.

## Deleted code

- 15 allocation counter globals;
- 16 profile-output string globals;
- `__ep_gc_record_alloc_profile` (96 lines);
- `__ep_gc_print_alloc_profile` (59 lines);
- two calls from the small and large allocation paths;
- the runtime-end profile print call.

The patch deletes 222 physical lines from `runtime/mir/gc.ir` and adds no replacement code.
Per-collection `gc stw` diagnostics remain.

## Validation

- bootstrap fixed point reached;
- all existing GC behavior remains represented by allocation, mark, sweep, threshold, and
  stress tests; only diagnostic stderr output is removed.

## Three-sample benchmark

| Metric | Embedded-runtime baseline | Profile removed | Delta |
|---|---:|---:|---:|
| median wall | 1700.052 ms | 1608.754 ms | -91.298 ms (-5.37%) |
| median internal | 1687 ms | 1594 ms | -93 ms (-5.51%) |
| median GC STW total | 515 ms | 532 ms | +17 ms (+3.30%) |
| X64 items | 149,909 | 149,400 | -509 |
| `.text` | 683,196 B | 681,184 B | -2,012 B |
| `.data` | 98,400 B | 90,243 B | -8,157 B |
| executable | 784,384 B | 774,144 B | -10,240 B |

The variant wall samples were 1608.754, 1612.875, and 1593.561 ms. The improvement is much
larger than their spread.

## Conclusion

This change should replace the permanent profiler. It removes roughly 15% of `gc.ir`,
shrinks the self-hosted compiler, and improves total compile time despite a small
layout-sensitive increase in measured GC STW. Future allocation-shape studies
should use a temporary experiment branch or an explicitly enabled diagnostic build rather
than counters in every production allocation.
