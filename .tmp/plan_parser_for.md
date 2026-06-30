Task: make one narrow parser fix.

Context:
- Current repo root has src/parser.ep as the active Epic parser.
- Python parser is the oracle for test_parser_bootstrap.py.
- For-range parsing currently lowers `for i in a:b { ... }` during parsing into a Block with temporary lets and a While node.
- This is too early. Parser should preserve a For AST node like Python's ForRangeNode.

Required change:
- Edit only src/parser.ep unless absolutely necessary.
- Change parse_for_stmt so it returns an AstNode with:
  - kind = "For"
  - name = loop variable token text
  - start = parsed start expression
  - end = parsed end expression
  - body = parsed block
- Keep loop_depth validation behavior around parse_block.
- Remove/stop using the lowering logic in parse_for_stmt.
- Prefer not to touch dump_node unless needed; the generic dump already prints kind/name/body/start/end in the same order Python expects for For.
- Do not change Python files, tests, codegen, examples, docs, or unrelated parser behavior.

Validation target after edit:
- `python test_parser_bootstrap.py` should reduce failures: v1_for_in_range and the for part of v1_break_continue should improve.
- It does not need to be all green.
