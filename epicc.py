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
    ("NEW",       r'\bnew\b'),
    ("LET",       r'\blet\b'),
    ("TYPE_STR",  r'\bstr\b'),
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
    ("AMPERSAND", r'&'),
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
    """Tokenize source text. Detects and rejects invalid characters."""
    tokens = []
    lines = source_text.split("\n")
    line_numbers = []
    pos = 0
    for i, line in enumerate(lines, 1):
        for _ in range(len(line) + 1):  # +1 for newline
            if pos < len(source_text):
                line_numbers.append(i)
            pos += 1

    pos = 0
    while pos < len(source_text):
        m = TOKEN_RE.match(source_text, pos)
        if not m:
            line = line_numbers[pos] if pos < len(line_numbers) else 1
            raise LexError(f"Unexpected character {source_text[pos]!r}", line)
        kind = m.lastgroup
        value = m.group()
        if kind == "WHITESPACE" or kind == "COMMENT":
            pos = m.end()
            continue
        line = line_numbers[m.start()] if m.start() < len(line_numbers) else 1
        if kind == "NUMBER":
            value = int(value)
        elif kind == "STRING":
            value = value[1:-1]  # strip quotes
        elif kind == "CHAR":
            value = ord(value[1])  # 'X' → ASCII code
        tokens.append((kind, value, line))
        pos = m.end()
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
        if t[0] == "AMPERSAND":
            inner = self.parse_type()
            return f"&{inner}"  # e.g. "&Token" or "&i64"
        if t[0] in ("TYPE_I64", "TYPE_I8", "TYPE_STR"):
            return t[1]  # "i64" or "i8" or "str"
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
        return {"type": "return", "expr": expr, "line": line}

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
        return {"type": "let", "name": name[1], "var_type": typ, "value": value}

    def parse_assign_stmt(self):
        name = self.expect("ID")
        # Build LHS chain: .field | [index]
        lhs = {"type": "var", "name": name[1]}
        while True:
            if self.check("DOT"):
                field = self.expect("ID")
                lhs = {"type": "field_access", "object": lhs, "field": field[1]}
            elif self.check("LBRACKET"):
                index = self.parse_expr()
                self.expect("RBRACKET")
                lhs = {"type": "subscript", "base": lhs, "index": index}
            else:
                break
        self.expect("ASSIGN")
        value = self.parse_expr()
        self.expect("SEMICOLON")
        if lhs["type"] == "var":
            return {"type": "assign", "name": lhs["name"], "value": value}
        elif lhs["type"] == "field_access":
            return {"type": "field_set", "object": lhs["object"], "field": lhs["field"], "value": value}
        elif lhs["type"] == "subscript":
            return {"type": "subscript_assign", "base": lhs["base"], "index": lhs["index"], "value": value}
        raise ParseError(f"Invalid assignment target: {lhs['type']}")

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
        if self.check("AMPERSAND"):
            return {"type": "unary", "op": "&", "expr": self.parse_unary()}
        if self.check("STAR"):
            return {"type": "unary", "op": "*", "expr": self.parse_unary()}
        return self.parse_primary()

    def parse_primary(self):
        if self.peek_kind("NEW"):
            self.expect("NEW")
            t = self.advance()
            if t[0] not in ("ID", "TYPE_I64", "TYPE_I8"):
                raise ParseError(f"Expected type after new, got {t[0]}", t[2])
            elem = t[1]
            if self.check("LBRACKET"):
                count = self.parse_expr()
                self.expect("RBRACKET")
                return {"type": "new_array", "elem_type": elem, "count": count}
            return {"type": "new", "struct_name": elem}
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
            else:
                node = {"type": "var", "name": name}
            # Postfix: .field and [index]
            while True:
                if self.check("DOT"):
                    field = self.expect("ID")
                    node = {"type": "field_access", "object": node, "field": field[1]}
                elif self.check("LBRACKET"):
                    index = self.parse_expr()
                    self.expect("RBRACKET")
                    node = {"type": "subscript", "base": node, "index": index}
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


# ═══════════════════════════════════════════════════════════════════════════
#  Emitter (AST → NASM assembly)
# ═══════════════════════════════════════════════════════════════════════════

