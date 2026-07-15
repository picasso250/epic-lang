# File count little-endian decode experiment

Date: 2026-07-15

## Question

`__ep_file_u32_le` decoded the four-byte result written by `ReadFile` and
`WriteFile` using multiplication and addition. This experiment replaced those
operations with shifts and bitwise OR, which directly express little-endian
field assembly.

## Self-host A/B

Both variants compiled the same canonical compiler workload from the same seed
with the same arguments and output location. Each result is the median of three
equivalent runs from `benchmark_self_host.py` measured in the same session.

| Metric | Multiply + add | Shift + OR | Delta |
| --- | ---: | ---: | ---: |
| wall time median | 1417.403 ms | 1401.452 ms | -15.951 ms (-1.13%) |
| internal time median | 1406 ms | 1391 ms | -15 ms (-1.07%) |
| X64 items | 135831 | 135831 | 0 |
| `.text` | 620164 B | 620155 B | -9 B |
| `.rdata` | 87152 B | 87152 B | 0 B |
| `.data` | 240 B | 240 B | 0 B |
| executable | 710144 B | 710144 B | 0 B |

Wall samples were:

- multiply + add: 1426.6710, 1415.3927, 1417.4027 ms;
- shift + OR: 1450.0095, 1396.4236, 1401.4522 ms.

The ranges overlap, so the measured time change is not significant under the
project's three-run rule.

## Decision

Retain shift + OR because it states the byte-layout operation directly and
reduces `.text` by 9 bytes without increasing any reported size metric. Do not
claim a performance improvement.

This decision was later superseded when file I/O moved to MIR stack `u32`
output slots and `__ep_file_u32_le` was deleted.
