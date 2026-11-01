"""
Epic v0 — lexer
Tokenizes .ep source into a list of (kind, value, line) tuples.
"""

import re

TOKEN_SPEC = [
    ("FUN",       r'\bfun\b'),
    ("RET",       r'\bret\b'),
    ("RETURN",    r'\breturn\b'),
    ("IF",        r'\bif\b'),
    ("ELSE",      r'\belse\b'),
    ("FOR",       r'\bfor\b'),
    ("WHILE",     r'\bwhile\b'),
    ("BREAK",     r'\bbreak\b'),
    ("CONTINUE",  r'\bcontinue\b'),
    ("TYPE",      r'\btype\b'),
    ("NEW",       r'\bnew\b'),
    ("LET",       r'\blet\b'),
    ("ID",        r'[a-zA-Z_][a-zA-Z0-9_]*'),
    ("NUMBER",    r'0[xX][0-9a-fA-F]+|[0-9]+'),
    ("EQEQ",      r'=='),
    ("NEQ",       r'!='),
    ("LTE",       r'<='),
    ("GTE",       r'>='),
    ("SHL",       r'<<'),
    ("SHR",       r'>>'),
    ("AND",       r'&&'),
    ("AMPERSAND", r'&'),
    ("OR",        r'\|\|'),
    ("BIT_OR",    r'\|'),
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
    ("COMMA",     r','),
    ("COLON",     r':'),
    ("CHAR",      r"'(?:\\[nrt\\\\\"'0]|[^\\'\n\r])'"),
    ("STRING",    r'"(?:\\[nrt\\\\\"\'0]|[^\\\"\n\r])*"'),
    ("COMMENT",   r'#[^\n]*'),
    ("NEWLINE",   r'\n'),
    ("WHITESPACE", r'[ \t\r]+'),
]

TOKEN_RE = re.compile(
    "|".join(f"(?P<{name}>{pattern})" for name, pattern in TOKEN_SPEC),
    re.DOTALL,
)


class LexError(Exception):
    def __init__(self, msg, line):
        super().__init__(f"Lex error line {line}: {msg}")
        self.line = line


ESCAPES = {
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "\\": "\\",
    '"': '"',
    "'": "'",
    "0": "\0",
}


def decode_escaped(raw, line):
    out = []
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == "\\":
            i += 1
            if i >= len(raw) or raw[i] not in ESCAPES:
                raise LexError("Invalid escape sequence", line)
            ch = ESCAPES[raw[i]]
        if ord(ch) > 127:
            raise LexError("Non-ASCII string and character literals are not supported", line)
        out.append(ch)
        i += 1
    return "".join(out)


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
            value = int(value, 16) if value.lower().startswith("0x") else int(value, 10)
            if value > 0x7FFFFFFFFFFFFFFF:
                raise LexError("Integer literal is out of i64 range", line)
        elif kind == "STRING":
            value = decode_escaped(value[1:-1], line)
        elif kind == "CHAR":
            decoded = decode_escaped(value[1:-1], line)
            if len(decoded) != 1:
                raise LexError("Character literal must contain exactly one byte", line)
            value = ord(decoded)
        tokens.append((kind, value, line))
        pos = m.end()
    return tokens
