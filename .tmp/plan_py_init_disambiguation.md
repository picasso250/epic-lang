Task: Step 3. Remove Python parser uppercase-name heuristic for brace initializers.

Current branch is clean and has WIP baseline commits. Make a narrow change.

Goal:
- Python parser should classify brace initializers by grammar/token shape, not by identifier capitalization.
- This aligns with docs and current Epic parser direction.

Allowed files:
- bootstrap/parser.py
- examples/*.ep only for one tiny coverage example if useful
- tests only if required by the new example or dump support

Do not edit src/*.ep unless absolutely necessary. Current src/parser.ep already uses token shape rather than uppercase spelling for initializer recognition.
Do not edit codegen unless the new example reveals a real Python reference compiler issue.

Current bug:
- bootstrap/parser.py uses `name[:1].isupper()` before parsing `Name { ... }` and `Name.Variant { ... }`.

Required parser behavior:
- Add/adjust a small lookahead helper for named-field initializer braces, roughly:
  - current token is LBRACE and next tokens are `ID COLON`, allowing whitespace/newline only if the existing token stream represents them explicitly. Keep it simple and consistent with current parser token model.
- For `ID { field: value }`, parse StructInitNode regardless of ID capitalization if the lookahead says the brace starts named fields.
- For `ID.DOT.ID { field: value }`, parse StructInitNode/variant init regardless of ID capitalization, but only when the left side is a simple type-name VarNode. Use the actual VarNode name as the type name, not a stale outer variable if the code was chained.
- Do not add empty init support in this step unless it is already trivial and safe. Existing examples use named fields.
- Keep existing AST shape for Python StructInitNode for now; this step is only disambiguation/capitalization, not dump-shape alignment.

Coverage:
- Add one tiny example with a lowercase struct type initialized with named fields, e.g. `struct point { x: i64 }` and `let p = point { x: 7 }`, with EXIT annotation.
- Name it consistently under examples/, e.g. `v2_lowercase_struct_init.ep`.

Validation:
- Run `python test_lexer_bootstrap.py` and it should pass.
- Run `python test_parser_bootstrap.py`; it may still have existing dump-shape failures, but the new lowercase example should pass.
- Run `python runtests.py --linker py`; all examples including the new one should pass.
