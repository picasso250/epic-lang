"""
Epic v0 — recursive-descent parser
Consumes tokens from lexer, produces AST dataclass nodes.
"""

from ast_nodes import *


class ParseError(Exception):
    def __init__(self, msg, line=None):
        prefix = f"Parse error line {line}: " if line else "Parse error: "
        super().__init__(prefix + msg)


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return ("EOF", None, -1)

    def peek_kind(self, kind):
        return self.peek()[0] == kind

    def advance(self):
        t = self.peek()
        self.pos += 1
        return t

    def expect(self, kind):
        t = self.advance()
        if t[0] != kind:
            raise ParseError(f"Expected {kind}, got {t[0]}('{t[1]}')", t[2])
        return t

    def check(self, kind):
        if self.peek_kind(kind):
            return self.advance()
        return None

    # ── program ───────────────────────────────────────────────────────

    def parse_program(self):
        funcs = []
        structs = []
        while self.peek()[0] in ("FUN", "STRUCT"):
            if self.peek_kind("FUN"):
                funcs.append(self.parse_fn_def())
            else:
                structs.append(self.parse_struct_def())
        if self.peek()[0] != "EOF":
            t = self.peek()
            raise ParseError(f"Unexpected token {t[0]}('{t[1]}')", t[2])
        return ProgramNode(funcs=funcs, structs=structs)

    # ── fun definition ─────────────────────────────────────────────────

    def parse_struct_def(self):
        self.expect("STRUCT")
        name = self.expect("ID")
        self.expect("LBRACE")
        fields = []
        while not self.peek_kind("RBRACE"):
            fname = self.expect("ID")
            self.expect("COLON")
            ftype = self.parse_type()
            self.expect("SEMICOLON")
            fields.append(StructField(name=fname[1], type=ftype))
        self.expect("RBRACE")
        return StructDefNode(name=name[1], fields=fields)

    def parse_fn_def(self):
        self.expect("FUN")
        name = self.expect("ID")
        self.expect("LPAREN")
        params = self.parse_params()
        self.expect("RPAREN")
        self.expect("ARROW")
        ret_type = self.parse_type()
        body = self.parse_block()
        return FunDefNode(
            name=name[1],
            params=params,
            ret_type=ret_type,
            body=body,
            line=name[2],
        )

    def parse_params(self):
        params = []
        if not self.peek_kind("ID"):
            return params
        while True:
            pname = self.expect("ID")
            self.expect("COLON")
            ptype = self.parse_type()
            params.append(Param(name=pname[1], type=ptype))
            if not self.check("COMMA"):
                break
        return params

    def parse_type(self):
        t = self.advance()
        if t[0] == "AMPERSAND":
            inner = self.parse_type()
            return f"&{inner}"  # e.g. "&Token" or "&i64"
        if t[0] == "ID":
            return t[1]  # struct name
        raise ParseError(f"Expected type, got {t[0]}({t[1]})", t[2])

    # ── block ─────────────────────────────────────────────────────────

    def parse_block(self):
        self.expect("LBRACE")
        stmts = []
        while not self.peek_kind("RBRACE"):
            if self.peek()[0] == "EOF":
                raise ParseError("Unexpected end of file in block")
            stmts.append(self.parse_stmt())
        self.expect("RBRACE")
        return BlockNode(stmts=stmts)

    # ── statements ────────────────────────────────────────────────────

    EXPR_FIRST = {"NUMBER", "STRING", "ID", "LPAREN", "MINUS", "BANG"}

    def _is_assignment(self):
        """Look ahead past ID (.ID | [expr])* to see if = follows."""
        i = self.pos + 1
        while i < len(self.tokens):
            kind = self.tokens[i][0]
            if kind == "DOT":
                i += 2
            elif kind == "LBRACKET":
                depth = 1
                i += 1
                while i < len(self.tokens) and depth > 0:
                    if self.tokens[i][0] == "LBRACKET":
                        depth += 1
                    elif self.tokens[i][0] == "RBRACKET":
                        depth -= 1
                    i += 1
            else:
                return kind == "ASSIGN"
        return False

    def parse_stmt(self):
        t = self.peek()
        if t[0] == "RETURN":
            return self.parse_return_stmt()
        if t[0] == "LET":
            return self.parse_let_stmt()
        if t[0] == "IF":
            return self.parse_if_stmt()
        if t[0] == "WHILE":
            return self.parse_while_stmt()
        if t[0] == "ID":
            if self._is_assignment():
                return self.parse_assign_stmt()
        if t[0] in self.EXPR_FIRST:
            return self.parse_expr_stmt()
        raise ParseError(f"Unexpected token {t[0]} in statement", t[2])

    def parse_return_stmt(self):
        line = self.peek()[2]
        self.expect("RETURN")
        expr = self.parse_expr()
        self.expect("SEMICOLON")
        return ReturnNode(expr=expr, line=line)

    def parse_let_stmt(self):
        self.expect("LET")
        name = self.expect("ID")
        typ = None
        if self.check("COLON"):
            typ = self.parse_type()
        value = None
        if self.check("ASSIGN"):
            value = self.parse_expr()
        self.expect("SEMICOLON")
        return LetNode(name=name[1], var_type=typ, value=value)

    def parse_assign_stmt(self):
        name = self.expect("ID")
        # Build LHS chain: .field | [index]
        lhs = VarNode(name=name[1])
        while True:
            if self.check("DOT"):
                field = self.expect("ID")
                lhs = FieldAccessNode(object=lhs, field=field[1])
            elif self.check("LBRACKET"):
                index = self.parse_expr()
                self.expect("RBRACKET")
                lhs = SubscriptNode(base=lhs, index=index)
            else:
                break
        self.expect("ASSIGN")
        value = self.parse_expr()
        self.expect("SEMICOLON")
        if isinstance(lhs, VarNode):
            return AssignNode(name=lhs.name, value=value)
        elif isinstance(lhs, FieldAccessNode):
            return FieldSetNode(object=lhs.object, field=lhs.field, value=value)
        elif isinstance(lhs, SubscriptNode):
            return SubscriptAssignNode(base=lhs.base, index=lhs.index, value=value)
        raise ParseError(f"Invalid assignment target: {type(lhs).__name__}")

    def parse_if_stmt(self):
        self.expect("IF")
        cond = self.parse_expr()
        then_block = self.parse_block()
        else_block = None
        if self.check("ELSE"):
            else_block = self.parse_block()
        return IfNode(cond=cond, then_block=then_block, else_block=else_block)

    def parse_while_stmt(self):
        self.expect("WHILE")
        cond = self.parse_expr()
        body = self.parse_block()
        return WhileNode(cond=cond, body=body)

    def parse_expr_stmt(self):
        expr = self.parse_expr()
        self.expect("SEMICOLON")
        return ExprStmtNode(expr=expr)

    # ── expressions ───────────────────────────────────────────────────

    def parse_expr(self):
        return self.parse_logic_or()

    def parse_logic_or(self):
        left = self.parse_logic_and()
        while self.check("OR"):
            right = self.parse_logic_and()
            left = BinaryNode(op="||", left=left, right=right)
        return left

    def parse_logic_and(self):
        left = self.parse_equality()
        while self.check("AND"):
            right = self.parse_equality()
            left = BinaryNode(op="&&", left=left, right=right)
        return left

    # Token kind → operator string
    OP_MAP = {
        "PLUS": "+", "MINUS": "-", "STAR": "*", "SLASH": "/", "PERCENT": "%",
        "EQEQ": "==", "NEQ": "!=", "LT": "<", "GT": ">",
        "LTE": "<=", "GTE": ">=", "AND": "&&", "OR": "||",
    }

    def parse_equality(self):
        left = self.parse_comparison()
        while op := self.check("EQEQ") or self.check("NEQ"):
            left = BinaryNode(op=self.OP_MAP[op[0]], left=left, right=self.parse_comparison())
        return left

    def parse_comparison(self):
        left = self.parse_term()
        while op := (self.check("LT") or self.check("GT")
                     or self.check("LTE") or self.check("GTE")):
            left = BinaryNode(op=self.OP_MAP[op[0]], left=left, right=self.parse_term())
        return left

    def parse_term(self):
        left = self.parse_factor()
        while op := self.check("PLUS") or self.check("MINUS"):
            left = BinaryNode(op=self.OP_MAP[op[0]], left=left, right=self.parse_factor())
        return left

    def parse_factor(self):
        left = self.parse_unary()
        while op := (self.check("STAR") or self.check("SLASH") or self.check("PERCENT")):
            left = BinaryNode(op=self.OP_MAP[op[0]], left=left, right=self.parse_unary())
        return left

    def parse_unary(self):
        return self.parse_primary()

    def parse_primary(self):
        if self.peek_kind("NEW"):
            self.expect("NEW")
            t = self.advance()
            if t[0] != "ID":
                raise ParseError(f"Expected type after new, got {t[0]}", t[2])
            elem = t[1]
            if self.check("LBRACKET"):
                count = self.parse_expr()
                self.expect("RBRACKET")
                return NewArrayNode(elem_type=elem, count=count)
            return NewNode(struct_name=elem)
        if self.peek_kind("NUMBER"):
            t = self.advance()
            return LiteralNode(value=t[1])
        if self.peek_kind("CHAR"):
            t = self.advance()
            return LiteralNode(value=t[1])
        if self.peek_kind("STRING"):
            t = self.advance()
            return StringNode(value=t[1])
        if self.peek_kind("ID"):
            t = self.advance()
            name = t[1]
            if self.check("LPAREN"):
                args = self.parse_args()
                self.expect("RPAREN")
                node = CallNode(name=name, args=args)
            else:
                node = VarNode(name=name)
            # Postfix: .field and [index]
            while True:
                if self.check("DOT"):
                    field = self.expect("ID")
                    node = FieldAccessNode(object=node, field=field[1])
                elif self.check("LBRACKET"):
                    index = self.parse_expr()
                    self.expect("RBRACKET")
                    node = SubscriptNode(base=node, index=index)
                else:
                    break
            return node
        if self.check("LPAREN"):
            expr = self.parse_expr()
            self.expect("RPAREN")
            return expr
        t = self.peek()
        raise ParseError(f"Unexpected token {t[0]}('{t[1]}')", t[2])

    def parse_args(self):
        args = []
        if not self.peek_kind("RPAREN"):
            args.append(self.parse_expr())
            while self.check("COMMA"):
                args.append(self.parse_expr())
        return args
