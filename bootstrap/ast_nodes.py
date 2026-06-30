"""
Epic v0 — AST node definitions
Each node is a dataclass; no "kind" field, type is the class itself.
"""

from dataclasses import dataclass, field
from typing import Optional


class ASTNode:
    """Base class for all AST nodes."""
    pass


@dataclass
class ProgramNode(ASTNode):
    funcs: list      # list[FunDefNode]
    structs: list    # list[StructDefNode]
    types: list = field(default_factory=list)


@dataclass
class StructField(ASTNode):
    name: str
    type: str


@dataclass
class StructDefNode(ASTNode):
    name: str
    fields: list     # list[StructField]


@dataclass
class Param(ASTNode):
    name: str
    type: str


@dataclass
class FunDefNode(ASTNode):
    name: str
    params: list     # list[Param]
    ret_type: str
    body: 'BlockNode'
    line: int


@dataclass
class BlockNode(ASTNode):
    stmts: list      # list of statement ASTNode


# ── statements ──────────────────────────────────────────────────────────

@dataclass
class ReturnNode(ASTNode):
    expr: Optional[ASTNode]
    line: int


@dataclass
class LetNode(ASTNode):
    name: str
    var_type: Optional[str] = None
    value: Optional[ASTNode] = None


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
    line: int


@dataclass
class ContinueNode(ASTNode):
    line: int


@dataclass
class ForRangeNode(ASTNode):
    name: str
    start: ASTNode
    end: ASTNode
    body: 'BlockNode'


@dataclass
class PanicNode(ASTNode):
    message: ASTNode
    line: int


@dataclass
class AssertNode(ASTNode):
    cond: ASTNode
    message: Optional[ASTNode]
    line: int


@dataclass
class MatchCase(ASTNode):
    pattern: ASTNode
    bindings: list
    body: 'BlockNode'
    is_else: bool = False


@dataclass
class MatchNode(ASTNode):
    expr: ASTNode
    cases: list


@dataclass
class ExprStmtNode(ASTNode):
    expr: ASTNode


# ── expressions ─────────────────────────────────────────────────────────

@dataclass
class LiteralNode(ASTNode):
    value: int


@dataclass
class CharNode(ASTNode):
    value: int


@dataclass
class BoolNode(ASTNode):
    value: int


@dataclass
class StringNode(ASTNode):
    value: str


@dataclass
class FStringNode(ASTNode):
    parts: list


@dataclass
class VarNode(ASTNode):
    name: str


@dataclass
class CallNode(ASTNode):
    name: str
    args: list      # list[ASTNode]
    namespace: str = ""


@dataclass
class BinaryNode(ASTNode):
    op: str
    left: ASTNode
    right: ASTNode


@dataclass
class UnaryNode(ASTNode):
    op: str
    expr: ASTNode


@dataclass
class FieldAccessNode(ASTNode):
    object: ASTNode
    field: str


@dataclass
class SubscriptNode(ASTNode):
    base: ASTNode
    index: ASTNode


@dataclass
class SliceNode(ASTNode):
    base: ASTNode
    start: Optional[ASTNode]
    end: Optional[ASTNode]


@dataclass
class NewNode(ASTNode):
    struct_name: str


@dataclass
class NewArrayNode(ASTNode):
    elem_type: str
    count: Optional[ASTNode] = None


@dataclass
class StructInitNode(ASTNode):
    type_name: str
    fields: list
    variant: str = ""


@dataclass
class ArrayLiteralNode(ASTNode):
    elem_type: str
    values: list


@dataclass
class TypeVariant(ASTNode):
    name: str
    fields: list


@dataclass
class TypeDefNode(ASTNode):
    name: str
    variants: list
