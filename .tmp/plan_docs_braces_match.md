Task: Step 1 docs only. Document the brace disambiguation and match case colon rule.

Baseline has been staged with `git add -A`; make only docs changes so unstaged diff shows your work.

Allowed files:
- docs/design.md
- docs/impl.md

Do not edit src, bootstrap, examples, tests, todo, AGENTS, or any other files.

Design decision to document:
1. `{ ... }` is not classified by identifier spelling/capitalization.
2. `{ ... }` is a block/body only where grammar explicitly expects a block/body:
   - fun body
   - if then block
   - else block
   - while block
   - for block
   - struct body
   - type body
   - match body
   - match case body after colon
3. In expression/pattern position, postfix `{ ... }` is an initializer or pattern-payload candidate, not a block.
4. Parser may create init/pattern candidate AST nodes from token shape and context, but legality belongs to semantic/codegen checks:
   - target must be a real struct/type/ADT variant
   - fields/payload bindings must exist and be valid
   - types must match
5. Match cases must use colon syntax to separate pattern from body:
   - `pattern: { ... }`
   - `else: { ... }`
   - ADT pattern example: `Expr.IntLit { value: n }: { ... }`
6. Rationale: this removes the old double-brace ambiguity like `Expr.IntLit { value: n } { ... }` and eliminates uppercase-name heuristics.

Please update docs/design.md as the language rule, and docs/impl.md as implementation guidance/acceptance note. Keep it concise but explicit.
