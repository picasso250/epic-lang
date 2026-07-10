# `str` to `u8[]` Alias Plan

This document records the current direction for Epic's temporary text model.

## Decision

For the current self-hosting phase, `u8[]` is the source of truth for text-like
byte buffers. `str` is not the future UTF-8 string design. It is a temporary
compatibility name for a byte-slice-backed text view.

A real UTF-8-aware `str` may be reintroduced later as a separate design. That
future feature should not constrain the current bootstrap core.

## Current invariant

`str` and `u8[]` use the same runtime header layout:

```text
{ data, len, cap }
```

Therefore these operations are representation-level identity conversions:

```epic
str(bytes_value)   # u8[] -> str view
bytes(str_value)   # str -> u8[] view
```

They do not allocate, copy, validate UTF-8, or make data immutable.

## Migration target

The staged target is:

1. Treat `str` as a compatibility alias over the `u8[]` layout.
2. Move public APIs toward `u8[]` as the explicit byte-buffer carrier.
3. Keep the spelling `str` only where it reduces churn in the self-hosted
   compiler during the transition.
4. Eventually remove the temporary `str` spelling from the bootstrap core.

## Non-goals

The current alias phase does **not** introduce:

- UTF-8 validation.
- Unicode scalar indexing.
- Grapheme cluster semantics.
- Immutable string literals.
- A high-level string library.
- Automatic formatting for structs or arbitrary arrays.

Those belong to a future string design.

## Compatibility blockers

`str` cannot be deleted in one commit because it is still used as a shared
contract in these places:

- String literals currently type as `str`.
- `argv` is currently `str[]`.
- `print`, `println`, `cstr`, `read_file(path)`, and
  `write_file(path, data)` use `str` for text/path arguments.
- The Python reference compiler has explicit `STR`, `ptr_str()`,
  `ptr_slice_str()`, `argv`, and `__ep_str_*` paths.
- The self-hosted compiler (`src/*.ep`) uses `str` for token kinds, names,
  type names, labels, paths, diagnostics, and generated assembly fragments.

## Recommended order

### Phase A: Documentation and stale contract cleanup

- Document `str` as a temporary `u8[]`-layout alias.
- Remove stale recommendations for `s[i]` and direct string-oriented helper use.
- Keep tests focused on explicit `bytes(s)[i]` and `u8[]` scanning.

### Phase B: Frontend alias compatibility

- Decide the exact sema rule for `str`/`u8[]` assign compatibility.
- Prefer explicit casts at public boundaries until codegen type lowering is ready
  to collapse `ptr<str>` and `ptr<_slice_u8>` safely.

### Phase C: Runtime/API convergence

- Move `print`/`println` implementation toward byte-slice output.
- Move path-like APIs toward `u8[]` where practical.
- Rename or retire formatting-shaped `str(x)` after a replacement name exists.

### Phase D: Self-hosted source migration

- Convert parser/lexer/sema/codegen internal byte scanning to operate primarily
  on `u8[]`.
- Keep a minimal compatibility layer only for literals and diagnostics.

## Open decisions

These require explicit design choices before code changes should become large:

1. Should `let s: str = some_u8_array` be implicit, or must it stay `str(bytes)`
   during the transition?
2. Should string literals eventually type as `u8[]` directly, or remain `str`
   until the final spelling removal?
3. What replaces `str(i64)` / `str(bool)` formatting once `str` no longer names a
   real string type?
