Task: Fix v1_str_helpers parser bootstrap dump failure caused by subprocess newline translation.

Current branch is clean enough for a narrow commit. Make only this test-harness change.

Problem:
- `python test_parser_bootstrap.py` fails on examples/v1_str_helpers.ep because the dump contains a String node with real CR followed by LF.
- `bootstrap_parser_dump` captures parser.exe stdout with `text=True`, so Python universal newline conversion normalizes `\r\n` to `\n` and loses embedded CR in the dump text.
- This is analogous to the already-fixed lexer bootstrap test harness.

Allowed file:
- test_parser_bootstrap.py only.

Required change:
- In bootstrap_parser_dump, remove `text=True` and capture bytes.
- Decode `result.stdout` and `result.stderr` manually with UTF-8 and errors="replace" without newline translation.
- Preserve existing error reporting behavior.
- Do not edit parser, lexer, examples, docs, or codegen.

Optional:
- Leave ensure_bootstrap_parser as text=True because it only compiles parser and does not compare dump bytes.

Validation:
- Run `python test_parser_bootstrap.py`; v1_str_helpers should now pass and total should improve by one.
- Run `python test_lexer_bootstrap.py`.
- Run `python runtests.py --linker py`.
