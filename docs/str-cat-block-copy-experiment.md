# `str + str` block-copy experiment

Date: 2026-07-15

## Question

`__ep_str_cat` previously built a temporary `u8[]`, appended each input byte
through checked indexing and capacity-aware `push`, then converted that slice
to a second allocation containing the final inline string. The experiment asks
whether a dedicated MIR helper using `Kernel32.dll!RtlMoveMemory` improves the
self-host workload enough to justify moving this runtime operation out of Epic
source.

## Change

The MIR helper now:

1. loads both string lengths and calculates the final length;
2. returns the shared empty string when both inputs are empty;
3. allocates exactly one `[len:i64][bytes...][NUL]` inline string;
4. copies each non-empty input with one `RtlMoveMemory` call;
5. writes the trailing NUL and returns the new string.

This removes the temporary slice header, its growable backing allocation, the
per-byte checked calls, and the final slice-to-string copy. It preserves the
existing empty-string result and the externally observable string layout.

## Correctness

The complete module suite passed, including concatenation with an empty side
and the NUL-termination test. The compiler also reached its fixed point from
the v0 seed.

## Self-host A/B

Both variants compiled the same canonical compiler workload from the same
seed, with the same arguments and output location. Each result is the median
of three equivalent runs from `benchmark_self_host.py`.

| Metric | Byte loops + temporary slice | Direct `RtlMoveMemory` | Delta |
| --- | ---: | ---: | ---: |
| wall time median | 1616.405 ms | 1450.711 ms | -165.694 ms (-10.25%) |
| internal time median | 1609 ms | 1437 ms | -172 ms (-10.69%) |
| X64 items | 135851 | 135831 | -20 (-0.01%) |
| `.text` | 620277 B | 620164 B | -113 B (-0.02%) |
| `.rdata` | 85712 B | 87160 B | +1448 B (+1.69%) |
| `.data` | 240 B | 240 B | 0 B |
| executable | 708608 B | 710144 B | +1536 B (+0.22%) |

Wall samples were:

- byte loops: 1633.6535, 1616.4052, 1593.6598 ms;
- direct block copy: 1470.8407, 1445.7694, 1450.7112 ms.

The sample ranges do not overlap. During fixed-point compilation the observed
GC collection count also fell from 10 to 9, consistent with removing temporary
allocations.

## Decision

Retain the MIR implementation. The self-host improvement is large and stable,
while the executable-size increase is 0.22%. The extra `.rdata` is embedded
handwritten MIR text; generated machine code is slightly smaller.
