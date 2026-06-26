"""
Epic v0 compiler — M1: minimal pipeline
Input:  .ep source
Output: .exe via nasm + link.py

Usage: python epicc.py <file.ep>
"""

import sys
import os
import subprocess
import re

# ── paths ────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.join(SCRIPT_DIR, "tools")
NASM = os.path.join(TOOLS_DIR, "nasm.exe")
LLD_LINK = os.path.join(TOOLS_DIR, "lld-link.exe")
LINK_PY = os.path.join(SCRIPT_DIR, "link.py")
SDK_LIB = r"C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\um\x64"


# ═══════════════════════════════════════════════════════════════════════════
#  Lexer
# ═══════════════════════════════════════════════════════════════════════════

TOKEN_SPEC = [
    ("FUN",       r'\bfun\b'),
    ("RETURN",    r'\breturn\b'),
    ("IF",        r'\bif\b'),
    ("ELSE",      r'\belse\b'),
    ("WHILE",     r'\bwhile\b'),
    ("STRUCT",    r'\bstruct\b'),
    ("LET",       r'\blet\b'),
    ("TYPE_I8",   r'\bi8\b'),
    ("TYPE_I64",  r'\bi64\b'),
    ("ID",        r'[a-zA-Z_][a-zA-Z0-9_]*'),
    ("NUMBER",    r'[0-9]+'),
    ("ARROW",     r'->'),
    ("EQEQ",      r'=='),
    ("NEQ",       r'!='),
    ("LTE",       r'<='),
    ("GTE",       r'>='),
    ("AND",       r'&&'),
    ("OR",        r'\|\|'),
    ("LT",        r'<'),
    ("GT",        r'>'),
    ("PLUS",      r'\+'),
    ("MINUS",     r'-'),
    ("STAR",      r'\*'),
    ("SLASH",     r'/'),
    ("PERCENT",   r'%'),
    ("DOT",       r'\.'),
    ("BANG",      r'!'),
    ("ASSIGN",    r'='),
    ("LBRACKET",  r'\['),
    ("RBRACKET",  r'\]'),
    ("LPAREN",    r'\('),
    ("RPAREN",    r'\)'),
    ("LBRACE",    r'\{'),
    ("RBRACE",    r'\}'),
    ("SEMICOLON", r';'),
    ("COMMA",     r','),
    ("COLON",     r':'),
    ("CHAR",      r"'[^']'"),
    ("STRING",    r'"[^"]*"'),
    ("COMMENT",   r'#[^\n]*'),
    ("WHITESPACE", r'[ \t\n\r]+'),
]

TOKEN_RE = re.compile(
    "|".join(f"(?P<{name}>{pattern})" for name, pattern in TOKEN_SPEC),
    re.DOTALL,
)


class LexError(Exception):
    def __init__(self, msg, line):
        super().__init__(f"Lex error line {line}: {msg}")
        self.line = line


def lex(source_text):
    """Tokenize source text, yield (name, value, line) tuples."""
    tokens = []
    lines = source_text.split("\n")
    line_numbers = []
    pos = 0
    for i, line in enumerate(lines, 1):
        for _ in range(len(line) + 1):  # +1 for newline
            if pos < len(source_text):
                line_numbers.append(i)
            pos += 1

    for m in TOKEN_RE.finditer(source_text):
        kind = m.lastgroup
        value = m.group()
        line = 1
        if m.start() < len(line_numbers):
            line = line_numbers[m.start()]
        if kind == "WHITESPACE":
            continue
        if kind == "COMMENT":
            continue
        if kind == "NUMBER":
            value = int(value)
        if kind == "STRING":
            value = value[1:-1]  # strip quotes
        if kind == "CHAR":
            value = ord(value[1])  # 'X' → ASCII code
        tokens.append((kind, value, line))
    return tokens


