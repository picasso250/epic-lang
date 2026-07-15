# Contiguous store bounds-check experiment

This experiment tested whether AST-to-MIR should combine source sequences such as
`bytes_patch_u64_le` into one checked range followed by unchecked stores.

## Candidate lowering

The prototype recognized consecutive `AstSubscriptAssign` statements with:

- the same array variable;
- one shared index variable and constant deltas `0..N-1`;
- scalar RHS expressions proven not to call, mutate, or trap;
- no intervening statements.

It evaluated the array and starting index once, then checked the half-open range
`[start, start + count)` without forming the possibly overflowing end expression:

```text
start >= 0
len >= count
start <= len - count
```

On success it loaded the backing pointer once and emitted unchecked stores. This
preserves GC safety because the accepted RHS subset cannot allocate while the raw
backing pointer is live. Array compound assignments were deliberately excluded:
their RHS may resize the same array, so their second address lookup remains
semantically necessary.

## Local result

The generated code improvement was real. Counts below come from `objdump -dr` on
the converged compiler COFF object.

| Function | Variant | code bytes | x64 instructions | calls | `__ep_slice_at` calls |
|---|---|---:|---:|---:|---:|
| `bytes_patch_u32_bits_le` | baseline | 479 | 122 | 8 | 4 |
| `bytes_patch_u32_bits_le` | unified | 437 | 111 | 4 | 0 |
| `bytes_patch_u64_le` | baseline | 892 | 213 | 16 | 8 |
| `bytes_patch_u64_le` | unified | 562 | 142 | 4 | 0 |

The full module suite also passed with the prototype: 13 modules, 95 e2e cases,
examples, GC tests, and bootstrap fixed point.

## Self-host result

`benchmark_self_host.py` measured three equivalent compilations and reports the
median. The first prototype called the recognizer for every statement. A second
variant first gated it on two adjacent `AstSubscriptAssign` nodes.

| Variant | median wall | X64 items | `.text` bytes | `.rdata` bytes | `.data` bytes | exe bytes |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 1398.270 ms | 135,554 | 618,762 | 88,208 | 240 | 710,144 |
| unified | 1461.279 ms | 138,220 | 631,648 | 88,448 | 240 | 722,944 |
| gated unified | 1509.499 ms | 138,344 | 632,243 | 88,448 | 240 | 723,456 |

The ungated prototype was 4.51% slower than baseline. The gated variant was 7.95%
slower and also larger, so three samples already give a decisive result under the
project benchmark rules.

## Decision

Reject the AST block scanner and revert the implementation. It removes repeated
checks in the two endian patch helpers, but adds substantially more compiler code
and work to every compilation. The optimized helpers do not amortize that cost in
the self-host workload.

A future attempt should wait for one of these conditions:

- an existing MIR optimization framework can carry range facts at low marginal
  compiler cost;
- natural-width load/store combining is implemented as a small, narrowly matched
  MIR peephole;
- profiling shows contiguous byte patching dominates enough runtime to justify a
  dedicated lowering.

Until then, ordinary source subscripts continue to call `__ep_slice_at`
independently. No handwritten MIR replacement was retained.
