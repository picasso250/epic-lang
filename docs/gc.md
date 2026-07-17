# Garbage collector

Epic v2 uses a single-threaded, conservative, non-moving mark-and-sweep
collector. It is an internal runtime facility: the language has no manual
`gc()` builtin, finalizers, weak references, or collection diagnostics.

## Allocation

Every managed allocation passes through `__ep_alloc`. Payloads are zeroed and
allocated individually from the Win32 process heap. They carry no object
header; persistent side tables record each allocation's exact base address and
requested size.

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

The collector builds temporary raw metadata for an address hash table, mark
bytes, and an iterative work stack. Marked payloads are scanned in aligned
eight-byte words, so references stored inside arrays and nested product values
are followed without type descriptors. Sweep frees unmarked payloads with
`HeapFree` and compacts the persistent side tables in place. Objects never
move.

This first implementation deliberately has no small-object slab or generational
policy. Raw collector metadata is outside the managed heap and is never
scanned. The runtime supports one Epic thread; it does not enumerate roots from
other or externally created threads.

## Verification

`bootstrap_fixed_point.py` makes generation 1 compile generation 2, exercising
the collector in the compiler workload, and requires byte-identical output.
The `tests/gc` stress suite also creates a retained stack/heap object graph amid
more than 60 MiB of temporary allocations and checks both retention and a
bounded peak working set.
