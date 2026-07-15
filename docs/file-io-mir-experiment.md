# File I/O MIR output-slot experiment

Date: 2026-07-15

## Question

The Epic implementations of `read_file` and `write_file` allocated a four-byte
`u8[]` for the `DWORD*` output of `ReadFile` and `WriteFile`, then decoded that
count with four checked byte reads. The experiment moves both helpers to MIR
and uses `alloca u32` plus `load u32` instead.

## Change

- `write_file` passes a stack `u32` slot to `WriteFile` and loads it once.
- `read_file` does the same for `ReadFile`, then stores the count directly into
  the result slice length instead of repeatedly calling `pop` after a short read.
- The obsolete `__ep_file_u32_le` and `runtime/file.ep` are deleted.
- File I/O imports and helper bodies now live with the other handwritten MIR
  runtime helpers.

The stack addresses are borrowed only for synchronous WinAPI calls. MIR `ptr`
is untyped; the `u32` access type on `store` and `load` selects the four-byte
memory operation and zero-extension behavior.

## Correctness

All 13 test modules passed, including 95 end-to-end cases and the dedicated
binary/empty file tests. Bootstrap reached its fixed point from the v0 seed.

## Self-host A/B

Both variants compiled the same canonical compiler workload from the same seed
with the same arguments and output location. Each result is the median of three
equivalent runs from `benchmark_self_host.py`.

| Metric | Epic byte-slot helpers | MIR `u32` slots | Delta |
| --- | ---: | ---: | ---: |
| wall time median | 1401.452 ms | 1415.803 ms | +14.351 ms (+1.02%) |
| internal time median | 1391 ms | 1391 ms | 0 ms |
| X64 items | 135831 | 135554 | -277 (-0.20%) |
| `.text` | 620155 B | 618762 B | -1393 B (-0.22%) |
| `.rdata` | 87152 B | 88208 B | +1056 B (+1.21%) |
| `.data` | 240 B | 240 B | 0 B |
| executable | 710144 B | 710144 B | 0 B |

Wall samples were:

- Epic byte slots: 1450.0095, 1396.4236, 1401.4522 ms;
- MIR `u32` slots: 1418.9433, 1404.9211, 1415.8033 ms.

The sample ranges overlap, so the measured time change is not significant under
the project's three-run rule. The larger `.rdata` is embedded handwritten MIR
text; generated `.text` is smaller and final executable size is unchanged.

## Decision

Retain the MIR helpers. They delete two temporary GC allocations per file I/O
operation, replace hundreds of dynamic instructions with one typed load, remove
the partial-read pop loop, and reduce generated machine code without increasing
the executable. Do not claim an end-to-end timing improvement.
