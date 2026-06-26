"""
Epic v0 — lexer
Tokenizes .ep source into a list of (kind, value, line) tuples.
"""

import re

TOKEN_SPEC = [
    ("FUN",       r'\bfun\b'),
    ("RETURN",    r'\breturn\b'),
    ("IF",        r'\bif\b'),
    ("ELSE",      r'\belse\b'),
    ("WHILE",     r'\bwhile\b'),
    ("STRUCT",    r'\bstruct\b'),
    ("NEW",       r'\bnew\b'),
    ("LET",       r'\blet\b'),
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
