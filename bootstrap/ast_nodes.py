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
    """Common source metadata; compiler passes should use concrete node families."""
    line: int = 0


class StmtNode(ASTNode):
    """Base class for nodes that may appear in a block statement list."""


class ExprNode(ASTNode):
    """Base class for nodes that produce a value."""


@dataclass
class ProgramNode(ASTNode):
    funcs: list[FunDefNode]
    structs: list[StructDefNode]
    unions: list[UnionDefNode] = field(default_factory=list)
    externs: list[ExternDefNode] = field(default_factory=list)


@dataclass
class ExternDefNode(ASTNode):
    library: str
    name: str
    params: list[Param]
    ret_type: EpicType
    resolved_type: Optional[EpicType] = None


@dataclass
class StructField(ASTNode):
    name: str
    type: EpicType
    resolved_type: Optional[EpicType] = None


@dataclass
class StructDefNode(ASTNode):
    name: str
    fields: list[StructField]


@dataclass
class UnionDefNode(ASTNode):
    name: str
    members: list[str]


@dataclass
class Param(ASTNode):
    name: str
    type: EpicType
    resolved_type: Optional[EpicType] = None


@dataclass
class FunDefNode(ASTNode):
    name: str
    params: list[Param]
    ret_type: EpicType
    body: 'BlockNode'
    resolved_type: Optional[EpicType] = None
    receiver_name: Optional[str] = None
    receiver_type: Optional[EpicType] = None
    method_name: Optional[str] = None


@dataclass
class BlockNode(ASTNode):
    stmts: list[StmtNode]


# ── statements ──────────────────────────────────────────────────────────

@dataclass
class ReturnNode(StmtNode):
    expr: Optional[ExprNode]


@dataclass
class LetNode(StmtNode):
    name: str
    value: ExprNode
    var_type: Optional[EpicType] = None
    resolved_type: Optional[EpicType] = None


@dataclass
class AssignNode(StmtNode):
    name: str
    value: ExprNode


@dataclass
class AssignOpNode(StmtNode):
    op: str
    target: ExprNode
    value: ExprNode


@dataclass
class FieldSetNode(StmtNode):
    object: ExprNode
    field: str
    value: ExprNode



@dataclass
class SubscriptAssignNode(StmtNode):
    base: ExprNode
    index: ExprNode
    value: ExprNode



@dataclass
class IfNode(StmtNode):
    cond: ExprNode
    then_block: BlockNode
    else_block: Optional[BlockNode] = None


@dataclass
class LoopNode(StmtNode):
    cond: ExprNode
    body: BlockNode


@dataclass
class BreakNode(StmtNode):
    pass


@dataclass
class ContinueNode(StmtNode):
    pass


@dataclass
class ForRangeNode(StmtNode):
    name: str
    start: ExprNode
    end: ExprNode
    body: 'BlockNode'
    resolved_type: Optional[EpicType] = None


@dataclass
class PanicNode(StmtNode):
    message: ExprNode



@dataclass
class MatchCase(ASTNode):
    pattern: Optional[ExprNode]
    body: 'BlockNode'
    is_else: bool = False
    variant_name: Optional[str] = None
    binding_name: Optional[str] = None
    binding_type: Optional[EpicType] = None


@dataclass
class MatchNode(StmtNode):
    expr: ExprNode
    cases: list[MatchCase]
    union_name: Optional[str] = None


@dataclass
class ExprStmtNode(StmtNode):
    expr: ExprNode


# ── expressions ─────────────────────────────────────────────────────────

@dataclass
class LiteralNode(ExprNode):
    value: int
    resolved_type: Optional[EpicType] = None


@dataclass
class CharNode(ExprNode):
    value: int
    resolved_type: Optional[EpicType] = None


@dataclass
class BoolNode(ExprNode):
    value: int
    resolved_type: Optional[EpicType] = None


@dataclass
class StringNode(ExprNode):
    value: str
    resolved_type: Optional[EpicType] = None


@dataclass
class EmbedNode(ExprNode):
    path: str
    source_path: str
    resolved_type: Optional[EpicType] = None


class FStringPart:
    pass


@dataclass
class FStringTextPart(FStringPart):
    value: str


@dataclass
class FStringExprPart(FStringPart):
    expr: ExprNode


@dataclass
class FStringNode(ExprNode):
    parts: list[FStringPart]
    resolved_type: Optional[EpicType] = None


@dataclass
class VarNode(ExprNode):
    name: str
    resolved_type: Optional[EpicType] = None


@dataclass
class CallNode(ExprNode):
    name: str
    args: list[ExprNode]
    resolved_type: Optional[EpicType] = None


@dataclass
class BinaryNode(ExprNode):
    op: str
    left: ExprNode
    right: ExprNode
    resolved_type: Optional[EpicType] = None


@dataclass
class UnaryNode(ExprNode):
    op: str
    expr: ExprNode
    resolved_type: Optional[EpicType] = None


@dataclass
class FieldAccessNode(ExprNode):
    object: ExprNode
    field: str
    resolved_type: Optional[EpicType] = None


@dataclass
class NullCheckNode(ExprNode):
    expr: ExprNode
    resolved_type: Optional[EpicType] = None


@dataclass
class DotCallNode(ExprNode):
    object: ExprNode
    name: str
    args: list[ExprNode]
    resolved_type: Optional[EpicType] = None


@dataclass
class SubscriptNode(ExprNode):
    base: ExprNode
    index: ExprNode
    resolved_type: Optional[EpicType] = None


@dataclass
class SliceNode(ExprNode):
    base: ExprNode
    start: ExprNode
    end: ExprNode
    resolved_type: Optional[EpicType] = None


@dataclass
class NewArrayNode(ExprNode):
    elem_type: EpicType
    count: Optional[ExprNode] = None
    resolved_type: Optional[EpicType] = None


@dataclass
class StructInitNode(ExprNode):
    type_name: str
    fields: list
    resolved_type: Optional[EpicType] = None


@dataclass
class UnionInitNode(ExprNode):
    type_name: str
    payload: ExprNode
    resolved_type: Optional[EpicType] = None


@dataclass
class ArrayLiteralNode(ExprNode):
    elem_type: EpicType
    values: list[ExprNode]
    resolved_type: Optional[EpicType] = None
