# `extend` copy experiments

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

## Shared `RtlMoveMemory` follow-up

A second experiment implemented the compact shared primitive suggested above.
All supported arrays use the same three-word `{ data, len, capacity }` header, so
the three helpers were replaced by one:

```text
__ep_slice_extend(dst, src, slot_size)
```

This follow-up initially passed `slot_size = 1` for `u8[]` and `8` for all other
supported arrays. The later natural-width slice experiment generalized this ABI
to 1/2/4/8-byte slots and reused the same block-copy strategy for every array
operation; see [`natural-width-slices-experiment.md`](natural-width-slices-experiment.md).
The helper snapshots the source, grows at most once with the existing capacity
policy, then copies the old destination and appended source with at most two
calls to `Kernel32.dll!RtlMoveMemory`. Empty-source and empty-destination paths
avoid zero-length calls. `RtlMoveMemory` also gives the helper overlap-safe block
copy semantics, while the source snapshot preserves `xs.extend(xs)` across an
allocation.

The same complete module suite and bootstrap fixed point passed. The self-host
A/B was:

| Metric | Existing `get` + `push` | Shared `RtlMoveMemory` | Delta |
| --- | ---: | ---: | ---: |
| wall time median | 1572.279 ms | 1576.316 ms | +4.037 ms (+0.26%) |
| internal time median | 1547 ms | 1547 ms | 0 ms |
| X64 items | 147699 | 147780 | +81 (+0.05%) |
| `.text` | 673939 B | 674386 B | +447 B (+0.07%) |
| `.data` | 91357 B | 91582 B | +225 B (+0.25%) |
| executable | 768000 B | 768512 B | +512 B (+0.07%) |

The new wall samples were 1576.3430, 1565.2218, and 1576.3161 ms. Their range
overlaps the existing samples, so performance remains unchanged under the
project's three-run rule. Unlike the first experiment, this version reduces the
runtime from three helpers to one and removes the per-element checked calls with
only a 512-byte executable increase. Retain the shared helper for the structural
simplification and better large-copy behavior.
