# Register-memory operand folding experiment

This experiment was run on `codex/stack-traffic-experiments` from
`dev@22a96a1`. It tested folding a stack-backed right operand into an x64
memory operand:

```asm
mov rcx, [rbp-slot]
add rax, rcx
```

became:

```asm
add rax, [rbp-slot]
```

The tested instruction set was `add/sub/and/or/xor/cmp/imul`. The machine
encoder gained the corresponding `r64, m64` forms, and MIR-to-X64 selected
them when the right operand already had a value slot. Constants retained the
existing immediate path; address slots and non-value operands retained the
register fallback.

Exact bytes were checked independently against GNU assembler and covered all
seven forms. Targeted machine and MIR-to-X64 tests passed, as did bootstrap
fixed point.

## Three-sample benchmark

Both variants used the same v0 seed, source inputs, host, parameters, and
output location. The baseline and variant were measured with
`benchmark_self_host.py --refresh`.

| Metric | Baseline | Reg-memory folding | Change |
|---|---:|---:|---:|
| Wall samples | 1750.798 / 1701.923 / 1675.479 ms | 1713.603 / 1677.654 / 1685.558 ms | overlapping |
| Wall median | 1701.922 ms | 1685.558 ms | -16.364 ms, -0.96% |
| Internal median | 1687 ms | 1671 ms | -16 ms, -0.95% |
| X64 items | 157,479 | 157,900 | +421, +0.27% |
| `.text` bytes | 726,098 B | 729,385 B | +3,287 B, +0.45% |
| `.data` bytes | 81,840 B | 81,893 B | +53 B, +0.06% |
| Final exe | 810,496 B | 814,080 B | +3,584 B, +0.44% |

The wall samples do not establish a stable improvement. Deterministic item
count and code-size metrics regress.

## Disassembly audit

The converged compilers show that folding did fire, but the implementation
cost was larger than the generated-code saving:

| Pattern | Baseline | Variant | Change |
|---|---:|---:|---:|
| Total instructions | 147,095 | 147,446 | +351 |
| `rbp` stack `mov` | 69,346 | 69,216 | -130 |
| Stack loads | 35,358 | 34,994 | -364 |
| Stack stores | 33,988 | 34,222 | +234 |
| `rcx` stack loads | 13,249 | 12,725 | -524 |
| Folded reg-memory operations | 0 | 597 | +597 |

Folded operations by opcode:

| Opcode | Hits |
|---|---:|
| `cmp` | 426 |
| `add` | 97 |
| `sub` | 26 |
| `imul` | 18 |
| `or` | 17 |
| `and` | 11 |
| `xor` | 2 |

Four new self-hosted helper functions plus lowering selection increased the
compiler workload enough to outweigh 597 folded operations. Although explicit
loads fell, new implementation code added more stores and total instructions.

## Conclusion

Rejected and removed. The experiment failed the predeclared requirement that
X64 item and `.text` size improve without a stable wall regression. Per the
serial experiment stop rule, the planned RAX home-store elision, single-`r10`
cache, and block-local linear scan experiments were not attempted.

The opcode distribution suggests that a much narrower `cmp r64, m64` design
could have a better implementation-cost ratio, but this experiment did not
test that follow-up.
