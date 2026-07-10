"""
Epic v0 — recursive-descent parser
Consumes tokens from lexer, produces AST dataclass nodes.
"""

from ast_nodes import *
from epic_types import ARRAY, BOOL, I32, I64, MAP, NAMED, STR, U32, U64, U8, VOID


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

    def peek_ahead(self, offset):
        idx = self.pos + offset
        if idx < len(self.tokens):
            return self.tokens[idx]
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
        if self.peek_kind("RBRACE"):
            return
        t = self.peek()
        raise ParseError("Expected end of line", t[2])

    # ── program ───────────────────────────────────────────────────────

    def parse_program(self):
        funcs = []
        structs = []
        globals = []
        unions = []
        self.skip_newlines()
        while self.peek()[0] in ("FUN", "STRUCT", "LET", "TYPE"):
            if self.peek_kind("FUN"):
                funcs.append(self.parse_fn_def())
            elif self.peek_kind("STRUCT"):
                structs.append(self.parse_struct_def())
            elif self.peek_kind("TYPE"):
                unions.append(self.parse_union_def())
            else:
                globals.append(self.parse_let_stmt())
            self.skip_newlines()
        if self.peek()[0] != "EOF":
            t = self.peek()
            raise ParseError(f"Unexpected token {t[0]}('{t[1]}')", t[2])
        return ProgramNode(funcs=funcs, structs=structs, globals=globals, unions=unions)

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
            fields.append(StructField(name=fname[1], type=ftype, line=fname[2]))
        self.expect("RBRACE")
        return StructDefNode(name=name[1], fields=fields)

    def parse_union_def(self):
        self.expect("TYPE")
        name = self.expect("ID")
        self.expect("ASSIGN")
        members = []
        while True:
            member = self.expect("ID")
            members.append(member[1])
            if not self.check("PIPE"):
                break
        self.expect_stmt_end()
        return UnionDefNode(name=name[1], members=members)

    def parse_fn_def(self):
        self.expect("FUN")
        receiver_name = ""
        receiver_type = None
        method_name = ""
        if self.peek_kind("LPAREN"):
            self.expect("LPAREN")
            receiver = self.expect("ID")
            self.expect("COLON")
            receiver_type = self.parse_type()
            if receiver_type.kind != "named":
                raise ParseError(f"method receiver must be a named type, got {receiver_type}", receiver[2])
            self.expect("RPAREN")
            name = self.expect("ID")
            receiver_name = receiver[1]
            method_name = name[1]
            symbol_name = f"{receiver_type.name}__{method_name}"
            line = name[2]
            params = [Param(name=receiver_name, type=receiver_type)]
        else:
            name = self.expect("ID")
            symbol_name = name[1]
            line = name[2]
            params = []
        self.expect("LPAREN")
        params.extend(self.parse_params())
        self.expect("RPAREN")
        self.expect("COLON")
        ret_type = self.parse_type()
        body = self.parse_block()
        return FunDefNode(
            name=symbol_name,
            params=params,
            ret_type=ret_type,
            body=body,
            line=line,
            receiver_name=receiver_name,
            receiver_type=receiver_type,
            method_name=method_name,
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
        if self.peek_kind("ID") and self.peek()[1] == "map":
            self.advance()
            self.expect("LBRACKET")
            key = self.expect("ID")
            self.expect("RBRACKET")
            if key[1] != "str":
                raise ParseError(f"only map[str]T is supported, got map[{key[1]}]", key[2])
            value = self.parse_type()
            return MAP(value)
        t = self.advance()
        if t[0] in ("ID",):
            typ = self._type_atom(t[1])
            while self.check("LBRACKET"):
                self.expect("RBRACKET")
                typ = ARRAY(typ)
            return typ
        raise ParseError(f"Expected type, got {t[0]}({t[1]})", t[2])

    def _type_atom(self, name):
        if name == "i64":
            return I64
        if name == "u64":
            return U64
        if name == "i32":
            return I32
        if name == "u32":
            return U32
        if name == "u8":
            return U8
        if name == "bool":
            return BOOL
        if name == "void":
            return VOID
        if name == "str":
            return STR
        return NAMED(name)

    # ── block ─────────────────────────────────────────────────────────

    def parse_block(self):
        self.expect("LBRACE")
        self.skip_newlines()
        stmts = []
        value_expr = None
        while not self.peek_kind("RBRACE"):
            if self.peek()[0] == "EOF":
                raise ParseError("Unexpected end of file in block")
            stmt = self.parse_stmt()
            self.skip_newlines()
            if isinstance(stmt, ExprStmtNode) and self.peek_kind("RBRACE"):
                value_expr = stmt.expr
            else:
                stmts.append(stmt)
        self.expect("RBRACE")
        return BlockNode(stmts=stmts, value_expr=value_expr)

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
        if not self.peek_kind("NEWLINE") and not self.peek_kind("RBRACE"):
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
        lhs = VarNode(name=name[1], line=name[2])
        while True:
            if self.check("DOT"):
                field = self.expect("ID")
                lhs = FieldAccessNode(object=lhs, field=field[1], line=field[2])
            elif self.check("LBRACKET"):
                index = self.parse_expr()
                self.expect("RBRACKET")
                lhs = SubscriptNode(base=lhs, index=index, line=getattr(index, "line", name[2]))
            else:
                break
        op_token = self.advance()
        if op_token[0] not in self.ASSIGN_TOKENS:
            raise ParseError(f"Expected assignment operator, got {op_token[0]}", op_token[2])
        value = self.parse_expr()
        self.expect_stmt_end()
        op = self.ASSIGN_TOKENS[op_token[0]]
        if op:
            return AssignOpNode(op=op, target=lhs, value=value, line=op_token[2])
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

    def parse_for_stmt(self):
        self.expect("FOR")
        if self.peek_kind("ID") and self.pos + 1 < len(self.tokens) and self.tokens[self.pos + 1][0] == "IN":
            name = self.expect("ID")
            self.expect("IN")
            source = self.parse_expr()
            if self.check("COLON"):
                end = self.parse_expr()
                body = self.parse_block()
                return ForRangeNode(name=name[1], start=source, end=end, body=body)
            body = self.parse_block()
            return ForInNode(name=name[1], source=source, body=body)
        cond = self.parse_expr()
        body = self.parse_block()
        return WhileNode(cond=cond, body=body)

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
            elif self.peek_kind("ID") and self.peek()[1] == "_":
                self.advance()
                self.expect("COLON")
                body = self.parse_block()
                cases.append(MatchCase(pattern=None, bindings=[], body=body, is_else=True))
            elif self.peek_kind("ID") and self.peek_ahead(1)[0] == "ID" and self.peek_ahead(2)[0] == "COLON":
                variant = self.expect("ID")
                binding = self.expect("ID")
                self.expect("COLON")
                body = self.parse_block()
                cases.append(MatchCase(pattern=None, bindings=[], body=body, variant_name=variant[1], binding_name=binding[1]))
            else:
                pattern = self.parse_expr()
                self.expect("COLON")
                body = self.parse_block()
                cases.append(MatchCase(pattern=pattern, bindings=[], body=body))
            self.skip_newlines()
        self.expect("RBRACE")
        return MatchNode(expr=expr, cases=cases)

    def parse_break_stmt(self):
        t = self.expect("BREAK")
        self.expect_stmt_end()
        return BreakNode(line=t[2])

    def parse_continue_stmt(self):
        t = self.expect("CONTINUE")
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
        while op := self.check("OR"):
            right = self.parse_logic_and()
            left = BinaryNode(op="||", left=left, right=right, line=op[2])
        return left

    def parse_logic_and(self):
        left = self.parse_equality()
        while op := self.check("AND"):
            right = self.parse_equality()
            left = BinaryNode(op="&&", left=left, right=right, line=op[2])
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
            left = BinaryNode(op=self.OP_MAP[op[0]], left=left, line=op[2], right=self.parse_bit_or())
        return left

    def parse_bit_or(self):
        left = self.parse_bit_xor()
        while op := self.check("PIPE"):
            left = BinaryNode(op=self.OP_MAP[op[0]], left=left, line=op[2], right=self.parse_bit_xor())
        return left

    def parse_bit_xor(self):
        left = self.parse_bit_and()
        while op := self.check("CARET"):
            left = BinaryNode(op=self.OP_MAP[op[0]], left=left, line=op[2], right=self.parse_bit_and())
        return left

    def parse_bit_and(self):
        left = self.parse_comparison()
        while op := self.check("AMPERSAND"):
            left = BinaryNode(op=self.OP_MAP[op[0]], left=left, line=op[2], right=self.parse_comparison())
        return left

    def parse_comparison(self):
        left = self.parse_shift()
        while op := (self.check("LT") or self.check("GT")
                     or self.check("LTE") or self.check("GTE")):
            left = BinaryNode(op=self.OP_MAP[op[0]], left=left, line=op[2], right=self.parse_shift())
        return left

    def parse_shift(self):
        left = self.parse_term()
        while op := (self.check("SHL") or self.check("SHR") or self.check("USHR")):
            left = BinaryNode(op=self.OP_MAP[op[0]], left=left, line=op[2], right=self.parse_term())
        return left

    def parse_term(self):
        left = self.parse_factor()
        while op := self.check("PLUS") or self.check("MINUS"):
            left = BinaryNode(op=self.OP_MAP[op[0]], left=left, line=op[2], right=self.parse_factor())
        return left

    def parse_factor(self):
        left = self.parse_unary()
        while op := (self.check("STAR") or self.check("SLASH") or self.check("PERCENT")):
            left = BinaryNode(op=self.OP_MAP[op[0]], left=left, line=op[2], right=self.parse_unary())
        return left

    def parse_unary(self):
        if op := self.check("BANG"):
            return UnaryNode(op="!", expr=self.parse_unary(), line=op[2])
        if op := self.check("MINUS"):
            return UnaryNode(op="-", expr=self.parse_unary(), line=op[2])
        if op := self.check("TILDE"):
            return UnaryNode(op="~", expr=self.parse_unary(), line=op[2])
        return self.parse_primary()

    def parse_postfix(self, node):
        while True:
            if self.check("DOT"):
                field = self.expect("ID")
                if self.check("LPAREN"):
                    args = self.parse_args()
                    self.expect("RPAREN")
                    node = DotCallNode(object=node, name=field[1], args=args, line=field[2])
                else:
                    node = FieldAccessNode(object=node, field=field[1], line=field[2])
            elif self.check("LBRACKET"):
                if self.check("COLON"):
                    raise ParseError("slice requires explicit start and end")
                index = self.parse_expr()
                if self.check("COLON"):
                    if self.peek_kind("RBRACKET"):
                        raise ParseError("slice requires explicit start and end")
                    end = self.parse_expr()
                    self.expect("RBRACKET")
                    node = SliceNode(base=node, start=index, end=end, line=getattr(index, "line", getattr(node, "line", 0)))
                    continue
                self.expect("RBRACKET")
                node = SubscriptNode(base=node, index=index, line=getattr(index, "line", getattr(node, "line", 0)))
            elif q := self.check("QUESTION"):
                node = NullCheckNode(expr=node, line=q[2])
            else:
                break
        return node

    def parse_primary_atom(self):
        if self.peek_kind("NEW"):
            self.expect("NEW")
            t = self.advance()
            if t[0] != "ID":
                raise ParseError(f"Expected type after new, got {t[0]}", t[2])
            if t[1] == "map":
                self.expect("LBRACKET")
                key = self.expect("ID")
                self.expect("RBRACKET")
                if key[1] != "str":
                    raise ParseError(f"only map[str]T is supported, got map[{key[1]}]", key[2])
                value = self.parse_type()
                type_name = MAP(value)
                entries = self.parse_map_entries_after_lbrace() if self.check("LBRACE") else []
                return MapInitNode(type_name=type_name, entries=entries, line=t[2])
            name = t[1]
            if self.check("LBRACKET"):
                count = None
                if not self.peek_kind("RBRACKET"):
                    count = self.parse_expr()
                self.expect("RBRACKET")
                if count is None and self.check("LBRACE"):
                    return ArrayLiteralNode(elem_type=self._type_atom(name), values=self.parse_brace_values(), line=t[2])
                return NewArrayNode(elem_type=self._type_atom(name), count=count, line=t[2])
            if self.check("LPAREN"):
                payload = self.parse_expr()
                self.expect("RPAREN")
                return UnionInitNode(type_name=name, payload=payload, line=t[2])
            if self.check("LBRACE"):
                return StructInitNode(type_name=name, fields=self.parse_named_fields_after_lbrace(), line=t[2])
            return StructInitNode(type_name=name, fields=[], line=t[2])
        if self.peek_kind("NUMBER"):
            t = self.advance()
            return LiteralNode(value=t[1], line=t[2])
        if self.peek_kind("TRUE"):
            t = self.advance()
            return BoolNode(value=1, line=t[2])
        if self.peek_kind("FALSE"):
            t = self.advance()
            return BoolNode(value=0, line=t[2])
        if self.peek_kind("CHAR"):
            t = self.advance()
            return CharNode(value=t[1], line=t[2])
        if self.peek_kind("STRING"):
            t = self.advance()
            return StringNode(value=t[1], line=t[2])
        if self.peek_kind("FSTRING"):
            t = self.advance()
            return FStringNode(parts=self.parse_fstring_parts(t[1], t[2]), line=t[2])
        if self.peek_kind("ID"):
            t = self.advance()
            name = t[1]
            if self.peek_kind("LBRACKET") and self.pos + 1 < len(self.tokens) and self.tokens[self.pos + 1][0] == "RBRACKET":
                self.advance()
                self.advance()
                elem_type = self._type_atom(name)
                if self.check("LBRACE"):
                    return ArrayLiteralNode(elem_type=elem_type, values=self.parse_brace_values(), line=t[2])
                raise ParseError("Expected array literal after type[]", t[2])
            if self.check("LPAREN"):
                args = self.parse_args()
                self.expect("RPAREN")
                return CallNode(name=name, args=args, line=t[2])
            return VarNode(name=name, line=t[2])
        if self.check("LPAREN"):
            expr = self.parse_expr()
            self.expect("RPAREN")
            return expr
        t = self.peek()
        raise ParseError(f"Unexpected token {t[0]}('{t[1]}')", t[2])

    def parse_primary(self):
        return self.parse_postfix(self.parse_primary_atom())

    def parse_fstring_parts(self, parts, line):
        parsed = []
        for kind, value, _dump_value in parts:
            if kind == "text":
                if value:
                    parsed.append(FStringTextPart(value))
                continue
            if kind == "expr":
                from lexer import lex
                p = Parser(lex(value))
                expr = p.parse_expr()
                if p.peek()[0] != "EOF":
                    t = p.peek()
                    raise ParseError(f"Unexpected token {t[0]}('{t[1]}') in f-string expression", line)
                parsed.append(FStringExprPart(expr))
                continue
            raise ParseError(f"Unknown f-string part {kind}", line)
        return parsed


    def parse_named_fields_after_lbrace(self):
        fields = []
        self.skip_newlines()
        while not self.peek_kind("RBRACE"):
            name = self.expect("ID")
            self.expect("COLON")
            value = self.parse_expr()
            fields.append((name[1], value))
            if self.check("COMMA"):
                self.skip_newlines()
            elif self.peek_kind("NEWLINE"):
                self.skip_newlines()
            elif not self.peek_kind("RBRACE"):
                t = self.peek()
                raise ParseError("Expected comma or newline in struct initializer", t[2])
        self.expect("RBRACE")
        return fields

    def parse_brace_values(self):
        values = []
        self.skip_newlines()
        while not self.peek_kind("RBRACE"):
            values.append(self.parse_expr())
            if self.check("COMMA"):
                self.skip_newlines()
            elif self.peek_kind("NEWLINE"):
                self.skip_newlines()
            elif not self.peek_kind("RBRACE"):
                t = self.peek()
                raise ParseError("Expected comma or newline in array literal", t[2])
        self.expect("RBRACE")
        return values

    def parse_map_entries_after_lbrace(self):
        entries = []
        self.skip_newlines()
        while not self.peek_kind("RBRACE"):
            key = self.parse_expr()
            self.expect("COLON")
            value = self.parse_expr()
            entries.append((key, value))
            if self.check("COMMA"):
                self.skip_newlines()
            elif self.peek_kind("NEWLINE"):
                self.skip_newlines()
            elif not self.peek_kind("RBRACE"):
                t = self.peek()
                raise ParseError("Expected comma or newline in map initializer", t[2])
        self.expect("RBRACE")
        return entries

    def parse_args(self):
        args = []
        if not self.peek_kind("RPAREN"):
            args.append(self.parse_expr())
            while self.check("COMMA"):
                args.append(self.parse_expr())
        return args


def _dump_line(depth, text):
    return f"{'  ' * depth}{text}"


def _type_suffix(node):
    typ = getattr(node, "resolved_type", None)
    return f" : {typ}" if typ is not None else ""


def _decl_type_suffix(node, source_type):
    resolved = _type_suffix(node)
    if resolved:
        return resolved
    return f" : {source_type}" if source_type else ""


def dump_ast_lines(node, depth=0):
    out = []

    def emit(text):
        out.append(_dump_line(depth, text))

    if isinstance(node, ProgramNode):
        emit("Program")
        for struct in node.structs:
            out.extend(dump_ast_lines(struct, depth + 1))
        for union in node.unions:
            out.extend(dump_ast_lines(union, depth + 1))
        for glob in node.globals:
            out.extend(dump_ast_lines(glob, depth + 1))
        for func in node.funcs:
            out.extend(dump_ast_lines(func, depth + 1))
    elif isinstance(node, StructDefNode):
        emit(f"StructDef {node.name}")
        for field in node.fields:
            out.extend(dump_ast_lines(field, depth + 1))
    elif isinstance(node, StructField):
        emit(f"StructField {node.name}{_decl_type_suffix(node, node.type)}")
    elif isinstance(node, UnionDefNode):
        emit(f"UnionDef {node.name}")
        for member in node.members:
            out.append(_dump_line(depth + 1, f"UnionMember {member}"))
    elif isinstance(node, FunDefNode):
        if node.method_name:
            emit(f"Method {node.receiver_type}.{node.method_name}{_decl_type_suffix(node, node.ret_type)}")
        else:
            emit(f"FunDef {node.name}{_decl_type_suffix(node, node.ret_type)}")
        for param in node.params:
            out.extend(dump_ast_lines(param, depth + 1))
        out.extend(dump_ast_lines(node.body, depth + 1))
    elif isinstance(node, Param):
        emit(f"Param {node.name}{_decl_type_suffix(node, node.type)}")
    elif isinstance(node, BlockNode):
        emit("Block")
        for stmt in node.stmts:
            out.extend(dump_ast_lines(stmt, depth + 1))
        if node.value_expr is not None:
            out.append(_dump_line(depth + 1, "BlockValue"))
            out.extend(dump_ast_lines(node.value_expr, depth + 2))
    elif isinstance(node, ReturnNode):
        emit("Return")
        if node.expr is not None:
            out.extend(dump_ast_lines(node.expr, depth + 1))
    elif isinstance(node, LetNode):
        emit(f"Let {node.name}{_decl_type_suffix(node, node.var_type)}")
        if node.value is not None:
            out.extend(dump_ast_lines(node.value, depth + 1))
    elif isinstance(node, AssignNode):
        emit(f"Assign {node.name}")
        out.extend(dump_ast_lines(node.value, depth + 1))
    elif isinstance(node, AssignOpNode):
        emit(f"AssignOp {node.op}")
        out.extend(dump_ast_lines(node.target, depth + 1))
        out.extend(dump_ast_lines(node.value, depth + 1))
    elif isinstance(node, FieldSetNode):
        emit(f"FieldSet {node.field}")
        out.extend(dump_ast_lines(node.value, depth + 1))
        out.extend(dump_ast_lines(node.object, depth + 1))
    elif isinstance(node, SubscriptAssignNode):
        emit("SubscriptAssign")
        out.extend(dump_ast_lines(node.value, depth + 1))
        out.extend(dump_ast_lines(node.base, depth + 1))
        out.extend(dump_ast_lines(node.index, depth + 1))
    elif isinstance(node, IfNode):
        emit("If")
        out.extend(dump_ast_lines(node.then_block, depth + 1))
        if node.else_block is not None:
            out.extend(dump_ast_lines(node.else_block, depth + 1))
        out.extend(dump_ast_lines(node.cond, depth + 1))
    elif isinstance(node, WhileNode):
        emit("While")
        out.extend(dump_ast_lines(node.body, depth + 1))
        out.extend(dump_ast_lines(node.cond, depth + 1))
    elif isinstance(node, BreakNode):
        emit("Break")
    elif isinstance(node, ContinueNode):
        emit("Continue")
    elif isinstance(node, ForRangeNode):
        emit(f"ForRange {node.name}{_type_suffix(node)}")
        out.extend(dump_ast_lines(node.body, depth + 1))
        out.extend(dump_ast_lines(node.start, depth + 1))
        out.extend(dump_ast_lines(node.end, depth + 1))
    elif isinstance(node, ForInNode):
        emit(f"ForIn {node.name}{_type_suffix(node)}")
        out.extend(dump_ast_lines(node.body, depth + 1))
        out.extend(dump_ast_lines(node.source, depth + 1))
    elif isinstance(node, PanicNode):
        emit("Panic")
        out.extend(dump_ast_lines(node.message, depth + 1))
    elif isinstance(node, AssertNode):
        emit("Assert")
        out.extend(dump_ast_lines(node.cond, depth + 1))
        if node.message is not None:
            out.extend(dump_ast_lines(node.message, depth + 1))
    elif isinstance(node, MatchNode):
        emit("Match")
        out.extend(dump_ast_lines(node.expr, depth + 1))
        for case in node.cases:
            out.extend(dump_ast_lines(case, depth + 1))
    elif isinstance(node, MatchCase):
        if node.is_else:
            emit("MatchCase _")
        elif node.variant_name:
            emit(f"MatchCase {node.variant_name} {node.binding_name}")
        else:
            emit("MatchCase")
        if node.pattern is not None:
            out.extend(dump_ast_lines(node.pattern, depth + 1))
        for field, bind in node.bindings:
            emit(f"  MatchBinding {field} : {bind}")
        out.extend(dump_ast_lines(node.body, depth + 1))
    elif isinstance(node, ExprStmtNode):
        emit("ExprStmt")
        out.extend(dump_ast_lines(node.expr, depth + 1))
    elif isinstance(node, LiteralNode):
        emit(f"Literal {node.value}{_type_suffix(node)}")
    elif isinstance(node, CharNode):
        emit(f"Char {node.value}{_type_suffix(node)}")
    elif isinstance(node, BoolNode):
        emit(f"Bool {node.value}{_type_suffix(node)}")
    elif isinstance(node, StringNode):
        emit(f"String {node.value}{_type_suffix(node)}")
    elif isinstance(node, FStringNode):
        emit(f"FString{_type_suffix(node)}")
        for part in node.parts:
            if isinstance(part, FStringTextPart):
                emit(f"  FStringText {part.value}")
            elif isinstance(part, FStringExprPart):
                out.extend(dump_ast_lines(part.expr, depth + 1))
    elif isinstance(node, VarNode):
        emit(f"Var {node.name}{_type_suffix(node)}")
    elif isinstance(node, CallNode):
        suffix = f" : {node.namespace}" if node.namespace else ""
        emit(f"Call {node.name}{suffix}{_type_suffix(node)}")
        for arg in node.args:
            out.extend(dump_ast_lines(arg, depth + 1))
    elif isinstance(node, DotCallNode):
        emit(f"DotCall {node.name}{_type_suffix(node)}")
        out.extend(dump_ast_lines(node.object, depth + 1))
        for arg in node.args:
            out.extend(dump_ast_lines(arg, depth + 1))
    elif isinstance(node, BinaryNode):
        emit(f"Binary {node.op}{_type_suffix(node)}")
        out.extend(dump_ast_lines(node.left, depth + 1))
        out.extend(dump_ast_lines(node.right, depth + 1))
    elif isinstance(node, UnaryNode):
        emit(f"Unary {node.op}{_type_suffix(node)}")
        out.extend(dump_ast_lines(node.expr, depth + 1))
    elif isinstance(node, FieldAccessNode):
        emit(f"FieldAccess {node.field}{_type_suffix(node)}")
        out.extend(dump_ast_lines(node.object, depth + 1))
    elif isinstance(node, NullCheckNode):
        emit(f"NullCheck{_type_suffix(node)}")
        out.extend(dump_ast_lines(node.expr, depth + 1))
    elif isinstance(node, SubscriptNode):
        emit(f"Subscript{_type_suffix(node)}")
        out.extend(dump_ast_lines(node.base, depth + 1))
        out.extend(dump_ast_lines(node.index, depth + 1))
    elif isinstance(node, SliceNode):
        emit(f"Slice{_type_suffix(node)}")
        out.extend(dump_ast_lines(node.base, depth + 1))
        if node.start is not None:
            out.extend(dump_ast_lines(node.start, depth + 1))
        if node.end is not None:
            out.extend(dump_ast_lines(node.end, depth + 1))
    elif isinstance(node, NewArrayNode):
        emit(f"NewArray : {node.elem_type}{_type_suffix(node)}")
        if node.count is not None:
            out.extend(dump_ast_lines(node.count, depth + 1))
    elif isinstance(node, StructInitNode):
        emit(f"StructInit {node.type_name}{_type_suffix(node)}")
        for field, value in node.fields:
            out.append(_dump_line(depth + 1, f"InitField {field}"))
            out.extend(dump_ast_lines(value, depth + 2))
    elif isinstance(node, UnionInitNode):
        emit(f"UnionInit {node.type_name}{_type_suffix(node)}")
        out.extend(dump_ast_lines(node.payload, depth + 1))
    elif isinstance(node, ArrayLiteralNode):
        emit(f"ArrayLiteral : {node.elem_type}{_type_suffix(node)}")
        for value in node.values:
            out.extend(dump_ast_lines(value, depth + 1))
    elif isinstance(node, MapInitNode):
        emit(f"MapInit : {node.type_name}{_type_suffix(node)}")
        for key, value in node.entries:
            out.append(_dump_line(depth + 1, "Key"))
            out.extend(dump_ast_lines(key, depth + 2))
            out.append(_dump_line(depth + 1, "Value"))
            out.extend(dump_ast_lines(value, depth + 2))
    else:
        raise TypeError(f"unsupported AST node: {type(node).__name__}")

    return out


def dump_ast_text(node):
    return "\n".join(dump_ast_lines(node)) + "\n"
