Task: Step 2. Implement mandatory colon syntax for match cases.

Baseline has been staged with `git add -A`; make only the changes needed for match case colon syntax so unstaged diff shows your work.

Goal syntax:
- Basic match case: `1: { ... }`
- String/bool cases: `"x": { ... }`, `true: { ... }`
- Else case: `else: { ... }`
- ADT payload pattern: `Expr.IntLit { value: n }: { ... }`
- ADT no-payload pattern: `Expr.Empty: { ... }` or if existing grammar uses empty payload, support `Expr.Empty {}: { ... }` only if easy and consistent. Prefer the clean no-payload form if examples can use it.

Old syntax to remove from examples/tests:
- `1 { ... }`
- `else { ... }`
- `Expr.IntLit { value: n } { ... }`

Allowed files:
- bootstrap/parser.py
- src/parser.ep
- examples/*.ep only as needed for match examples
- tests that embed expected parser dumps or match syntax if needed

Do not edit docs in this step; Step 1 already documented the rule.
Do not edit codegen unless parser AST shape forces it. Prefer preserving existing MatchNode/MatchCase AST shape so codegen remains unchanged.

Python parser requirements:
- In parse_match_stmt, after parsing a case pattern and optional ADT payload bindings, require COLON before parse_block().
- For else, require `else` then COLON then parse_block().
- Remove reliance on the old double-brace `pattern { payload } { body }` form.
- Keep MatchCase AST shape unchanged.

Epic parser requirements:
- In src/parser.ep parse_match_stmt, after parsing a case pattern and optional ADT payload bindings, require COLON before parse_block().
- For else, require COLON before parse_block().
- Remove/stop using next_brace_is_payload_pattern if no longer needed.
- Keep MatchCase AST shape unchanged if possible.

Examples:
- Update v2_match_basic.ep and v2_match_adt.ep to colon syntax.
- Search all examples for old match case syntax and update any other match cases.

Validation:
- Run `python test_lexer_bootstrap.py`.
- Run `python test_parser_bootstrap.py`; it does not need to be all green, but match-related failures should improve or remain only dump-order issues.
- Run `python runtests.py --linker py` and keep 65/65 passing.