class Emitter:
    def __init__(self, out_path):
        self.out = open(out_path, "w")
        self.builtins = {"exit", "putc", "putstr",
                         "fopen", "fread", "fwrite", "fclose",
                         "strcmp", "strlen", "itoa", "system",
                         "listdir", "str"}
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
        self.emit("extern CreateProcessA")
        self.emit("extern WaitForSingleObject")
        self.emit("extern GetExitCodeProcess")
        self.emit("extern HeapAlloc")
        self.emit("extern GetProcessHeap")
        self.emit("extern FindFirstFileA")
        self.emit("extern FindNextFileA")
        self.emit("extern FindClose")
        self.emit("default rel")
        self.emit("")

        # Compute struct layouts first
        self._compute_struct_layouts(ast)

        # Collect strings from AST
        self.strings = {}
        self.string_counter = 0
        for func in ast.get("funcs", []):
            self._collect_strings_from_block(func.get("body", {}))

        self.emit("section .data")
        self.emit("    _buf times 32 db 0")
        self.emit("    _buf_end db 0")
        self.emit("    _written dd 0")
        self.emit("    _heap dq 0")
        # Emit string literals as comma-separated bytes (avoids NASM escaping)
        for label, text in sorted(self.strings.items(), key=lambda x: x[0]):
            bytes_str = ", ".join(str(b) for b in text.encode('ascii', errors='replace'))
            self.emit(f"{label}: db {bytes_str}, 0")
        self.emit("")
        self.emit("section .text")
        self.emit("")

        for func in ast.get("funcs", []):
            self.emit_fn_def(func)

    def _collect_strings_from_block(self, block):
        """Recursively collect strings from AST."""
        for stmt in block.get("stmts", []):
            if stmt["type"] == "if":
                self._collect_strings_from_block(stmt["then_block"])
                if stmt.get("else_block"):
                    self._collect_strings_from_block(stmt["else_block"])
            elif stmt["type"] == "while":
                self._collect_strings_from_block(stmt["body"])
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

        # Pre-scan parameters FIRST so local_bytes includes them
        for p in params:
            self.get_var_slot(p["name"], p.get("type", "i64"))

        # Pre-scan: allocate stack slots for let declarations
        self._pre_scan_block(body)

        # Pre-scan: count max temp slots needed
        max_temps = self._pre_scan_temps(body)
        temp_bytes = max(max_temps + 1, 3) * 8  # at least 3 temps (24 bytes)

        # Entry label: main → _start
        label = "_start" if name == "main" else name
        self.emit(f"{label}:")

        # Prologue: dynamic frame, 16-byte aligned (include 32-byte shadow + compiler temps)
        self._temp_count = 0
        self._temp_base = self.local_bytes  # temps start below user vars
        self.alloc_size = ((self.local_bytes + temp_bytes + 32 + 15) // 16) * 16
        self.emit("    push rbp")
        self.emit("    mov rbp, rsp")
        self.emit(f"    sub rsp, {self.alloc_size}")

        # Heap init for main
        if name == "main":
            self.emit("    call GetProcessHeap")
            self.emit("    mov [_heap], rax")

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

    # ── ABI helpers ───────────────────────────────────────────────────

    def _call_prep(self, stack_args=0):
        """Emit sub rsp for extra stack params beyond the 4 register params.
        The frame already has 32 bytes shadow space; extra bytes are for
        params 5+ at [rsp+32], [rsp+40], etc.  Alignment: rsp \u2261 8 mod 16."""
        extra_bytes = stack_args * 8
        if extra_bytes == 0:
            return 0
        frame = ((extra_bytes + 15) // 16) * 16
        self.emit(f"    sub rsp, {frame}")
        return frame

    def _call_cleanup(self, stack_args=0):
        extra_bytes = stack_args * 8
        if extra_bytes == 0:
            return
        frame = ((extra_bytes + 15) // 16) * 16
        self.emit(f"    add rsp, {frame}")

    def get_var_slot(self, name, typ=None):
        if name not in self.local_offset:
            size = self._type_size(typ) if typ else 8
            # 8-byte align
            if self.local_bytes % 8 != 0:
                self.local_bytes += 8 - (self.local_bytes % 8)
            self.local_bytes += size
            self.local_offset[name] = -self.local_bytes
        return self.local_offset[name]

    def _alloc_temp(self):
        """Allocate a compiler temporary frame slot, return rbp-relative offset."""
        nr = self._temp_count
        self._temp_count += 1
        return -(self._temp_base + (nr + 1) * 8)

    def _type_size(self, typ):
        if typ == "i64":
            return 8
        if typ == "i8":
            return 1
        if typ in self.structs:
            return self.structs[typ]["size"]
        if typ.startswith("&"):
            return 8  # pointers are always 8 bytes
        return 8  # unknown, assume i64

    def _register_len_data_type(self, name, elem_ptr_type):
        """Register a {data, len} layout type. data at offset 0, len at offset 8."""
        if name not in self.structs:
            self.structs[name] = {
                "fields": [
                    {"name": "data", "type": elem_ptr_type, "offset": 0},
                    {"name": "len", "type": "i64", "offset": 8},
                ],
                "size": 16,
            }

    def _compute_struct_layouts(self, ast):
        self.structs = {}
        # Built-in str type: { data: &i8, len: i64 }
        self._register_len_data_type("str", "&i8")
        # Array-of-str type used by listdir()
        self._register_len_data_type("_arr_str", "&&str")
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

    def _pre_scan_temps(self, node):
        """Count maximum temp slots needed. Each binary op uses 1 temp."""
        if isinstance(node, dict):
            count = 0
            if node.get("type") == "binary":
                count = 1  # this binary op saves right operand in a temp
            # Recurse into children, take max across siblings (temps are reused)
            for v in node.values():
                count += self._pre_scan_temps(v)
            return count
        elif isinstance(node, list):
            # For lists of statements, each statement's path is independent
            # But temps are cumulative across sequential statements (not reused across statements)
            total = 0
            for item in node:
                total += self._pre_scan_temps(item)
            return total
        return 0

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
        elif t == "if":
            self.emit_if(stmt)
        elif t == "while":
            self.emit_while(stmt)
        elif t == "assign":
            self.emit_assign(stmt)
        elif t == "field_set":
            self.emit_field_set(stmt)
        elif t == "subscript_assign":
            self.emit_subscript_assign(stmt)
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
        var_type = stmt.get("var_type")
        value = stmt.get("value")
        # Type inference from initializer
        if var_type is None and value is not None:
            if value["type"] == "new":
                var_type = f"&{value['struct_name']}"
            elif value["type"] == "new_array":
                var_type = f"&_arr_{value['elem_type']}"
            elif value["type"] == "call" and value["name"] == "listdir":
                var_type = "&_arr_str"
            elif value["type"] == "call" and value["name"] == "itoa":
                var_type = "&str"
            elif value["type"] == "call" and value["name"] == "str":
                var_type = "&str"
            elif value["type"] == "string":
                var_type = "&str"
            else:
                var_type = "i64"
        if var_type is None:
            var_type = "i64"
        slot = self.get_var_slot(name, var_type)
        self.local_types[name] = var_type
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
            strlen = len(expr["value"])
            self.emit(f"    lea rcx, [{label}]")
            self.emit(f"    mov rdx, {strlen}")
            self.emit(f"    call _str_alloc")
        elif t == "var":
            name = expr["name"]
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
        elif t == "subscript":
            self.emit_subscript(expr)
        elif t == "binary":
            self.emit_binary(expr)
        elif t == "unary":
            self.emit_unary(expr)
        elif t == "field_access":
            self.emit_field_access(expr)
        elif t == "new":
            self.emit_new(expr)
        elif t == "new_array":
            self.emit_new_array(expr)
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
            elif name == "putc":
                self.emit_expr(args[0])
                self.emit("    mov [_buf], al")
                self.emit("    mov ecx, -11")
                self.emit("    call GetStdHandle")
                self.emit("    mov rcx, rax")
                self.emit("    lea rdx, [_buf]")
                self.emit("    mov r8, 1")
                self.emit("    lea r9, [_written]")
                self._call_prep(1)
                self.emit("    mov qword [rsp+32], 0")
                self.emit("    call WriteFile")
                self._call_cleanup(1)
            elif name == "putstr":
                # putstr(s: &str): save &str in temp slot, GetStdHandle, then WriteFile
                self.emit_expr(args[0])       # rax = &str
                tmp = self._alloc_temp()
                self.emit(f"    mov [rbp{tmp:+d}], rax")  # save &str
                self.emit("    mov ecx, -11")  # STD_OUTPUT_HANDLE
                self.emit("    call GetStdHandle")
                self.emit("    mov rcx, rax")   # rcx = stdout handle
                self.emit(f"    mov rax, [rbp{tmp:+d}]")  # rax = &str
                self.emit("    mov rdx, [rax]")      # rdx = str.data (offset 0)
                self.emit("    mov r8, [rax+8]")    # r8 = str.len (offset 8)
                self.emit("    lea r9, [_written]")
                self._call_prep(1)             # 1 stack arg (lpOverlapped)
                self.emit("    mov qword [rsp+32], 0")
                self.emit("    call WriteFile")
                self._call_cleanup(1)
            elif name == "strcmp":
                # strcmp(a: &str, b: &str) → extract .data from each, call lstrcmpA
                self.emit_expr(args[1])       # rax = &str (b)
                self.emit("    mov rdx, [rax]")    # rdx = b.data (offset 0)
                self.emit_expr(args[0])       # rax = &str (a)
                self.emit("    mov rcx, [rax]")    # rcx = a.data (offset 0)
                self.emit("    call lstrcmpA")
            elif name == "fopen":
                # fopen(path: &str, mode) → extract path.data, call CreateFileA
                rl = self.fresh_label()
                dl = self.fresh_label()
                self.emit_expr(args[1])  # rax = mode
                self.emit("    test rax, rax")
                self.emit(f"    jz {rl}")
                # Write mode
                self.emit_expr(args[0])       # rax = &str
                self.emit("    mov rcx, [rax]")    # rcx = path.data (offset 0)
                self.emit("    mov edx, 0x40000000")  # GENERIC_WRITE
                self.emit("    xor r8d, r8d")
                self.emit("    xor r9d, r9d")
                self._call_prep(3)
                self.emit("    mov dword [rsp+32], 2")       # CREATE_ALWAYS
                self.emit("    mov dword [rsp+40], 0x80")
                self.emit("    mov qword [rsp+48], 0")
                self.emit("    call CreateFileA")
                self._call_cleanup(3)
                self.emit(f"    jmp {dl}")
                self.emit(f"{rl}:")
                self.emit_expr(args[0])       # rax = &str
                self.emit("    mov rcx, [rax]")    # rcx = path.data (offset 0)
                self.emit("    mov edx, 0x80000000")  # GENERIC_READ
                self.emit("    mov r8d, 1")
                self.emit("    xor r9d, r9d")
                self._call_prep(3)
                self.emit("    mov dword [rsp+32], 3")       # OPEN_EXISTING
                self.emit("    mov dword [rsp+40], 0x80")
                self.emit("    mov qword [rsp+48], 0")
                self.emit("    call CreateFileA")
                self._call_cleanup(3)
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
                self._call_prep(1)
                self.emit("    mov qword [rsp+32], 0")  # lpOverlapped = NULL
                self.emit("    call ReadFile")
                self._call_cleanup(1)
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
                self._call_prep(1)
                self.emit("    mov qword [rsp+32], 0")
                self.emit("    call WriteFile")
                self._call_cleanup(1)
                self.emit("    mov eax, [_written]")
            elif name == "fclose":
                # fclose(fd) → CloseHandle
                self.emit_expr(args[0])
                self.emit("    mov rcx, rax")
                self.emit("    call CloseHandle")
            elif name == "strlen":
                # strlen(s: &str) → s.len (direct field read, no call)
                self.emit_expr(args[0])
                self.emit("    mov rax, [rax+8]")  # str.len at offset 8
            elif name == "itoa":
                # itoa(n) → &str (heap-allocated)
                self.emit_expr(args[0])     # rax = n
                self.emit("    mov rcx, rax")  # rcx = n
                self.emit("    call _itoa")
            elif name == "system":
                # system(cmd: &str) → extract cmd.data, call _system
                self.emit_expr(args[0])       # rax = &str
                self.emit("    mov rcx, [rax]")    # rcx = cmd.data (offset 0)
                self.emit("    sub rsp, 8")       # align for _system entry
                self.emit("    call _system")
                self.emit("    add rsp, 8")
            elif name == "listdir":
                # listdir(pattern: &str, max) → extract pattern.data, call _listdir
                self.emit_expr(args[1])     # max
                self.emit("    mov rdx, rax")
                self.emit_expr(args[0])     # pattern
                self.emit("    mov rcx, [rax]")  # rcx = pattern.data (offset 0)
                self.emit("    sub rsp, 8")       # align for _listdir entry
                self.emit("    call _listdir")
                self.emit("    add rsp, 8")
            elif name == "str":
                # str(bytes: &i8, len: i64) → &str (deep-copy via _str_alloc)
                self.emit_expr(args[1])     # rax = len
                self.emit("    mov rdx, rax")
                self.emit_expr(args[0])     # rax = bytes
                self.emit("    mov rcx, rax")
                self.emit("    call _str_alloc")
            return

        # User-defined function call: spill all args first, then load registers
        if len(args) > 4:
            raise RuntimeError(f"Function {name} has >4 arguments (not supported)")
        param_regs = ["rcx", "rdx", "r8", "r9"]
        # Evaluate args right-to-left, push each
        for arg in reversed(args):
            self.emit_expr(arg)
            self.emit("    push rax")
        # Pop into registers (rcx gets first arg, rdx second, etc.)
        for i in range(len(args)):
            self.emit(f"    pop {param_regs[i]}")
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

        # Evaluate right to temp slot, evaluate left → rax, load right → rcx
        # Using temp slot (not push/pop) so left expr can contain calls without
        # clobbering stack alignment or shadow space.
        self.emit_expr(right)
        tmp = self._alloc_temp()
        self.emit(f"    mov [rbp{tmp:+d}], rax")
        self.emit_expr(left)
        self.emit(f"    mov rcx, [rbp{tmp:+d}]")

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
        if expr["op"] == "-":
            self.emit_expr(expr["expr"])
            self.emit("    neg rax")
        elif expr["op"] == "!":
            self.emit_expr(expr["expr"])
            self.emit("    test rax, rax")
            self.emit("    setz al")
            self.emit("    movzx eax, al")
        elif expr["op"] == "&":
            self.emit_addrof(expr)
        elif expr["op"] == "*":
            self.emit_deref(expr)
        else:
            raise RuntimeError(f"Unknown unary op: {expr['op']}")

    # ── struct operations ─────────────────────────────────────────────

    def _resolve_field(self, var_name, field_name):
        """Return (slot_offset, field_offset, field_type, is_ptr) for var.field."""
        slot = self.local_offset.get(var_name)
        if slot is None:
            raise RuntimeError(f"Undefined variable: {var_name}")
        var_type = self.local_types.get(var_name, "i64")
        is_ptr = var_type.startswith("&")
        struct_name = var_type[1:] if is_ptr else var_type
        if struct_name not in self.structs:
            raise RuntimeError(f"Field access on non-struct type '{var_type}'")
        info = self.structs[struct_name]
        for f in info["fields"]:
            if f["name"] == field_name:
                return slot, f["offset"], f["type"], is_ptr
        raise RuntimeError(f"Struct '{struct_name}' has no field '{field_name}'")

    def _emit_struct_base(self, slot, is_ptr):
        """Emit instruction to load base address into rax."""
        if is_ptr:
            self.emit(f"    mov rax, [rbp{slot:+d}]")
        else:
            self.emit(f"    lea rax, [rbp{slot:+d}]")

    def _emit_struct_base_rcx(self, slot, is_ptr):
        """Emit instruction to load base address into rcx."""
        if is_ptr:
            self.emit(f"    mov rcx, [rbp{slot:+d}]")
        else:
            self.emit(f"    lea rcx, [rbp{slot:+d}]")

    def emit_field_access(self, expr):
        """Read expr.object.field into rax."""
        obj = expr["object"]
        field_name = expr["field"]
        if obj["type"] == "var":
            slot, off, ftype, is_ptr = self._resolve_field(obj["name"], field_name)
            self._emit_struct_base(slot, is_ptr)
            if ftype == "i8":
                self.emit(f"    movsx rax, byte [rax+{off}]")
            else:
                self.emit(f"    mov rax, [rax+{off}]")
        elif obj["type"] == "subscript":
            # Subscript returned a pointer; access its field
            self.emit_subscript(obj)
            elem, is_struct = self._subscript_type(obj["base"])
            if not is_struct:
                raise RuntimeError(f"Field access on value type '{elem}'")
            info = self.structs[elem]
            for f in info["fields"]:
                if f["name"] == field_name:
                    if f["type"] == "i8":
                        self.emit(f"    movsx rax, byte [rax+{f['offset']}]")
                    else:
                        self.emit(f"    mov rax, [rax+{f['offset']}]")
                    return
            raise RuntimeError(f"Struct '{elem}' has no field '{field_name}'")
        else:
            raise RuntimeError(f"Field access on non-variable: {obj['type']}")

    def emit_field_set(self, stmt):
        """stmt.object.field = stmt.value"""
        obj = stmt["object"]
        field_name = stmt["field"]
        if obj["type"] == "var":
            # Evaluate value first (may use same struct)
            self.emit_expr(stmt["value"])
            self.emit("    push rax")
            slot, off, ftype, is_ptr = self._resolve_field(obj["name"], field_name)
            self._emit_struct_base_rcx(slot, is_ptr)
            self.emit("    pop rax")
            if ftype == "i8":
                self.emit(f"    mov [rcx+{off}], al")
            else:
                self.emit(f"    mov [rcx+{off}], rax")
        elif obj["type"] == "subscript":
            # Subscript result is a pointer; set field on it
            self.emit_expr(stmt["value"])
            self.emit("    push rax")
            self.emit_subscript(obj)
            self.emit("    pop rcx")
            # rax = pointer to struct, rcx = value
            # Look up field offset
            elem, is_struct = self._subscript_type(obj["base"])
            if not is_struct:
                raise RuntimeError(f"Field set on value type")
            info = self.structs[elem]
            for f in info["fields"]:
                if f["name"] == field_name:
                    if f["type"] == "i8":
                        self.emit(f"    mov [rax+{f['offset']}], cl")
                    else:
                        self.emit(f"    mov [rax+{f['offset']}], rcx")
                    return
            raise RuntimeError(f"Struct '{elem}' has no field '{field_name}'")
        else:
            raise RuntimeError(f"Field set on non-var: {obj['type']}")

    def emit_subscript_assign(self, stmt):
        """base[index] = value"""
        base = stmt["base"]
        index = stmt["index"]
        value = stmt["value"]
        elem, is_struct = self._subscript_type(base)
        # Evaluate value first
        self.emit_expr(value)
        self.emit("    push rax")
        # Compute address: base + index * size
        self.emit_expr(base)        # rax = base pointer
        self.emit("    push rax")
        self.emit_expr(index)       # rax = index
        self.emit("    pop rcx")    # rcx = base pointer
        if elem == "i8":
            self.emit(f"    lea rcx, [rcx + rax]")
        else:
            self.emit(f"    lea rcx, [rcx + rax*8]")
        self.emit("    pop rax")
        if elem == "i8":
            self.emit(f"    mov [rcx], al")
        else:
            self.emit(f"    mov [rcx], rax")

    def emit_new(self, expr):
        """new StructName → HeapAlloc, returns &StructName in rax."""
        struct_name = expr["struct_name"]
        if struct_name not in self.structs:
            raise RuntimeError(f"Unknown struct in new: {struct_name}")
        size = self.structs[struct_name]["size"]
        self.emit(f"    mov rcx, [_heap]")
        self.emit(f"    mov edx, 8")   # HEAP_ZERO_MEMORY
        self.emit(f"    mov r8d, {size}")
        self.emit(f"    sub rsp, 40")
        self.emit(f"    call HeapAlloc")
        self.emit(f"    add rsp, 40")
        # rax = pointer, zero-initialized

    def emit_new_array(self, expr):
        """new T[n] → array struct { len: i64, data: &T|&&T }"""
        elem = expr["elem_type"]
        count = expr["count"]
        arr_type = f"_arr_{elem}"
        if elem in ("i64", "i8"):
            data_type = f"&{elem}"
        else:
            data_type = f"&&{elem}"
        self._register_len_data_type(arr_type, data_type)
        # 1. Allocate header (16 bytes)
        self.emit(f"    mov rcx, [_heap]")
        self.emit(f"    mov edx, 8")
        self.emit(f"    mov r8d, 16")
        self.emit(f"    sub rsp, 40")
        self.emit(f"    call HeapAlloc")
        self.emit(f"    add rsp, 40")
        self.emit(f"    push rax")  # save header ptr on shadow
        # 2. Store len at offset 8
        self.emit_expr(count)       # rax = count
        self.emit(f"    pop rcx")   # rcx = header ptr
        self.emit(f"    push rcx")  # re-save
        self.emit(f"    mov [rcx+8], rax")  # header.len = count (offset 8)
        # 3. Compute data size and allocate
        if elem in ("i64", "i8"):
            el_size = 8 if elem == "i64" else 1
            s_op = "imul" if el_size > 1 else ""  # no multiplication needed for size 1
            self.emit(f"    mov r8, rax")  # r8 = count
            if el_size == 8:
                self.emit(f"    imul r8, {el_size}")
            self.emit(f"    mov rcx, [_heap]")
            self.emit(f"    mov edx, 8")
            self.emit(f"    sub rsp, 40")
            self.emit(f"    call HeapAlloc")
            self.emit(f"    add rsp, 40")
            # rax = data pointer
            self.emit(f"    pop rcx")   # rcx = header ptr
            self.emit(f"    push rcx")
            self.emit(f"    mov [rcx], rax")  # header.data = data ptr (offset 0)
            self.emit(f"    pop rax")   # return header ptr
        else:
            # struct array: allocate pointer array (count * 8), then new each element
            # Save count and header ptr in compiler temps (not hardcoded slots)
            tmp_header = self._alloc_temp()
            tmp_count = self._alloc_temp()
            tmp_data = self._alloc_temp()
            self.emit(f"    mov [rbp{tmp_header:+d}], rcx")  # save header ptr
            self.emit(f"    mov [rbp{tmp_count:+d}], rax")   # save count
            # Allocate pointer array: count * 8
            self.emit(f"    mov r8, rax")
            self.emit(f"    imul r8, 8")
            self.emit(f"    mov rcx, [_heap]")
            self.emit(f"    mov edx, 8")
            self.emit(f"    sub rsp, 40")
            self.emit(f"    call HeapAlloc")
            self.emit(f"    add rsp, 40")
            # rax = pointer array base
            self.emit(f"    mov [rbp{tmp_data:+d}], rax")   # save pointer array
            # Loop: for i in range(count): data[i] = new StructName
            self.emit(f"    mov r12, [rbp{tmp_count:+d}]")  # r12 = count (non-volatile)
            loop_lbl = self.fresh_label()
            done_lbl = self.fresh_label()
            self.emit(f"{loop_lbl}:")
            self.emit(f"    test r12, r12")
            self.emit(f"    jz {done_lbl}")
            self.emit(f"    dec r12")
            # new elem
            el_size = self.structs[elem]["size"]
            self.emit(f"    mov rcx, [_heap]")
            self.emit(f"    mov edx, 8")
            self.emit(f"    mov r8d, {el_size}")
            self.emit(f"    sub rsp, 40")
            self.emit(f"    call HeapAlloc")
            self.emit(f"    add rsp, 40")
            # store in pointer array
            self.emit(f"    mov rcx, [rbp{tmp_data:+d}]")  # pointer array base
            self.emit(f"    mov [rcx + r12*8], rax")
            self.emit(f"    jmp {loop_lbl}")
            self.emit(f"{done_lbl}:")
            # store pointer array in header
            self.emit(f"    mov rcx, [rbp{tmp_header:+d}]")  # header ptr
            self.emit(f"    mov rax, [rbp{tmp_data:+d}]")   # pointer array
            self.emit(f"    mov [rcx], rax")   # header.data = pointer array (offset 0)
            self.emit(f"    mov rax, rcx")     # return header ptr
            self.emit(f"    pop rcx")           # balance push from step 2

    def emit_subscript(self, expr):
        """base[index] → load value from array"""
        base = expr["base"]
        index = expr["index"]
        # Determine element type from base expression
        elem, is_struct = self._subscript_type(base)
        # Evaluate base (pointer), then add index * size
        self.emit_expr(base)        # rax = base pointer
        self.emit("    push rax")
        self.emit_expr(index)       # rax = index
        self.emit("    pop rcx")    # rcx = base pointer
        if elem == "i8":
            self.emit(f"    movsx rax, byte [rcx + rax]")
        elif elem == "i64":
            self.emit(f"    mov rax, [rcx + rax*8]")
        else:
            # Struct pointer array
            self.emit(f"    mov rax, [rcx + rax*8]")

    def _subscript_type(self, base_expr):
        """Return (elem_type, is_struct) for subscript base expression."""
        if base_expr["type"] == "field_access":
            obj = base_expr["object"]
            fn = base_expr["field"]
            if obj["type"] == "var":
                vtype = self.local_types.get(obj["name"], "i64")
                if vtype.startswith("&"):
                    vtype = vtype[1:]  # strip &
                if vtype.startswith("_arr_"):
                    vtype = vtype[5:]  # strip _arr_
                if vtype in ("i64", "i8"):
                    return vtype, False
                else:
                    return vtype, True
        # Default: pointer to i64
        return "i64", False

    def emit_addrof(self, expr):
        """&inner → lea rax, [address]"""
        inner = expr["expr"]
        if inner["type"] == "var":
            name = inner["name"]
            slot = self.local_offset[name]
            self.emit(f"    lea rax, [rbp{slot:+d}]")
        elif inner["type"] == "field_access":
            obj = inner["object"]
            field_name = inner["field"]
            if obj["type"] != "var":
                raise RuntimeError(f"Cannot take address of: {obj['type']}")
            slot, off, ftype, is_ptr = self._resolve_field(obj["name"], field_name)
            self._emit_struct_base(slot, is_ptr)
            self.emit(f"    add rax, {off}")
        else:
            raise RuntimeError(f"Cannot take address of: {inner['type']}")

    def emit_deref(self, expr):
        """*inner → load value from pointer"""
        inner = expr["expr"]
        # Determine pointee type from the inner expression
        pointee = "i64"
        if inner["type"] == "var":
            vtype = self.local_types.get(inner["name"], "i64")
            if vtype.startswith("&"):
                pointee = vtype[1:]
        self.emit_expr(inner)
        if pointee == "i8":
            self.emit("    movsx rax, byte [rax]")
        else:
            self.emit("    mov rax, [rax]")


# ═══════════════════════════════════════════════════════════════════════════
#  Helpers (itoa, string output) — emitted once at end of .asm
# ═══════════════════════════════════════════════════════════════════════════

STR_ALLOC_HELPER = r"""
; ── _str_alloc: deep-copy bytes into heap-allocated str ──
; rcx = src pointer, rdx = len
; returns: rax = &str { data: &i8, len: i64 }
; clobbers: rax, rcx, rdx, r8, r9, r10, r11
_str_alloc:
    push rbp
    mov rbp, rsp
    sub rsp, 40           ; 3 save slots (24) + alignment
    mov [rbp-8], rcx      ; save src
    mov [rbp-16], rdx     ; save len
    ; Allocate header (16 bytes)
    mov rcx, [_heap]
    mov edx, 8
    mov r8d, 16
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov [rbp-24], rax     ; save header ptr
    ; Allocate data (len + 1 for null terminator)
    mov rcx, [_heap]
    mov edx, 8
    mov r8, [rbp-16]      ; len
    inc r8                ; +1 for null
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
                          ; rax = data ptr
    ; Store data ptr and len in header
    mov rcx, [rbp-24]     ; rcx = header
    mov [rcx], rax        ; header.data = data (offset 0)
    mov rdx, [rbp-16]     ; rdx = len
    mov [rcx+8], rdx      ; header.len = len (offset 8)
    ; Copy bytes
    test rdx, rdx
    jz _str_alloc_null
    mov r8, [rbp-8]       ; r8 = src
    mov r9, rax           ; r9 = dst
_str_alloc_copy:
    mov r10b, [r8]
    mov [r9], r10b
    inc r8
    inc r9
    dec rdx
    jnz _str_alloc_copy
_str_alloc_null:
    mov byte [r9], 0      ; null terminator
    mov rax, [rbp-24]     ; return header ptr
    mov rsp, rbp
    pop rbp
    ret
"""

ITOA_HELPER = r"""
; ── _itoa: convert integer to heap-allocated str ──
; rcx = number
; returns: rax = &str (heap-allocated { data: &i8, len: i64 })
_itoa:
    push rbp
    mov rbp, rsp
    sub rsp, 88           ; 48 (saves) + 32 (temp) + 8 (align)
    mov r8, 0             ; sign flag
    mov rax, rcx
    test rax, rax
    jns .positive
    neg rax
    mov r8, 1             ; has sign
.positive:
    test rax, rax
    jnz .convert
    lea r10, [zero_str_data]
    mov r11, 1
    mov r8, 0
    jmp .save_state
.convert:
    lea r10, [rbp-80]
    add r10, 31
    sub r10, r8           ; leave room for sign
    mov r11, 0
.digit_loop:
    xor rdx, rdx
    mov rcx, 10
    div rcx
    add dl, '0'
    dec r10
    mov [r10], dl
    inc r11
    test rax, rax
    jnz .digit_loop
.save_state:
    mov [rbp-16], r10     ; save first digit ptr (volatile)
    mov [rbp-24], r11     ; save digit count (volatile)
    mov [rbp-32], r8      ; save sign flag
    ; Allocate header (16 bytes)
    mov rcx, [_heap]
    mov edx, 8
    mov r8d, 16
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov [rbp-8], rax      ; save header
    ; Compute total len
    mov r8, [rbp-24]       ; digit count
    add r8, [rbp-32]       ; + sign flag
    ; Allocate data (total len + 1)
    mov rcx, [_heap]
    mov edx, 8
    push r8               ; save total len
    inc r8                ; +1 for null
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    pop rdx               ; rdx = total len
    mov rcx, [rbp-8]
    mov [rcx], rax        ; header.data = data
    mov [rcx+8], rdx      ; header.len = total len
    ; Restore volatile state
    mov r10, [rbp-16]     ; first digit ptr
    mov r11, [rbp-24]     ; digit count
    mov r8, [rbp-32]      ; sign flag
    ; Write sign if negative
    mov r9, rax           ; dst cursor
    test r8, r8
    jz .copy_digits
    mov byte [r9], '-'
    inc r9
.copy_digits:
    mov rcx, r11
    test rcx, rcx
    jz .nullterm
.copy:
    mov al, [r10]
    mov [r9], al
    inc r10
    inc r9
    dec rcx
    jnz .copy
.nullterm:
    mov byte [r9], 0
    mov rax, [rbp-8]
    mov rsp, rbp
    pop rbp
    ret
zero_str_data: db '0', 0
"""

SYSTEM_HELPER = r"""
; ── _system: execute command via CreateProcessA ──
; rcx = command line string
; returns: rax = exit code, or -1 on failure
_system:
    push rbp
    mov rbp, rsp
    sub rsp, 248         ; 128(SI+PI) + 80(call frame: 32 shadow + 48 params) + 40 pad
    push rcx             ; save cmd
    ; Zero STARTUPINFOA + PROCESS_INFORMATION (128 bytes)
    lea rdi, [rsp+96]    ; SI+PI at rsp+96 (above call frame)
    mov ecx, 32          ; 128/4 = 32 dwords
    xor eax, eax
    rep stosd
    ; si.cb = sizeof(STARTUPINFOA) = 104
    mov dword [rsp+96], 104
    ; CreateProcessA(NULL, cmd, NULL, NULL, 0, 0, NULL, NULL, &si, &pi)
    xor ecx, ecx              ; lpApplicationName = NULL
    pop rdx                   ; lpCommandLine
    xor r8, r8                ; lpProcessAttributes = NULL
    xor r9, r9                ; lpThreadAttributes = NULL
    mov qword [rsp+32], 0     ; bInheritHandles = FALSE
    mov qword [rsp+40], 0     ; dwCreationFlags = 0
    mov qword [rsp+48], 0     ; lpEnvironment = NULL
    mov qword [rsp+56], 0     ; lpCurrentDirectory = NULL
    lea rax, [rsp+96]
    mov [rsp+64], rax         ; lpStartupInfo
    lea rax, [rsp+200]
    mov [rsp+72], rax         ; lpProcessInformation
    call CreateProcessA
    ; Check result
    test eax, eax
    jnz _system_ok
    mov rax, -1               ; failure → -1
    jmp _system_done
_system_ok:
    ; WaitForSingleObject(pi.hProcess, INFINITE)
    mov rcx, [rsp+200]       ; pi.hProcess
    mov edx, -1               ; INFINITE
    sub rsp, 40
    call WaitForSingleObject
    add rsp, 40
    ; GetExitCodeProcess
    mov rcx, [rsp+200]       ; pi.hProcess
    lea rdx, [rbp-8]          ; exit code out
    sub rsp, 40
    call GetExitCodeProcess
    add rsp, 40
    ; CloseHandle(pi.hProcess)
    mov rcx, [rsp+200]
    sub rsp, 32
    call CloseHandle
    add rsp, 32
    ; CloseHandle(pi.hThread)
    mov rcx, [rsp+208]
    sub rsp, 32
    call CloseHandle
    add rsp, 32
    mov rax, [rbp-8]          ; return exit code
_system_done:
    mov rsp, rbp
    pop rbp
    ret
"""

LISTDIR_HELPER = r"""
; ── _listdir: list files matching pattern ──
; rcx = pattern (C string), rdx = max
; returns: rax = pointer to { data: &&str, len: i64 }
_listdir:
    push rbp
    mov rbp, rsp
    sub rsp, 688         ; WIN32_FIND_DATAA(592) + 96
    push r12             ; rbp-696
    push r13             ; rbp-704
    push r14             ; rbp-712
    push r15             ; rbp-720
    push rcx             ; rbp-728 save pattern
    push rdx             ; rbp-736 save max
    ; Allocate header (16 bytes)
    mov rcx, [_heap]
    mov edx, 8
    mov r8d, 16
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov r14, rax         ; r14 = header ptr
    mov qword [r14+8], 0 ; header.len = 0 (offset 8)
    ; Allocate pointer array: max * 8
    mov rcx, [_heap]
    mov edx, 8
    mov r8, [rbp-736]    ; max
    imul r8, 8
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov [r14], rax       ; header.data = pointer array (offset 0)
    ; FindFirstFileA
    lea rdx, [rbp-592]
    mov rcx, [rbp-728]   ; pattern
    sub rsp, 40
    call FindFirstFileA
    add rsp, 40
    cmp rax, -1
    je _listdir_done2
    mov r15, rax          ; r15 = find handle
_listdir_loop2:
    mov rcx, [r14+8]      ; current count (offset 8)
    cmp rcx, [rbp-736]    ; max
    jge _listdir_close2
    ; Get filename length
    lea rcx, [rbp-592+44]
    sub rsp, 40
    call lstrlenA
    add rsp, 40
    mov r12, rax          ; r12 = filename length
    ; Allocate str struct (16 bytes)
    mov rcx, [_heap]
    mov edx, 8
    mov r8d, 16
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov r13, rax          ; r13 = str ptr
    mov [r13+8], r12      ; str.len = filename length (offset 8)
    ; Allocate filename buffer (len + 1)
    mov r8, r12
    inc r8
    mov rcx, [_heap]
    mov edx, 8
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov [r13], rax        ; str.data = filename buffer (offset 0)
    ; Copy filename
    mov rcx, rax          ; dst = filename buffer
    lea rdx, [rbp-592+44] ; src = cFileName
    sub rsp, 40
    call lstrcpyA
    add rsp, 40
    ; Store str ptr in pointer array
    mov rcx, [r14]        ; pointer array base (offset 0)
    mov rax, [r14+8]      ; current index (offset 8)
    mov [rcx + rax*8], r13
    inc qword [r14+8]     ; header.len++ (offset 8)
    ; FindNextFileA
    mov rcx, r15
    lea rdx, [rbp-592]
    sub rsp, 40
    call FindNextFileA
    add rsp, 40
    test eax, eax
    jnz _listdir_loop2
_listdir_close2:
    mov rcx, r15
    sub rsp, 40
    call FindClose
    add rsp, 40
_listdir_done2:
    mov rax, r14          ; return header ptr
    pop rdx               ; discard saved max
    pop rcx               ; discard saved pattern
    pop r15
    pop r14
    pop r13
    pop r12
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
    emitter.emit(STR_ALLOC_HELPER)
    emitter.emit(ITOA_HELPER)
    emitter.emit(SYSTEM_HELPER)
    emitter.emit(LISTDIR_HELPER)
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
