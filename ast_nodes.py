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
class ExprStmtNode(ASTNode):
    expr: ASTNode


# ── expressions ─────────────────────────────────────────────────────────

@dataclass
class LiteralNode(ASTNode):
    value: int


@dataclass
class StringNode(ASTNode):
    value: str


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
class FieldAccessNode(ASTNode):
    object: ASTNode
    field: str


@dataclass
class SubscriptNode(ASTNode):
    base: ASTNode
    index: ASTNode


@dataclass
class NewNode(ASTNode):
    struct_name: str


@dataclass
class NewArrayNode(ASTNode):
    elem_type: str
    count: Optional[ASTNode] = None