# ═══════════════════════════════════════════════════════════════════════════
#  Parser
# ═══════════════════════════════════════════════════════════════════════════

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
        return {"type": "program", "funcs": funcs, "structs": structs}

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
            fields.append({"name": fname[1], "type": ftype})
        self.expect("RBRACE")
        return {"type": "struct_def", "name": name[1], "fields": fields}

    def parse_fn_def(self):
        self.expect("FUN")
        name = self.expect("ID")
        self.expect("LPAREN")
        params = self.parse_params()
        self.expect("RPAREN")
        self.expect("ARROW")
        ret_type = self.parse_type()
        body = self.parse_block()
        return {
            "type": "fn_def",
            "name": name[1],
            "params": params,
            "ret_type": ret_type,
            "body": body,
            "line": name[2],
        }

    def parse_params(self):
        params = []
        if not self.peek_kind("ID"):
            return params
        while True:
            name = self.expect("ID")
            self.expect("COLON")
            typ = self.parse_type()
            params.append({"name": name[1], "type": typ})
            if not self.check("COMMA"):
                break
        return params

    def parse_type(self):
        t = self.advance()
        if t[0] in ("TYPE_I64", "TYPE_I8"):
            return t[1]  # "i64" or "i8"
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
        return {"type": "block", "stmts": stmts}

    # ── statements ────────────────────────────────────────────────────

    EXPR_FIRST = {"NUMBER", "STRING", "ID", "LPAREN", "MINUS", "BANG"}

    def _is_assignment(self):
        """Look ahead past ID(.ID)* to see if = or [ follows."""
        i = self.pos + 1
        while i < len(self.tokens):
            kind = self.tokens[i][0]
            if kind == "DOT":
                i += 2
                continue
            return kind in ("ASSIGN", "LBRACKET")
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
        return {"type": "return", "expr": expr, "line": line}

    def parse_let_stmt(self):
        self.expect("LET")
        name = self.expect("ID")
        self.expect("COLON")
        typ = self.parse_type()
        # Check for array: let buf: i8[4096];
        if self.check("LBRACKET"):
            size_tok = self.expect("NUMBER")
            self.expect("RBRACKET")
            self.expect("SEMICOLON")
            return {"type": "array_decl", "name": name[1], "elem_type": typ, "size": size_tok[1]}
        value = None
        if self.check("ASSIGN"):
            value = self.parse_expr()
        self.expect("SEMICOLON")
        return {"type": "let", "name": name[1], "var_type": typ, "value": value}

    def parse_assign_stmt(self):
        name = self.expect("ID")
        # Check for array assign: buf[i] = expr;
        if self.check("LBRACKET"):
            index = self.parse_expr()
            self.expect("RBRACKET")
            self.expect("ASSIGN")
            value = self.parse_expr()
            self.expect("SEMICOLON")
            return {"type": "array_set", "name": name[1], "index": index, "value": value}
        # Check for field assign: obj.field = expr;
        if self.check("DOT"):
            field = self.expect("ID")
            self.expect("ASSIGN")
            value = self.parse_expr()
            self.expect("SEMICOLON")
            return {"type": "field_set",
                    "object": {"type": "var", "name": name[1]},
                    "field": field[1], "value": value}
        # Scalar assign: x = expr;
        self.expect("ASSIGN")
        value = self.parse_expr()
        self.expect("SEMICOLON")
        return {"type": "assign", "name": name[1], "value": value}

    def parse_if_stmt(self):
        self.expect("IF")
        cond = self.parse_expr()
        then_block = self.parse_block()
        else_block = None
        if self.check("ELSE"):
            else_block = self.parse_block()
        return {"type": "if", "cond": cond, "then_block": then_block, "else_block": else_block}

    def parse_while_stmt(self):
        self.expect("WHILE")
        cond = self.parse_expr()
        body = self.parse_block()
        return {"type": "while", "cond": cond, "body": body}

    def parse_expr_stmt(self):
        expr = self.parse_expr()
        self.expect("SEMICOLON")
        return {"type": "expr_stmt", "expr": expr}

    # ── expressions ───────────────────────────────────────────────────

    def parse_expr(self):
        return self.parse_logic_or()

    def parse_logic_or(self):
        left = self.parse_logic_and()
        while self.check("OR"):
            right = self.parse_logic_and()
            left = {"type": "binary", "op": "||", "left": left, "right": right}
        return left

    def parse_logic_and(self):
        left = self.parse_equality()
        while self.check("AND"):
            right = self.parse_equality()
            left = {"type": "binary", "op": "&&", "left": left, "right": right}
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
            left = {"type": "binary", "op": self.OP_MAP[op[0]], "left": left, "right": self.parse_comparison()}
        return left

    def parse_comparison(self):
        left = self.parse_term()
        while op := (self.check("LT") or self.check("GT")
                     or self.check("LTE") or self.check("GTE")):
            left = {"type": "binary", "op": self.OP_MAP[op[0]], "left": left, "right": self.parse_term()}
        return left

    def parse_term(self):
        left = self.parse_factor()
        while op := self.check("PLUS") or self.check("MINUS"):
            left = {"type": "binary", "op": self.OP_MAP[op[0]], "left": left, "right": self.parse_factor()}
        return left

    def parse_factor(self):
        left = self.parse_unary()
        while op := (self.check("STAR") or self.check("SLASH") or self.check("PERCENT")):
            left = {"type": "binary", "op": self.OP_MAP[op[0]], "left": left, "right": self.parse_unary()}
        return left

    def parse_unary(self):
        if self.check("MINUS"):
            return {"type": "unary", "op": "-", "expr": self.parse_unary()}
        if self.check("BANG"):
            return {"type": "unary", "op": "!", "expr": self.parse_unary()}
        return self.parse_primary()

    def parse_primary(self):
        if self.peek_kind("NUMBER"):
            t = self.advance()
            return {"type": "literal", "value": t[1]}
        if self.peek_kind("CHAR"):
            t = self.advance()
            return {"type": "literal", "value": t[1]}
        if self.peek_kind("STRING"):
            t = self.advance()
            return {"type": "string", "value": t[1]}
        if self.peek_kind("ID"):
            t = self.advance()
            name = t[1]
            if self.check("LPAREN"):
                args = self.parse_args()
                self.expect("RPAREN")
                node = {"type": "call", "name": name, "args": args}
            elif self.check("LBRACKET"):
                index = self.parse_expr()
                self.expect("RBRACKET")
                node = {"type": "array_get", "name": name, "index": index}
            else:
                node = {"type": "var", "name": name}
            # Field access chain: a.b.c
            while self.check("DOT"):
                field = self.expect("ID")
                node = {"type": "field_access", "object": node, "field": field[1]}
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


