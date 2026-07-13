# Natural-width generic slice runtime experiment

Date: 2026-07-13

## Question

Can Epic delete the typed slice layouts and helper families while giving scalar
arrays their natural storage widths, without breaking language semantics,
garbage-collector reachability, bootstrap fixed point, or self-host performance?

The experiment keeps the existing 24-byte `{ data, len, cap }` header. `len` and
`cap` count elements. Lowering supplies a byte `slot_size` of 1 for `u8`/`bool`,
2 for `i16`/`u16`, 4 for `i32`/`u32`, and 8 for `i64`/`u64` and references.
Struct, union, and `str` arrays remain arrays of references; aggregate values are
not stored inline.

## Implementation

All array metadata is registered as one internal `_slice` layout. The runtime
surface is:

```text
__ep_slice_new(len, slot_size)
__ep_slice_reserve(slice, minimum_capacity, slot_size)
__ep_slice_at(slice, index, slot_size) -> ptr
__ep_slice_push_slot(slice, slot_size) -> ptr
__ep_slice_pop_slot(slice, slot_size) -> ptr
__ep_slice_extend(dst, src, slot_size)
__ep_slice_copy_range(src, start, end, slot_size) -> ptr
```

`reserve` owns the exact reallocation path and uses the private `0 -> 4 ->
double` capacity policy. `reserve`, `extend`, and `copy_range` use
`Kernel32!RtlMoveMemory`. Indexing, assignment, push, and pop obtain a slot
address, after which lowering emits a statically typed narrow load or store.

Array compound assignment evaluates the base and index once, reads the old
value, evaluates the RHS, and then resolves the slot address again. An RHS that
grows the same array therefore cannot leave the final store pointing at retired
backing storage. `extend` snapshots source data and length before reserve, so
`xs.extend(xs)` appends the elements visible when the call began.

All `T[]` types now support copied half-open slices and return `T[]`. Reference
arrays are shallow-copied. `str[start:end]` remains on the independent string
helper and preserves its NUL-termination contract.

## Verification

The following acceptance commands passed:

```text
python tests/run.py
python tests/examples/run.py
python test_bootstrap_fixed_point.py
```

The module runner passed all 13 modules, 90 end-to-end cases, and the GC stress
and tiny-heap runs. Dedicated coverage exercises zero initialization, literals,
index reads/writes, push/pop, compound assignment, growth, truncation and signed
or unsigned boundary values for `bool`, `u8`, `i16`, `u16`, `i32`, `u32`, `i64`,
and `u64`. It also covers empty/full/subrange copies, empty extend, bulk extend,
self-extend, out-of-bounds panic, shallow `str`/struct/union reference copies,
GC pressure, and a compound-assignment RHS that relocates its own array.

## Self-host A/B

The existing `e873798` samples and the new samples use the same seed, canonical
compiler workload, arguments, and output-path conditions. Each result is three
equivalent runs from `benchmark_self_host.py --refresh`.

| Metric | `e873798` typed slices | Natural-width generic slices | Delta |
| --- | ---: | ---: | ---: |
| wall time median | 1572.279 ms | 1573.270 ms | +0.991 ms (+0.06%) |
| internal time median | 1547 ms | 1562 ms | +15 ms (+0.97%) |
| X64 items | 147699 | 154153 | +6454 (+4.37%) |
| `.text` | 673939 B | 710549 B | +36610 B (+5.43%) |
| `.data` | 91357 B | 80553 B | -10804 B (-11.83%) |
| executable | 768000 B | 794112 B | +26112 B (+3.40%) |

Wall samples were:

- typed baseline: 1579.0804, 1561.6612, 1572.2789 ms;
- natural-width generic: 1573.2699, 1571.8282, 1577.0364 ms.

The ranges overlap and the wall median changes by only 0.06%, so runtime
performance is not significantly changed under the project's three-run rule.
Natural widths reduce embedded `.data`, while resolving scalar slots through the
shared address ABI increases generated instructions, `.text`, and final exe
size. The executable increase is 3.40%.

## Decision

Accept the experiment as a refactor. No semantic, GC, example, or fixed-point
gate failed, and the performance rejection rule (all samples slower with a wall
median regression above 5%) does not apply. The implementation deletes the typed
helper families and per-element-type layout registrations, replacing them with
one layout and seven generic operations. The measured code-size cost is retained
under the project's explicit preference for clarity when performance is not
significantly worse.
