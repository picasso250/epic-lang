# Direct-copy `extend` experiment

Date: 2026-07-13

## Question

The MIR implementations of `u8[]`, word-array, and pointer-array `extend` called
the corresponding checked `get` and capacity-checking `push` helper once per
element. The compiler itself has more than twenty `extend` call sites, including
AST/MIR list merging and byte-buffer construction, so removing those calls was
plausibly useful.

The experiment replaced all three implementations with this sequence:

1. snapshot the source length and data pointer, preserving `xs.extend(xs)`;
2. calculate the final length and grow capacity at most once, using the existing
   zero-to-four and doubling policy;
3. copy the old destination into the grown buffer;
4. directly copy the source into the appended range with an MIR loop;
5. publish the final length.

No `memcpy`, new import, or capacity-policy change was introduced.

## Correctness

The complete module test suite passed, including the existing byte, integer,
pointer, and self-extend end-to-end cases. The bootstrap compiler also reached
its fixed point.

## Self-host A/B

Both variants compiled the same canonical compiler workload from the same seed,
with the same arguments and output path. Each result is the median of three
equivalent runs from `benchmark_self_host.py`.

| Metric | Existing `get` + `push` | Direct copy | Delta |
| --- | ---: | ---: | ---: |
| wall time median | 1572.279 ms | 1563.291 ms | -8.988 ms (-0.57%) |
| internal time median | 1547 ms | 1547 ms | 0 ms |
| X64 items | 147699 | 148000 | +301 (+0.20%) |
| `.text` | 673939 B | 675217 B | +1278 B (+0.19%) |
| `.data` | 91357 B | 97252 B | +5895 B (+6.45%) |
| executable | 768000 B | 775168 B | +7168 B (+0.93%) |

Wall samples were:

- existing: 1579.0804, 1561.6612, 1572.2789 ms;
- direct copy: 1657.1681, 1557.0997, 1563.2909 ms.

The sample ranges overlap substantially, so the measured time change is not
significant under the project's three-run rule. The size regression is stable.
Most of the `.data` increase comes from embedding three much larger MIR state
machines as runtime text.

## Decision

Reject the change and retain the compact `get` + `push` implementations. Direct
copy removes per-element calls locally, but this self-host workload did not show
a stable end-to-end speedup that pays for the additional MIR and executable
size. Revisit only with a workload that demonstrates large-array `extend` as a
measured bottleneck, or after adding a compact shared reserve/copy primitive.
