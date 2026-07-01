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
        self.loop_depth = 0

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

    def skip_newlines(self):
        while self.peek_kind("NEWLINE"):
            self.advance()

    def expect_stmt_end(self):
        if self.check("NEWLINE"):
            self.skip_newlines()
            return
        t = self.peek()
        raise ParseError("Expected end of line", t[2])

    # ── program ───────────────────────────────────────────────────────

    def parse_program(self):
        funcs = []
        structs = []
        types = []
        self.skip_newlines()
        while self.peek()[0] in ("FUN", "STRUCT", "TYPE"):
            if self.peek_kind("FUN"):
                funcs.append(self.parse_fn_def())
            elif self.peek_kind("STRUCT"):
                structs.append(self.parse_struct_def())
            else:
                types.append(self.parse_type_def())
            self.skip_newlines()
        if self.peek()[0] != "EOF":
            t = self.peek()
            raise ParseError(f"Unexpected token {t[0]}('{t[1]}')", t[2])
        return ProgramNode(funcs=funcs, structs=structs, types=types)

    # ── fun definition ─────────────────────────────────────────────────

    def parse_struct_def(self):
        self.expect("STRUCT")
        name = self.expect("ID")
        self.expect("LBRACE")
        self.skip_newlines()
        fields = []
        while not self.peek_kind("RBRACE"):
            fname = self.expect("ID")
            self.expect("COLON")
            ftype = self.parse_type()
            self.expect_stmt_end()
            fields.append(StructField(name=fname[1], type=ftype))
        self.expect("RBRACE")
        return StructDefNode(name=name[1], fields=fields)

    def parse_type_def(self):
        self.expect("TYPE")
        name = self.expect("ID")
        self.expect("LBRACE")
        self.skip_newlines()
        variants = []
        while not self.peek_kind("RBRACE"):
            vname = self.expect("ID")
            fields = []
            if self.check("LBRACE"):
                self.skip_newlines()
                while not self.peek_kind("RBRACE"):
                    fname = self.expect("ID")
                    self.expect("COLON")
                    ftype = self.parse_type()
                    self.expect_stmt_end()
                    fields.append(StructField(name=fname[1], type=ftype))
                self.expect("RBRACE")
            variants.append(TypeVariant(name=vname[1], fields=fields))
            self.skip_newlines()
        self.expect("RBRACE")
        return TypeDefNode(name=name[1], variants=variants)

    def parse_fn_def(self):
        self.expect("FUN")
        name = self.expect("ID")
        self.expect("LPAREN")
        params = self.parse_params()
        self.expect("RPAREN")
        self.expect("COLON")
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
            if len(params) > 4:
                raise ParseError("functions may have at most 4 parameters in v0", pname[2])
            if not self.check("COMMA"):
                break
        return params

    def parse_type(self):
        if self.peek_kind("ID") and self.peek()[1] == "map":
            self.advance()
            self.expect("LBRACKET")
            key = self.expect("ID")
            self.expect("RBRACKET")
            value = self.parse_type()
            return f"map[{key[1]}]{value}"
        t = self.advance()
        if t[0] in ("ID",):
            typ = t[1]
            while self.check("LBRACKET"):
                self.expect("RBRACKET")
                typ = f"{typ}[]"
            return typ
        raise ParseError(f"Expected type, got {t[0]}({t[1]})", t[2])

    # ── block ─────────────────────────────────────────────────────────

    def parse_block(self):
        self.expect("LBRACE")
        self.skip_newlines()
        stmts = []
        while not self.peek_kind("RBRACE"):
            if self.peek()[0] == "EOF":
                raise ParseError("Unexpected end of file in block")
            stmts.append(self.parse_stmt())
            self.skip_newlines()
        self.expect("RBRACE")
        return BlockNode(stmts=stmts)

    # ── statements ────────────────────────────────────────────────────

    EXPR_FIRST = {"NUMBER", "STRING", "FSTRING", "CHAR", "ID", "LPAREN", "TRUE", "FALSE", "BANG", "TILDE", "NEW"}

    def _skip_balanced_brackets(self, i):
        depth = 1
        i += 1
        while i < len(self.tokens) and depth > 0:
            kind = self.tokens[i][0]
            if kind == "LBRACKET":
                depth += 1
            elif kind == "RBRACKET":
                depth -= 1
            i += 1
        return i

    def _assignment_operator_pos(self):
        """Return ASSIGN position for ID (.ID | [expr])* =, or None."""
        if not self.peek_kind("ID"):
            return None

        i = self.pos + 1
        while i < len(self.tokens):
            kind = self.tokens[i][0]
            if kind == "DOT":
                if i + 1 >= len(self.tokens) or self.tokens[i + 1][0] != "ID":
                    return None
                i += 2
            elif kind == "LBRACKET":
                i = self._skip_balanced_brackets(i)
            elif kind in self.ASSIGN_TOKENS:
                return i
            else:
                return None
        return None

    def _is_assignment(self):
        return self._assignment_operator_pos() is not None

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
        if t[0] == "FOR":
            return self.parse_for_stmt()
        if t[0] == "BREAK":
            return self.parse_break_stmt()
        if t[0] == "CONTINUE":
            return self.parse_continue_stmt()
        if t[0] == "PANIC":
            return self.parse_panic_stmt()
        if t[0] == "ASSERT":
            return self.parse_assert_stmt()
        if t[0] == "MATCH":
            return self.parse_match_stmt()
        if t[0] == "ID":
            if self._is_assignment():
                return self.parse_assign_stmt()
        if t[0] in self.EXPR_FIRST:
            return self.parse_expr_stmt()
        raise ParseError(f"Unexpected token {t[0]} in statement", t[2])

    def parse_return_stmt(self):
        line = self.peek()[2]
        self.expect("RETURN")
        expr = None
        if not self.peek_kind("NEWLINE"):
            expr = self.parse_expr()
        self.expect_stmt_end()
        return ReturnNode(expr=expr, line=line)

    def parse_let_stmt(self):
        self.expect("LET")
        name = self.expect("ID")
        typ = None
        if self.peek_kind("COLON"):
            self.advance()
            typ = self.parse_type()
        value = None
        if self.check("ASSIGN"):
            value = self.parse_expr()
        self.expect_stmt_end()
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
        op_token = self.advance()
        if op_token[0] not in self.ASSIGN_TOKENS:
            raise ParseError(f"Expected assignment operator, got {op_token[0]}", op_token[2])
        value = self.parse_expr()
        self.expect_stmt_end()
        op = self.ASSIGN_TOKENS[op_token[0]]
        if op:
            return AssignOpNode(op=op, target=lhs, value=value)
        if isinstance(lhs, VarNode):
            return AssignNode(name=lhs.name, value=value)
        elif isinstance(lhs, FieldAccessNode):
            return FieldSetNode(object=lhs.object, field=lhs.field, value=value)
        elif isinstance(lhs, SubscriptNode):
            return SubscriptAssignNode(base=lhs.base, index=lhs.index, value=value)
        raise ParseError(f"Invalid assignment target: {type(lhs).__name__}")

    ASSIGN_TOKENS = {
        "ASSIGN": "",
        "PLUS_ASSIGN": "+",
        "MINUS_ASSIGN": "-",
        "STAR_ASSIGN": "*",
        "SLASH_ASSIGN": "/",
        "PERCENT_ASSIGN": "%",
        "SHL_ASSIGN": "<<",
        "SHR_ASSIGN": ">>",
        "USHR_ASSIGN": ">>>",
        "AMP_ASSIGN": "&",
        "PIPE_ASSIGN": "|",
        "CARET_ASSIGN": "^",
    }

    def parse_if_stmt(self):
        self.expect("IF")
        cond = self.parse_expr()
        then_block = self.parse_block()
        else_block = None
        self.skip_newlines()
        if self.check("ELSE"):
            self.skip_newlines()
            if self.peek_kind("IF"):
                else_block = BlockNode(stmts=[self.parse_if_stmt()])
            else:
                else_block = self.parse_block()
        return IfNode(cond=cond, then_block=then_block, else_block=else_block)

    def parse_while_stmt(self):
        self.expect("WHILE")
        cond = self.parse_expr()
        self.loop_depth += 1
        body = self.parse_block()
        self.loop_depth -= 1
        return WhileNode(cond=cond, body=body)

    def parse_for_stmt(self):
        self.expect("FOR")
        name = self.expect("ID")
        self.expect("IN")
        start = self.parse_expr()
        self.expect("COLON")
        end = self.parse_expr()
        self.loop_depth += 1
        body = self.parse_block()
        self.loop_depth -= 1
        return ForRangeNode(name=name[1], start=start, end=end, body=body)

    def parse_panic_stmt(self):
        t = self.expect("PANIC")
        message = self.parse_expr()
        self.expect_stmt_end()
        return PanicNode(message=message, line=t[2])

    def parse_assert_stmt(self):
        t = self.expect("ASSERT")
        cond = self.parse_expr()
        message = None
        if self.check("COMMA"):
            message = self.parse_expr()
        self.expect_stmt_end()
        return AssertNode(cond=cond, message=message, line=t[2])

    def parse_match_stmt(self):
        self.expect("MATCH")
        expr = self.parse_expr()
        self.expect("LBRACE")
        self.skip_newlines()
        cases = []
        while not self.peek_kind("RBRACE"):
            if self.peek_kind("ELSE"):
                self.advance()
                self.expect("COLON")
                body = self.parse_block()
                cases.append(MatchCase(pattern=None, bindings=[], body=body, is_else=True))
            else:
                bindings = []
                if (
                    self.peek_kind("ID")
                    and self.pos + 2 < len(self.tokens)
                    and self.tokens[self.pos + 1][0] == "DOT"
                    and self.tokens[self.pos + 2][0] == "ID"
                ):
                    type_name = self.advance()[1]
                    self.expect("DOT")
                    variant = self.expect("ID")[1]
                    pattern = FieldAccessNode(object=VarNode(type_name), field=variant)
                else:
                    pattern = self.parse_expr()
                if isinstance(pattern, FieldAccessNode) and self.check("LBRACE"):
                    if not self.peek_kind("RBRACE"):
                        while True:
                            field = self.expect("ID")
                            bind_name = field[1]
                            if self.check("COLON"):
                                bind_name = self.expect("ID")[1]
                            bindings.append((field[1], bind_name))
                            if not self.check("COMMA"):
                                break
                    self.expect("RBRACE")
                self.expect("COLON")
                body = self.parse_block()
                cases.append(MatchCase(pattern=pattern, bindings=bindings, body=body))
            self.skip_newlines()
        self.expect("RBRACE")
        return MatchNode(expr=expr, cases=cases)

    def parse_break_stmt(self):
        t = self.expect("BREAK")
        if self.loop_depth == 0:
            raise ParseError("break outside loop", t[2])
        self.expect_stmt_end()
        return BreakNode(line=t[2])

    def parse_continue_stmt(self):
        t = self.expect("CONTINUE")
        if self.loop_depth == 0:
            raise ParseError("continue outside loop", t[2])
        self.expect_stmt_end()
        return ContinueNode(line=t[2])

    def parse_expr_stmt(self):
        expr = self.parse_expr()
        self.expect_stmt_end()
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
        "PIPE": "|", "CARET": "^", "AMPERSAND": "&",
        "SHL": "<<", "SHR": ">>", "USHR": ">>>",
    }

    def parse_equality(self):
        left = self.parse_bit_or()
        while op := self.check("EQEQ") or self.check("NEQ"):
            left = BinaryNode(op=self.OP_MAP[op[0]], left=left, right=self.parse_bit_or())
        return left

    def parse_bit_or(self):
        left = self.parse_bit_xor()
        while op := self.check("PIPE"):
            left = BinaryNode(op=self.OP_MAP[op[0]], left=left, right=self.parse_bit_xor())
        return left

    def parse_bit_xor(self):
        left = self.parse_bit_and()
        while op := self.check("CARET"):
            left = BinaryNode(op=self.OP_MAP[op[0]], left=left, right=self.parse_bit_and())
        return left

    def parse_bit_and(self):
        left = self.parse_comparison()
        while op := self.check("AMPERSAND"):
            left = BinaryNode(op=self.OP_MAP[op[0]], left=left, right=self.parse_comparison())
        return left

    def parse_comparison(self):
        left = self.parse_shift()
        while op := (self.check("LT") or self.check("GT")
                     or self.check("LTE") or self.check("GTE")):
            left = BinaryNode(op=self.OP_MAP[op[0]], left=left, right=self.parse_shift())
        return left

    def parse_shift(self):
        left = self.parse_term()
        while op := (self.check("SHL") or self.check("SHR") or self.check("USHR")):
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
        if self.check("BANG"):
            return UnaryNode(op="!", expr=self.parse_unary())
        if self.check("MINUS"):
            return UnaryNode(op="-", expr=self.parse_unary())
        if self.check("TILDE"):
            return UnaryNode(op="~", expr=self.parse_unary())
        return self.parse_primary()

    def parse_primary(self):
        if self.peek_kind("NEW"):
            self.expect("NEW")
            t = self.advance()
            if t[0] != "ID":
                raise ParseError(f"Expected type after new, got {t[0]}", t[2])
            if t[1] == "map":
                self.expect("LBRACKET")
                key = self.expect("ID")
                self.expect("RBRACKET")
                value = self.parse_type()
                return NewNode(struct_name=f"map[{key[1]}]{value}")
            name = t[1]
            if self.check("LBRACKET"):
                count = None
                if not self.peek_kind("RBRACKET"):
                    count = self.parse_expr()
                self.expect("RBRACKET")
                if count is None and self.check("LBRACE"):
                    return ArrayLiteralNode(elem_type=name, values=self.parse_brace_values())
                return NewArrayNode(elem_type=name, count=count)
            if self.check("DOT"):
                variant = self.expect("ID")
                if self.check("LBRACE"):
                    return StructInitNode(type_name=name, variant=variant[1], fields=self.parse_named_fields_after_lbrace())
                return StructInitNode(type_name=name, variant=variant[1], fields=[])
            if self.check("LBRACE"):
                return StructInitNode(type_name=name, fields=self.parse_named_fields_after_lbrace())
            return StructInitNode(type_name=name, fields=[])
        if self.peek_kind("NUMBER"):
            t = self.advance()
            return LiteralNode(value=t[1])
        if self.peek_kind("TRUE"):
            self.advance()
            return BoolNode(value=1)
        if self.peek_kind("FALSE"):
            self.advance()
            return BoolNode(value=0)
        if self.peek_kind("CHAR"):
            t = self.advance()
            return CharNode(value=t[1])
        if self.peek_kind("STRING"):
            t = self.advance()
            return StringNode(value=t[1])
        if self.peek_kind("FSTRING"):
            t = self.advance()
            return FStringNode(parts=self.parse_fstring_parts(t[1], t[2]))
        if self.peek_kind("ID"):
            t = self.advance()
            name = t[1]
            if self.peek_kind("LBRACKET") and self.pos + 1 < len(self.tokens) and self.tokens[self.pos + 1][0] == "RBRACKET":
                self.advance()
                self.advance()
                elem_type = name
                if self.check("LBRACE"):
                    return ArrayLiteralNode(elem_type=elem_type, values=self.parse_brace_values())
                raise ParseError("Expected array literal after type[]", t[2])
            if self.check("LPAREN"):
                args = self.parse_args()
                self.expect("RPAREN")
                if len(args) > 4:
                    raise ParseError("function calls may have at most 4 arguments in v0", t[2])
                node = CallNode(name=name, args=args)
            else:
                node = VarNode(name=name)
            # Postfix: .field and [index]
            while True:
                if self.check("DOT"):
                    field = self.expect("ID")
                    if self.check("LPAREN"):
                        args = self.parse_args()
                        self.expect("RPAREN")
                        if isinstance(node, VarNode) and node.name == "os":
                            node = CallNode(name=field[1], args=args, namespace="os")
                        else:
                            if len(args) > 4:
                                raise ParseError("function calls may have at most 4 arguments in v0", field[2])
                            raise ParseError("method calls are only supported for os.* in v0", field[2])
                    else:
                        node = FieldAccessNode(object=node, field=field[1])
                elif self.check("LBRACKET"):
                    start = None
                    if not self.peek_kind("COLON") and not self.peek_kind("RBRACKET"):
                        start = self.parse_expr()
                    if self.check("COLON"):
                        end = None
                        if not self.peek_kind("RBRACKET"):
                            end = self.parse_expr()
                        self.expect("RBRACKET")
                        node = SliceNode(base=node, start=start, end=end)
                        continue
                    index = start
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

    def parse_fstring_parts(self, parts, line):
        parsed = []
        for kind, value in parts:
            if kind == "text":
                if value:
                    parsed.append((kind, value))
                continue
            if kind == "expr":
                from lexer import lex
                p = Parser(lex(value))
                expr = p.parse_expr()
                if p.peek()[0] != "EOF":
                    t = p.peek()
                    raise ParseError(f"Unexpected token {t[0]}('{t[1]}') in f-string expression", line)
                parsed.append((kind, expr))
                continue
            raise ParseError(f"Unknown f-string part {kind}", line)
        return parsed

    def parse_named_fields_after_lbrace(self):
        fields = []
        if not self.peek_kind("RBRACE"):
            while True:
                name = self.expect("ID")
                self.expect("COLON")
                value = self.parse_expr()
                fields.append((name[1], value))
                if not self.check("COMMA"):
                    break
        self.expect("RBRACE")
        return fields

    def parse_brace_values(self):
        values = []
        if not self.peek_kind("RBRACE"):
            while True:
                values.append(self.parse_expr())
                if not self.check("COMMA"):
                    break
        self.expect("RBRACE")
        return values

    def parse_args(self):
        args = []
        if not self.peek_kind("RPAREN"):
            args.append(self.parse_expr())
            while self.check("COMMA"):
                args.append(self.parse_expr())
        return args
