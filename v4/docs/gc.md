# Garbage collector

The collector described here was introduced in Epic v2. Later generations
inherit this baseline unless a generation-specific section below documents a
change. It is a single-threaded, conservative, non-moving mark-and-sweep
collector and an internal runtime facility: the language has no manual `gc()`
builtin, finalizers, weak references, or collection diagnostics.

## Allocation

Every managed allocation passes through `__ep_alloc`. Payloads carry no object
header. Requests up to 32 bytes use 8/16/24/32-byte slab classes; larger
payloads are allocated individually from the Win32 process heap and recorded in
parallel address/size side tables.

The small allocator reserves a 1 GiB virtual address arena and divides it into
64 KiB pages. Reservation consumes address space without committing the whole
arena. Pages are committed on demand, belong to one size class, and use bump
allocation plus an intrusive free list. Allocation and mark byte maps remain
outside the managed heap. Exhausted active pages search all committed pages for
reusable slots before committing more memory.

The initial collection threshold is 8 MiB of managed payload. After a
collection it becomes `max(8 MiB, 2 * live_bytes)`. A zero-sized language
allocation still receives a distinct physical address and contributes eight
bytes of pressure.

## Collection

At program entry the runtime records the high end of the active stack. A
collection conservatively scans aligned words from the current RSP to that
boundary, plus the explicit `_argv` global root. Candidate words retain an
object only when they equal its exact allocation base; interior addresses are
not roots. Monotonic minimum and maximum managed addresses reject candidates
outside the heap range before probing the allocation hash table.

The collector builds temporary raw metadata for the large-object address hash,
large mark bytes, and one iterative work stack shared by both allocation paths.
Marked payloads are scanned in aligned eight-byte words, so references stored
inside arrays and nested product values are followed without type descriptors.
Sweep frees unmarked large payloads with `HeapFree` and compacts their side
tables. Small sweep clears dead allocation bytes, rebuilds page free lists, and
selects reusable active pages. Objects never move.

The runtime has no generational policy. Raw collector metadata is outside the
managed heap and is never scanned. The runtime supports one Epic thread; it
does not enumerate roots from other or externally created threads. A Windows
callback may allocate only when it synchronously reenters on that owner thread,
whose active stack remains within the original `_gc_stack_high` boundary.

## Verification

`bootstrap_fixed_point.py` makes generation 1 compile generation 2, exercising
the collector in the compiler workload, and requires byte-identical output.
The `tests/gc` suite creates a retained stack/heap object graph amid more than
60 MiB of temporary allocations, separately exercises all four slab classes,
and checks retention plus a bounded peak working set.

## Generation history

### Epic v2

Epic v2 introduced the collector described above: managed allocation through
`__ep_alloc`, conservative exact-base stack scanning, non-moving mark-and-sweep,
8/16/24/32-byte slab classes, and the adaptive 8 MiB minimum threshold.