# ═══════════════════════════════════════════════════════════════════════════
#  Emitter (AST → NASM assembly)
# ═══════════════════════════════════════════════════════════════════════════

class Emitter:
    def __init__(self, out_path):
        self.out = open(out_path, "w")
        self.builtins = {"exit", "puti", "putc", "putstr",
                         "fopen", "fread", "fwrite", "fclose",
                         "strcmp", "strcpy"}
        self.local_offset = {}  # var name → stack offset relative to rbp
        self.local_count = 0
        self.local_types = {}
        self.label_counter = 0
        self.current_fn = ""
        self.alloc_size = 0     # bytes allocated after push rbp / mov rbp, rsp
        self.strings = {}       # literal text → label name
        self.string_counter = 0
        self.local_bytes = 0    # track variable allocation in pre-scan
        self.structs = {}       # name → {fields: [{name, type, offset}], size}

    def emit(self, s):
        self.out.write(s + "\n")

    def fresh_label(self):
        self.label_counter += 1
        return f"L{self.label_counter}"

    def close(self):
        self.out.close()

    # ── program header ──────────────────────────────────────────────────

    def emit_program(self, ast):
        self.emit("global _start")
        self.emit("extern ExitProcess")
        self.emit("extern GetStdHandle")
        self.emit("extern WriteFile")
        self.emit("extern CreateFileA")
        self.emit("extern ReadFile")
        self.emit("extern CloseHandle")
        self.emit("extern lstrcmpA")
        self.emit("extern lstrcpyA")
        self.emit("extern lstrlenA")
        self.emit("default rel")
        self.emit("")

        # Compute struct layouts first
        self._compute_struct_layouts(ast)

        # Collect arrays and strings from AST
        self.arrays = {}
        self.strings = {}
        self.string_counter = 0
        for func in ast.get("funcs", []):
            self._collect_from_block(func.get("body", {}))

        self.emit("section .data")
        self.emit("    _buf times 32 db 0")
        self.emit("    _buf_end db 0")
        self.emit("    _written dd 0")
        for name, info in self.arrays.items():
            self.emit(f"{name}: resb {info['size']}")
        # Emit string literals (null-terminated)
        for label, text in sorted(self.strings.items(), key=lambda x: x[0]):
            escaped = text.replace("\\", "\\\\").replace('"', '"')
            self.emit(f'{label}: db "{escaped}", 0')
        self.emit("")
        self.emit("section .text")
        self.emit("")

        for func in ast.get("funcs", []):
            self.emit_fn_def(func)

    def _collect_from_block(self, block):
        """Recursively collect arrays and strings from AST."""
        for stmt in block.get("stmts", []):
            if stmt["type"] == "array_decl":
                self.arrays[stmt["name"]] = {
                    "elem_type": stmt["elem_type"],
                    "size": stmt["size"]
                }
            elif stmt["type"] == "if":
                self._collect_from_block(stmt["then_block"])
                if stmt.get("else_block"):
                    self._collect_from_block(stmt["else_block"])
            elif stmt["type"] == "while":
                self._collect_from_block(stmt["body"])
            # Collect strings from expressions
            self._collect_strings(stmt)

    def _collect_strings(self, node):
        """Recursively find string literals and register them."""
        if isinstance(node, dict):
            if node.get("type") == "string":
                self.get_string_label(node["value"])
            for v in node.values():
                self._collect_strings(v)
        elif isinstance(node, list):
            for item in node:
                self._collect_strings(item)

    def get_string_label(self, text):
        # Check if text already has a label
        for lbl, txt in self.strings.items():
            if txt == text:
                return lbl
        # New string
        self.string_counter += 1
        label = f"_str_{self.string_counter}"
        self.strings[label] = text
        return label

    # ── function definition ────────────────────────────────────────────

    def emit_fn_def(self, fn):
        self.local_offset = {}
        self.local_types = {}
        self.local_bytes = 0
        name = fn["name"]
        self.current_fn = name
        params = fn["params"]
        body = fn["body"]

        # Pre-scan: allocate stack slots for let declarations
        self._pre_scan_block(body)

        # Entry label: main → _start
        label = "_start" if name == "main" else name
        self.emit(f"{label}:")

        # Prologue: dynamic frame, 16-byte aligned (include 32-byte shadow)
        self.alloc_size = ((self.local_bytes + 32 + 15) // 16) * 16
        self.emit("    push rbp")
        self.emit("    mov rbp, rsp")
        self.emit(f"    sub rsp, {self.alloc_size}")

        # Map params from registers to local slots
        param_regs = ["rcx", "rdx", "r8", "r9"]
        param_low = ["cl", "dl", "r8b", "r9b"]  # low-byte names
        for i, p in enumerate(params):
            slot = self.get_var_slot(p["name"])
            ptype = p.get("type", "i64")
            self.local_types[p["name"]] = ptype
            if ptype == "i8":
                self.emit(f"    mov [rbp{slot:+d}], {param_low[i]}")
            else:
                self.emit(f"    mov [rbp{slot:+d}], {param_regs[i]}")

        # Body
        self.emit_block(body)

        # Epilogue (only for non-main; main never returns via ret)
        if name != "main":
            ep_label = f"{name}_ep"
            self.current_ep_label = ep_label
            self.emit(f"{ep_label}:")
            self.emit("    mov rsp, rbp")
            self.emit("    pop rbp")
            self.emit("    ret")

        self.emit("")

    # ── frame helpers ──────────────────────────────────────────────────

    def get_var_slot(self, name, typ=None):
        if name not in self.local_offset:
            size = self._type_size(typ) if typ else 8
            # 8-byte align
            if self.local_bytes % 8 != 0:
                self.local_bytes += 8 - (self.local_bytes % 8)
            self.local_bytes += size
            self.local_offset[name] = -self.local_bytes
        return self.local_offset[name]

    def _type_size(self, typ):
        if typ == "i64":
            return 8
        if typ == "i8":
            return 1
        if typ in self.structs:
            return self.structs[typ]["size"]
        return 8  # unknown, assume i64

    def _compute_struct_layouts(self, ast):
        self.structs = {}
        for s in ast.get("structs", []):
            fields = []
            offset = 0
            max_align = 1
            for f in s["fields"]:
                fsize = self._type_size(f["type"])
                falign = 8 if f["type"] in self.structs else fsize
                if offset % falign != 0:
                    offset += falign - (offset % falign)
                fields.append({"name": f["name"], "type": f["type"], "offset": offset})
                offset += fsize
                max_align = max(max_align, falign)
            if offset % max_align != 0:
                offset += max_align - (offset % max_align)
            self.structs[s["name"]] = {"fields": fields, "size": offset}

    def _pre_scan_block(self, block):
        """Allocate stack slots for all let declarations."""
        for stmt in block.get("stmts", []):
            if stmt["type"] == "let":
                self.get_var_slot(stmt["name"], stmt.get("var_type"))
            elif stmt["type"] == "if":
                self._pre_scan_block(stmt["then_block"])
                if stmt.get("else_block"):
                    self._pre_scan_block(stmt["else_block"])
            elif stmt["type"] == "while":
                self._pre_scan_block(stmt["body"])

    # ── statements ─────────────────────────────────────────────────────

    def emit_block(self, block):
        for stmt in block.get("stmts", []):
            self.emit_stmt(stmt)

    def emit_stmt(self, stmt):
        t = stmt["type"]
        if t == "return":
            self.emit_return(stmt)
        elif t == "expr_stmt":
            self.emit_expr(stmt["expr"])
        elif t == "let":
            self.emit_let(stmt)
        elif t == "array_decl":
            pass  # already emitted in .data section
        elif t == "array_set":
            self.emit_array_set(stmt)
        elif t == "if":
            self.emit_if(stmt)
        elif t == "while":
            self.emit_while(stmt)
        elif t == "assign":
            self.emit_assign(stmt)
        elif t == "field_set":
            self.emit_field_set(stmt)
        else:
            raise RuntimeError(f"Unknown stmt type: {t}")

    def emit_return(self, stmt):
        expr = stmt["expr"]
        if self.current_fn == "main":
            self.emit_expr(expr)
            self.emit("    mov ecx, eax")
            self.emit("    call ExitProcess")
        else:
            self.emit_expr(expr)
            ep_label = getattr(self, "current_ep_label", f"{self.current_fn}_ep")
            self.emit(f"    jmp {ep_label}")

    def emit_let(self, stmt):
        name = stmt["name"]
        var_type = stmt.get("var_type", "i64")
        slot = self.get_var_slot(name, var_type)
        self.local_types[name] = var_type
        value = stmt.get("value")
        if value is None:
            return  # declaration without initializer
        self.emit_expr(value)
        if var_type == "i8":
            self.emit(f"    mov [rbp{slot:+d}], al")
        else:
            self.emit(f"    mov [rbp{slot:+d}], rax")

    def emit_if(self, stmt):
        else_label = self.fresh_label()
        end_label = self.fresh_label()
        self.emit_expr(stmt["cond"])
        self.emit("    test rax, rax")
        if stmt.get("else_block"):
            self.emit(f"    jz {else_label}")
        else:
            self.emit(f"    jz {end_label}")
        self.emit_block(stmt["then_block"])
        if stmt.get("else_block"):
            self.emit(f"    jmp {end_label}")
            self.emit(f"{else_label}:")
            self.emit_block(stmt["else_block"])
        self.emit(f"{end_label}:")

    def emit_while(self, stmt):
        start_label = self.fresh_label()
        end_label = self.fresh_label()
        self.emit(f"{start_label}:")
        self.emit_expr(stmt["cond"])
        self.emit("    test rax, rax")
        self.emit(f"    jz {end_label}")
        self.emit_block(stmt["body"])
        self.emit(f"    jmp {start_label}")
        self.emit(f"{end_label}:")

    def emit_array_get(self, expr):
        """result = buf[i]"""
        name = expr["name"]
        info = self.arrays.get(name)
        if info is None:
            raise RuntimeError(f"Undefined array: {name}")
        elem_type = info["elem_type"]
        self.emit_expr(expr["index"])
        self.emit(f"    lea rcx, [{name}]")
        if elem_type == "i8":
            self.emit("    movsx rax, byte [rcx + rax]")
        else:
            self.emit("    mov rax, [rcx + rax*8]")

    def emit_array_set(self, stmt):
        """buf[i] = expr;"""
        name = stmt["name"]
        info = self.arrays.get(name)
        if info is None:
            raise RuntimeError(f"Undefined array: {name}")
        elem_type = info["elem_type"]
        self.emit_expr(stmt["value"])
        self.emit("    push rax")  # save value
        self.emit_expr(stmt["index"])
        self.emit(f"    lea rcx, [{name}]")
        self.emit("    add rcx, rax")
        self.emit("    pop rax")  # restore value
        if elem_type == "i8":
            self.emit("    mov [rcx], al")
        else:
            self.emit("    mov [rcx], rax")

    def emit_assign(self, stmt):
        name = stmt["name"]
        self.emit_expr(stmt["value"])
        slot = self.local_offset.get(name)
        if slot is None:
            raise RuntimeError(f"Undefined variable: {name}")
        var_type = self.local_types.get(name, "i64")
        if var_type == "i8":
            self.emit(f"    mov [rbp{slot:+d}], al")
        else:
            self.emit(f"    mov [rbp{slot:+d}], rax")

    # ── expressions ────────────────────────────────────────────────────

    def emit_expr(self, expr):
        t = expr["type"]
        if t == "literal":
            self.emit(f"    mov rax, {expr['value']}")
        elif t == "string":
            label = self.get_string_label(expr["value"])
            self.emit(f"    lea rax, [{label}]")
        elif t == "var":
            name = expr["name"]
            # Check if it's an array name
            if name in self.arrays:
                self.emit(f"    lea rax, [{name}]")
            else:
                slot = self.local_offset.get(name)
                if slot is None:
                    raise RuntimeError(f"Undefined variable: {name}")
                var_type = self.local_types.get(name, "i64")
                if var_type == "i8":
                    self.emit(f"    movsx rax, byte [rbp{slot:+d}]")
                else:
                    self.emit(f"    mov rax, [rbp{slot:+d}]")
        elif t == "call":
            self.emit_call(expr)
        elif t == "array_get":
            self.emit_array_get(expr)
        elif t == "binary":
            self.emit_binary(expr)
        elif t == "unary":
            self.emit_unary(expr)
        elif t == "field_access":
            self.emit_field_access(expr)
        else:
            raise RuntimeError(f"Unknown expr type: {t}")

    def emit_call(self, expr):
        name = expr["name"]
        args = expr["args"]

        if name in self.builtins:
            if name == "exit":
                self.emit_expr(args[0])
                self.emit("    mov ecx, eax")
                self.emit("    call ExitProcess")
            elif name == "puti":
                self.emit_expr(args[0])
                self.emit("    call _itoa_write")
            elif name == "putc":
                self.emit_expr(args[0])
                self.emit("    mov [_buf], al")
                self.emit("    mov ecx, -11")
                self.emit("    call GetStdHandle")
                self.emit("    mov rcx, rax")
                self.emit("    lea rdx, [_buf]")
                self.emit("    mov r8, 1")
                self.emit("    lea r9, [_written]")
                self.emit("    sub rsp, 40")
                self.emit("    mov qword [rsp+32], 0")
                self.emit("    call WriteFile")
                self.emit("    add rsp, 40")
            elif name == "putstr":
                # putstr(ptr): write null-terminated string to stdout
                # Save params to stack before GetStdHandle clobbers volatile regs
                self.emit_expr(args[0])  # rax = ptr
                self.emit("    mov rcx, rax")
                self.emit("    call lstrlenA")  # rax = length
                self.emit("    push rax")       # save length on stack
                self.emit_expr(args[0])  # rax = ptr
                self.emit("    push rax")       # save ptr on stack
                self.emit("    mov ecx, -11")
                self.emit("    call GetStdHandle")  # rax = handle
                self.emit("    mov rcx, rax")
                self.emit("    pop rdx")        # restore ptr → rdx
                self.emit("    pop r8")         # restore length → r8
                self.emit("    lea r9, [_written]")
                self.emit("    sub rsp, 48")
                self.emit("    mov qword [rsp+32], 0")
                self.emit("    call WriteFile")
                self.emit("    add rsp, 48")
            elif name == "strcmp":
                # strcmp(ptr, "literal") → lstrcmpA(ptr, literal_addr)
                self.emit_expr(args[1])
                self.emit("    mov rdx, rax")
                self.emit_expr(args[0])
                self.emit("    mov rcx, rax")
                self.emit("    sub rsp, 40")
                self.emit("    call lstrcmpA")
                self.emit("    add rsp, 40")
            elif name == "strcpy":
                # strcpy(dst_ptr, "literal") → lstrcpyA(dst_ptr, literal_addr)
                self.emit_expr(args[1])
                self.emit("    mov rdx, rax")
                self.emit_expr(args[0])
                self.emit("    mov rcx, rax")
                self.emit("    sub rsp, 40")
                self.emit("    call lstrcpyA")
                self.emit("    add rsp, 40")
            elif name == "fopen":
                # fopen(path_ptr, mode) → CreateFileA
                rl = self.fresh_label()  # read label
                wl = self.fresh_label()  # write skip label (after write path)
                dl = self.fresh_label()  # done label
                self.emit_expr(args[1])  # rax = mode
                self.emit("    test rax, rax")
                self.emit(f"    jz {rl}")
                # Write mode
                self.emit_expr(args[0])  # rax = path
                self.emit("    mov rcx, rax")
                self.emit("    mov edx, 0x40000000")  # GENERIC_WRITE
                self.emit("    xor r8d, r8d")
                self.emit("    xor r9d, r9d")
                self.emit("    sub rsp, 56")
                self.emit("    mov dword [rsp+32], 2")       # CREATE_ALWAYS
                self.emit("    mov dword [rsp+40], 0x80")
                self.emit("    mov qword [rsp+48], 0")
                self.emit("    call CreateFileA")
                self.emit("    add rsp, 56")
                self.emit(f"    jmp {dl}")
                self.emit(f"{rl}:")
                self.emit_expr(args[0])  # rax = path
                self.emit("    mov rcx, rax")
                self.emit("    mov edx, 0x80000000")  # GENERIC_READ
                self.emit("    mov r8d, 1")
                self.emit("    xor r9d, r9d")
                self.emit("    sub rsp, 56")
                self.emit("    mov dword [rsp+32], 3")       # OPEN_EXISTING
                self.emit("    mov dword [rsp+40], 0x80")
                self.emit("    mov qword [rsp+48], 0")
                self.emit("    call CreateFileA")
                self.emit("    add rsp, 56")
                self.emit(f"{dl}:")
            elif name == "fread":
                # fread(fd, buf_ptr, len) → ReadFile
                self.emit_expr(args[2])  # len
                self.emit("    mov r8, rax")
                self.emit_expr(args[1])  # buf
                self.emit("    mov rdx, rax")
                self.emit_expr(args[0])  # fd
                self.emit("    mov rcx, rax")
                self.emit("    lea r9, [_written]")
                self.emit("    sub rsp, 40")
                self.emit("    mov qword [rsp+32], 0")  # lpOverlapped = NULL
                self.emit("    call ReadFile")
                self.emit("    add rsp, 40")
                # Return bytes read (from _written)
                self.emit("    mov eax, [_written]")
            elif name == "fwrite":
                # fwrite(fd, buf_ptr, len) → WriteFile
                self.emit_expr(args[2])  # len
                self.emit("    mov r8, rax")
                self.emit_expr(args[1])  # buf
                self.emit("    mov rdx, rax")
                self.emit_expr(args[0])  # fd
                self.emit("    mov rcx, rax")
                self.emit("    lea r9, [_written]")
                self.emit("    sub rsp, 40")
                self.emit("    mov qword [rsp+32], 0")
                self.emit("    call WriteFile")
                self.emit("    add rsp, 40")
                self.emit("    mov eax, [_written]")
            elif name == "fclose":
                # fclose(fd) → CloseHandle
                self.emit_expr(args[0])
                self.emit("    mov rcx, rax")
                self.emit("    sub rsp, 32")
                self.emit("    call CloseHandle")
                self.emit("    add rsp, 32")
            return

        # User-defined function call
        if len(args) > 4:
            raise RuntimeError(f"Function {name} has >4 arguments (not supported)")
        param_regs = ["rcx", "rdx", "r8", "r9"]
        for i, arg in enumerate(reversed(args)):
            idx = len(args) - 1 - i
            self.emit_expr(arg)
            self.emit(f"    mov {param_regs[idx]}, rax")
        self.emit(f"    sub rsp, 32")
        self.emit(f"    call {name}")
        self.emit(f"    add rsp, 32")

    def emit_binary(self, expr):
        op = expr["op"]
        left = expr["left"]
        right = expr["right"]

        if op in ("&&", "||"):
            self.emit_short_circuit(expr)
            return

        # Evaluate right → save to stack, evaluate left → rax, pop right → rcx
        self.emit_expr(right)
        self.emit("    push rax")
        self.emit_expr(left)
        self.emit("    pop rcx")

        op_map = {
            "+": "add rax, rcx",
            "-": "sub rax, rcx",
            "*": "imul rax, rcx",
        }

        if op in op_map:
            self.emit(f"    {op_map[op]}")
        elif op == "/":
            self.emit("    cqo")
            self.emit("    idiv rcx")
        elif op == "%":
            self.emit("    cqo")
            self.emit("    idiv rcx")
            self.emit("    mov rax, rdx")
        elif op == "==":
            self.emit("    cmp rax, rcx")
            self.emit("    sete al")
            self.emit("    movzx eax, al")
        elif op == "!=":
            self.emit("    cmp rax, rcx")
            self.emit("    setne al")
            self.emit("    movzx eax, al")
        elif op == "<":
            self.emit("    cmp rax, rcx")
            self.emit("    setl al")
            self.emit("    movzx eax, al")
        elif op == ">":
            self.emit("    cmp rax, rcx")
            self.emit("    setg al")
            self.emit("    movzx eax, al")
        elif op == "<=":
            self.emit("    cmp rax, rcx")
            self.emit("    setle al")
            self.emit("    movzx eax, al")
        elif op == ">=":
            self.emit("    cmp rax, rcx")
            self.emit("    setge al")
            self.emit("    movzx eax, al")
        else:
            raise RuntimeError(f"Unknown binary op: {op}")

    def emit_short_circuit(self, expr):
        op = expr["op"]
        end_label = self.fresh_label()
        true_label = self.fresh_label()

        self.emit_expr(expr["left"])
        if op == "&&":
            self.emit("    test rax, rax")
            self.emit(f"    jz {end_label}")
        else:  # ||
            self.emit("    test rax, rax")
            self.emit(f"    jnz {true_label}")

        self.emit_expr(expr["right"])

        if op == "||":
            self.emit(f"{true_label}:")

        self.emit("    test rax, rax")
        self.emit("    setne al")
        self.emit("    movzx eax, al")
        self.emit(f"{end_label}:")

    def emit_unary(self, expr):
        self.emit_expr(expr["expr"])
        if expr["op"] == "-":
            self.emit("    neg rax")
        elif expr["op"] == "!":
            self.emit("    test rax, rax")
            self.emit("    setz al")
            self.emit("    movzx eax, al")

    # ── struct operations ─────────────────────────────────────────────

    def _resolve_field(self, var_name, field_name):
        """Return (slot_offset, field_offset, field_type) for var.field."""
        slot = self.local_offset.get(var_name)
        if slot is None:
            raise RuntimeError(f"Undefined variable: {var_name}")
        var_type = self.local_types.get(var_name, "i64")
        if var_type not in self.structs:
            raise RuntimeError(f"Field access on non-struct type '{var_type}'")
        info = self.structs[var_type]
        for f in info["fields"]:
            if f["name"] == field_name:
                return slot, f["offset"], f["type"]
        raise RuntimeError(f"Struct '{var_type}' has no field '{field_name}'")

    def emit_field_access(self, expr):
        """Read expr.object.field into rax."""
        obj = expr["object"]
        field_name = expr["field"]
        if obj["type"] != "var":
            raise RuntimeError(f"Field access on non-variable: {obj['type']}")
        slot, off, ftype = self._resolve_field(obj["name"], field_name)
        self.emit(f"    lea rax, [rbp{slot:+d}]")
        if ftype == "i8":
            self.emit(f"    movsx rax, byte [rax+{off}]")
        else:
            self.emit(f"    mov rax, [rax+{off}]")

    def emit_field_set(self, stmt):
        """stmt.object.field = stmt.value"""
        obj = stmt["object"]
        field_name = stmt["field"]
        # Evaluate value first (may use same struct)
        self.emit_expr(stmt["value"])
        self.emit("    push rax")
        slot, off, ftype = self._resolve_field(obj["name"], field_name)
        self.emit(f"    lea rcx, [rbp{slot:+d}]")
        self.emit("    pop rax")
        if ftype == "i8":
            self.emit(f"    mov [rcx+{off}], al")
        else:
            self.emit(f"    mov [rcx+{off}], rax")


# ═══════════════════════════════════════════════════════════════════════════
#  Helpers (itoa, string output) — emitted once at end of .asm
# ═══════════════════════════════════════════════════════════════════════════

ITOA_HELPER = r"""
; ── _itoa_write: convert rax to decimal string and write to console ──
; clobbers: rax, rcx, rdx, r8, r9, r10, r11
_itoa_write:
    push rbp
    mov rbp, rsp
    sub rsp, 48

    ; handle negative
    test rax, rax
    jns itoa_positive
    mov byte [_buf], '-'
    neg rax
    mov r10, 1
    jmp itoa_convert

itoa_positive:
    ; handle zero
    test rax, rax
    jnz itoa_nonzero
    mov byte [_buf], '0'
    mov byte [_buf+1], 10
    mov r8, 2
    jmp itoa_print

itoa_nonzero:
    mov r10, 0  ; offset for sign

itoa_convert:
    ; write digits backwards from _buf_end
    lea r11, [_buf_end]
itoa_loop:
    dec r11
    xor rdx, rdx
    mov rcx, 10
    div rcx
    add dl, '0'
    mov [r11], dl
    test rax, rax
    jnz itoa_loop

    ; compute length: _buf_end - r11 + r10 + 1 (for newline)
    lea r8, [_buf_end]
    sub r8, r11
    add r8, r10
    inc r8  ; newline

    ; if negative, shift digits right by 1
    test r10, r10
    jz itoa_copy

    ; copy from r11 to _buf+1
    mov rcx, r11
    lea rdx, [_buf+1]
    mov rax, r8
    sub rax, 2  ; length without sign and newline
itoa_shift:
    mov bl, [rcx]
    mov [rdx], bl
    inc rcx
    inc rdx
    dec rax
    jnz itoa_shift
    jmp itoa_newline

itoa_copy:
    ; copy from r11 to _buf
    mov rcx, r11
    lea rdx, [_buf]
    mov rax, r8
    sub rax, 1  ; length without newline
itoa_copy_loop:
    mov bl, [rcx]
    mov [rdx], bl
    inc rcx
    inc rdx
    dec rax
    jnz itoa_copy_loop

itoa_newline:
    ; write newline at end (use lea to avoid 32-bit displacement overflow)
    lea rax, [_buf-1]
    mov byte [rax+r8], 10

itoa_print:
    mov [rbp-8], r8       ; save length (GetStdHandle clobbers r8)
    mov ecx, -11          ; STD_OUTPUT_HANDLE
    call GetStdHandle

    mov rcx, rax          ; hFile
    lea rdx, [_buf]       ; lpBuffer
    mov r8, [rbp-8]       ; restore length
    lea r9, [_written]
    sub rsp, 40
    mov qword [rsp+32], 0
    call WriteFile
    add rsp, 40

    mov rsp, rbp
    pop rbp
    ret
"""


# ═══════════════════════════════════════════════════════════════════════════
#  Driver
# ═══════════════════════════════════════════════════════════════════════════

def compile_file(input_path):
    base = os.path.splitext(os.path.basename(input_path))[0]
    asm_path = base + ".asm"
    obj_path = base + ".obj"
    exe_path = base + ".exe"

    print(f"[1/4] Reading {input_path}")
    with open(input_path, "r", encoding="utf-8") as f:
        source = f.read()

    print(f"[2/4] Compiling → {asm_path}")
    tokens = lex(source)
    parser = Parser(tokens)
    ast = parser.parse_program()

    emitter = Emitter(asm_path)
    emitter.emit_program(ast)
    emitter.emit(ITOA_HELPER)
    emitter.close()

    print(f"[3/4] Assembling → {obj_path}")
    result = subprocess.run(
        [NASM, "-f", "win64", asm_path, "-o", obj_path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("NASM error:\n" + result.stderr)
        sys.exit(1)

    print(f"[4/4] Linking → {exe_path}")
    result = subprocess.run(
        [sys.executable, LINK_PY, obj_path, "-o", exe_path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("Link error:\n" + result.stderr)
        sys.exit(1)

    size = os.path.getsize(exe_path)
    print(f"  OK: {exe_path} ({size} bytes)")


def main():
    if len(sys.argv) < 2:
        print("Usage: python epicc.py <file.ep>")
        sys.exit(1)

    input_path = sys.argv[1]
    if not os.path.exists(input_path):
        print(f"Error: file not found: {input_path}")
        sys.exit(1)

    compile_file(input_path)


if __name__ == "__main__":
    main()
