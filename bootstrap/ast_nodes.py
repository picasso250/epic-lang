"""
Epic v0 - AST node definitions.
Each node is a dataclass; no "kind" field, type is the class itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from epic_types import EpicType


@dataclass(kw_only=True)
class ASTNode:
    """Base class for all AST nodes."""
    line: int = 0


@dataclass
class ProgramNode(ASTNode):
    funcs: list      # list[FunDefNode]
    structs: list    # list[StructDefNode]
    globals: list = field(default_factory=list)  # list[LetNode]
    unions: list = field(default_factory=list)   # list[UnionDefNode]


@dataclass
class StructField(ASTNode):
    name: str
    type: EpicType
    resolved_type: Optional[EpicType] = None


@dataclass
class StructDefNode(ASTNode):
    name: str
    fields: list     # list[StructField]


@dataclass
class UnionDefNode(ASTNode):
    name: str
    members: list    # list[str], each a struct name


@dataclass
class Param(ASTNode):
    name: str
    type: EpicType
    resolved_type: Optional[EpicType] = None


@dataclass
class FunDefNode(ASTNode):
    name: str
    params: list     # list[Param]
    ret_type: EpicType
    body: 'BlockNode'
    resolved_type: Optional[EpicType] = None
    receiver_name: str = ""
    receiver_type: Optional[EpicType] = None
    method_name: str = ""


@dataclass
class BlockNode(ASTNode):
    stmts: list      # list of statement ASTNode
    value_expr: Optional[ASTNode] = None


# ── statements ──────────────────────────────────────────────────────────

@dataclass
class ReturnNode(ASTNode):
    expr: Optional[ASTNode]


@dataclass
class LetNode(ASTNode):
    name: str
    var_type: Optional[EpicType] = None
    value: Optional[ASTNode] = None
    resolved_type: Optional[EpicType] = None


@dataclass
class AssignNode(ASTNode):
    name: str
    value: ASTNode


@dataclass
class AssignOpNode(ASTNode):
    op: str
    target: ASTNode
    value: ASTNode


@dataclass
class FieldSetNode(ASTNode):
    object: ASTNode
    field: str
    value: ASTNode



@dataclass
class SubscriptAssignNode(ASTNode):
    base: ASTNode
    index: ASTNode
    value: ASTNode



@dataclass
class IfNode(ASTNode):
    cond: ASTNode
    then_block: BlockNode
    else_block: Optional[BlockNode] = None


@dataclass
class WhileNode(ASTNode):
    cond: ASTNode
    body: BlockNode


@dataclass
class BreakNode(ASTNode):
    pass


@dataclass
class ContinueNode(ASTNode):
    pass


@dataclass
class ForRangeNode(ASTNode):
    name: str
    start: ASTNode
    end: ASTNode
    body: 'BlockNode'
    resolved_type: Optional[EpicType] = None


@dataclass
class ForInNode(ASTNode):
    name: str
    source: ASTNode
    body: 'BlockNode'
    resolved_type: Optional[EpicType] = None


@dataclass
class PanicNode(ASTNode):
    message: ASTNode


@dataclass
class AssertNode(ASTNode):
    cond: ASTNode
    message: Optional[ASTNode]


@dataclass
class MatchCase(ASTNode):
    pattern: ASTNode
    bindings: list
    body: 'BlockNode'
    is_else: bool = False
    variant_name: str = ""
    binding_name: str = ""
    binding_type: Optional[EpicType] = None


@dataclass
class MatchNode(ASTNode):
    expr: ASTNode
    cases: list
    union_name: str = ""


@dataclass
class ExprStmtNode(ASTNode):
    expr: ASTNode


# ── expressions ─────────────────────────────────────────────────────────

@dataclass
class LiteralNode(ASTNode):
    value: int
    resolved_type: Optional[EpicType] = None


@dataclass
class CharNode(ASTNode):
    value: int
    resolved_type: Optional[EpicType] = None


@dataclass
class BoolNode(ASTNode):
    value: int
    resolved_type: Optional[EpicType] = None


@dataclass
class StringNode(ASTNode):
    value: str
    resolved_type: Optional[EpicType] = None


class FStringPart:
    pass


@dataclass
class FStringTextPart(FStringPart):
    value: str


@dataclass
class FStringExprPart(FStringPart):
    expr: ASTNode


@dataclass
class FStringNode(ASTNode):
    parts: list[FStringPart]
    resolved_type: Optional[EpicType] = None


@dataclass
class VarNode(ASTNode):
    name: str
    resolved_type: Optional[EpicType] = None


@dataclass
class CallNode(ASTNode):
    name: str
    args: list      # list[ASTNode]
    namespace: str = ""
    dll: str = ""
    resolved_type: Optional[EpicType] = None


@dataclass
class BinaryNode(ASTNode):
    op: str
    left: ASTNode
    right: ASTNode
    resolved_type: Optional[EpicType] = None


@dataclass
class UnaryNode(ASTNode):
    op: str
    expr: ASTNode
    resolved_type: Optional[EpicType] = None


@dataclass
class FieldAccessNode(ASTNode):
    object: ASTNode
    field: str
    resolved_type: Optional[EpicType] = None


@dataclass
class NullCheckNode(ASTNode):
    expr: ASTNode
    resolved_type: Optional[EpicType] = None


@dataclass
class DotCallNode(ASTNode):
    object: ASTNode
    name: str
    args: list      # list[ASTNode]
    resolved_type: Optional[EpicType] = None


@dataclass
class SubscriptNode(ASTNode):
    base: ASTNode
    index: ASTNode
    resolved_type: Optional[EpicType] = None


@dataclass
class SliceNode(ASTNode):
    base: ASTNode
    start: ASTNode
    end: ASTNode
    resolved_type: Optional[EpicType] = None


@dataclass
class NewArrayNode(ASTNode):
    elem_type: EpicType
    count: Optional[ASTNode] = None
    resolved_type: Optional[EpicType] = None


@dataclass
class StructInitNode(ASTNode):
    type_name: str
    fields: list
    resolved_type: Optional[EpicType] = None


@dataclass
class UnionInitNode(ASTNode):
    type_name: str
    payload: ASTNode
    resolved_type: Optional[EpicType] = None


@dataclass
class ArrayLiteralNode(ASTNode):
    elem_type: EpicType
    values: list
    resolved_type: Optional[EpicType] = None
