Task: Fix the small lexer bootstrap test failure caused by subprocess newline translation.

Current branch has a WIP baseline commit. Make only this narrow test-harness change.

Problem:
- `python test_lexer_bootstrap.py` fails only on examples/v1_str_helpers.ep.
- Difference is a string token containing real CR followed by LF: Python expected includes `\r`, but `bootstrap_lexer_dump` captures lexer.exe stdout with `text=True`, so Python universal newline conversion normalizes `\r\n` to `\n` and loses the CR embedded in token text.
- Binary capture confirmed lexer.exe stdout contains the CR byte, so lexer behavior is OK.

Allowed file:
- test_lexer_bootstrap.py only.

Required change:
- In bootstrap_lexer_dump, do not use `text=True` / universal newline mode.
- Capture stdout/stderr as bytes, then decode with UTF-8 using errors="replace" without newline translation.
- Preserve existing error reporting behavior as much as practical.
- Do not edit lexers, examples, parser, docs, or other tests.

Validation:
- Run `python test_lexer_bootstrap.py` and it should pass all files.
- Run `python test_parser_bootstrap.py` to ensure no regression.
- Run `python runtests.py --linker py` to ensure no regression.
