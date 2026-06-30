Task: make Python reference compiler preserve compound assignment as AssignOp, matching the Epic parser.

Baseline is already staged with `git add -A`. Make only this narrow Python-side change.

Files allowed:
- bootstrap/ast_nodes.py
- bootstrap/parser.py
- bootstrap/codegen.py
- test_parser_bootstrap.py

Do not edit src/*.ep, examples, docs, or unrelated files.

Current mismatch:
- Epic parser dumps compound assignment as:
  AssignOp +
    Var x
    Literal 5
- Python parser currently lowers x += 5 into:
  Assign x
    Binary +
      Var x
      Literal 5

Required AST shape:
- Add AssignOpNode to bootstrap/ast_nodes.py with fields:
  - op: str
  - target: ASTNode   # VarNode, FieldAccessNode, or SubscriptNode
  - value: ASTNode
- In bootstrap/parser.py parse_assign_stmt:
  - For plain `=`, keep existing AssignNode / FieldSetNode / SubscriptAssignNode behavior.
  - For compound ops, return AssignOpNode(op=operator, target=lhs, value=value) without lowering into BinaryNode.
  - Keep ASSIGN_TOKENS mapping as-is.

Codegen requirement:
- Add support for AssignOpNode in bootstrap/codegen.py so `python runtests.py --linker py` remains green.
- Implement semantics equivalent to current lowering for var/field/subscript targets, but keep the AST as AssignOp.
- It is acceptable to implement codegen by constructing the equivalent AssignNode/FieldSetNode/SubscriptAssignNode with BinaryNode at emission time, as long as parser AST and dumps preserve AssignOp.

Parser dump requirement:
- Update test_parser_bootstrap.py py_dump to emit AssignOp in the same generic shape as Epic parser dump:
  AssignOp <op>
    <target dump>
    <value dump>
- This should make examples/v1_compound_assign.ep parser dump pass.

Validation:
- Run `python test_parser_bootstrap.py` and report before/after failure count.
- Run `python runtests.py --linker py` and report result.
