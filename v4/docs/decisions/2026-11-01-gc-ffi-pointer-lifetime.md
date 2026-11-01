# GC roots and FFI pointer lifetime

Status: **Accepted** (2026-11-01). Scope: **Epic v4 design and current implementation**.
This decision documents the intended contract; it introduces **no language,
compiler, or runtime change** and does not retroactively redefine v0-v3.

## Decision

- The garbage collector owns **managed object lifetime**, not arbitrary machine
  addresses. `ptr` is an **opaque, non-owning FFI value**: it does not carry an
  owner, automatically pin an object, register a GC root, or extend a managed
  allocation's lifetime. A `ptr` may also represent a Windows handle, null,
  integer-encoded API constant, callback address, or other non-heap value.
- Keep the existing **non-moving, exact-allocation-base** conservative GC.
  Roots are aligned words on the active owner-thread stack and the explicitly
  registered `_argv` root. An interior address (e.g. allocation base + 1)
  **does not keep** the underlying allocation alive by itself. The presence
  of a raw pointer is not proof of ownership or reachability.
- **Synchronous FFI borrowing** is supported without a new pin/root API:
  the caller retains an ordinary managed owner that is reachable throughout
  the foreign use, and does not relocate/replace its backing storage while the
  address is borrowed. The present compiler places locals in stack slots,
  scanned conservatively by the current GC. Future code generation or
  optimization must preserve this required liveness across synchronous FFI
  calls; merely writing an unused local must not become an untested guarantee.
- If foreign code **retains** an address after the call returns (including
  asynchronous/overlapped operations), the caller must provide a suitable
  longer-lived owner for the **entire actual use**, not just until the native
  function returns. This is an FFI contract, **not** a blanket memory-safety
  guarantee for arbitrary foreign calls. The GC cannot see roots stored only
  inside Windows or other foreign code.
- No user-defined globals, public managed-root handle, `pin`, or GC lifetime
  annotation are introduced for this case. Epic v4 **does not provide user
  global variables**, and the collector does **not** scan arbitrary static
  data. A hypothetical future global binding would need an explicit GC-root
  design before it could be recommended as a lifetime solution. Long-lived
  owners in active Epic stack frames can cover suitable synchronous uses.

## Example: transient synchronous buffer

```epic
extern "kernel32.dll" fun GetCurrentDirectoryA(size: u32, buffer: ptr): u32

fun main(): void {
    let owner = new u8[260]
    let result = GetCurrentDirectoryA(u32(len(owner)), ptr(owner))
    # Keep owner alive while the native function uses the backing buffer;
    # do not push/extend/resize owner during the borrow.
    if result == u32(0) {
        exit(1)
    }
}
```

This shows the **borrow/lifetime pattern**, not a complete wrapper for Windows
buffer sizing or failure modes. `ptr(owner)` borrows the array's backing data;
`owner` is the managed array header that references it. For `cstr(text)`, the
returned `ptr` itself denotes a newly allocated C-string buffer; users must
not assume that an **interior** pointer derived from it retains that buffer.

## Why not make every interior pointer a GC root?

- Current marking uses allocation bases and compact small-object slot maps;
  accepting arbitrary interior addresses would change marking logic for both
  small and large allocations, with added cost and conservative false retention.
- It would **not** solve the long-lived native-pointer case: roots kept only
  by the operating system remain invisible to the collector.
- The simpler boundary is intentional: managed references govern lifetime;
  raw FFI values do not. This should not be reported as an accidental GC bug
  merely because a program retains only an interior raw address.

## Evidence, limitations, and reopening criteria

- In a v4 Windows x64 reproduction, retaining only `cstr("hello gc") + 1`
  across allocation pressure changed `lstrlenA` from 7 to 0; retaining the
  allocation base in an active stack local preserved the observed length (7).
  Integer round-tripping through `ptr(u64(base) + 1)` showed the same hazard;
  disabling pointer arithmetic alone is **not** a memory-safety proof.
- A synchronous owner-thread Windows callback with GC allocation pressure
  also preserved a buffer whose base remained live in its caller's stack frame.
  These are observations, not a proof of safe arbitrary FFI behavior.
- The v4 FFI contract remains restricted to owner-thread synchronous callback
  reentry. Native code retaining borrowed storage or using foreign threads is
  not automatically made safe by this decision. Array growth can replace its
  backing allocation even though the GC itself does not move objects.
- Reconsider adding managed handles, pinned buffers, global-root support, or
  interior-root recognition **only if** concrete supported use cases cannot be
  expressed safely under this contract, or optimization invalidates the
  synchronous owner-liveness requirement. Such a change needs tests for both
  small and large objects and across GC/FFI reentry.
- Removing `ptr + integer` is a **separate proposed language simplification**,
  **not implemented by this decision**. The v4 syntax still supports it today.

## Related specifications

- [GC implementation and exact-base scanning](../gc.md)
- [FFI, pointers, arrays, and callback restrictions](../language.md)
