# `str` and `u8[]` Layout Contract

This document records the current string/byte-buffer contract for Epic.

## Source-level distinction

`str` is a read-only, byte-oriented string. `u8[]` is a mutable byte buffer.
There is no implicit conversion or shared mutable view between them.

The string surface is:

```epic
len(s)
s[index]       # checked byte read, returns u8
s[start:end]   # checked copy
left == right
left != right
left + right   # allocates a new str
```

String indexing is read-only. Subscript assignment, compound subscript
assignment, `str += str`, ordering, and in-place string growth are rejected.

## Runtime layouts

`str` and `u8[]` deliberately have different runtime representations:

```text
str object: [len: i64][bytes...][NUL]
str value:  pointer to the object base

u8[] header: { data: &u8, len: i64, cap: i64 }
```

`len` does not include the trailing NUL. Inner NUL and non-UTF-8 bytes are
valid string contents. A dynamic non-empty string is one GC allocation of
`8 + len + 1` bytes. Empty dynamic results may reuse the static empty string.
String literals and `embed` values emit the whole inline object in `.rdata`.

## Explicit copy boundaries

Both conversions deep-copy logical bytes:

```epic
let text = str(buffer)   # u8[] -> independent str
let buffer = bytes(text) # str -> independent u8[]
```

Mutating either source after conversion cannot affect the result. There is no
copy-on-write or move conversion.

A mutable byte buffer can append a string directly:

```epic
buffer.extend(text)
```

`u8[].extend(str)` copies the string bytes directly into the destination and
does not allocate an intermediate `u8[]`. `str` itself has no `extend` method.

## C boundary

`cptr` accepts supported arrays and FFI-safe structs, but rejects `str`.
`cstr(s)` returns a borrowed pointer to the first byte (`s + 8`). The pointer is
NUL-terminated, but an inner NUL still truncates what a C string API observes.
The owner must remain reachable for the duration of the synchronous external
call. External mutation through this pointer violates the read-only string
contract.

## Text model

- `len(s)` counts bytes.
- `s[i]` returns one `u8` with bounds checking.
- `s[start:end]` returns an independent copied `str`.
- Equality compares byte contents.
- No UTF-8 validation, Unicode scalar indexing, grapheme semantics, collation,
  or normalization is defined.

Use `str` for read-only text or byte-string values. Use `u8[]` whenever mutation
or buffer growth is required.
