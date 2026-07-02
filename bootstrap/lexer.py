"""
Epic v0 — lexer
Tokenizes .ep source into a list of (kind, value, line, dump_value) tuples.
"""

import re

TOKEN_SPEC = [
    ("FUN",       r'\bfun\b'),
    ("RETURN",    r'\breturn\b'),
    ("IF",        r'\bif\b'),
    ("ELSE",      r'\belse\b'),
    ("WHILE",     r'\bwhile\b'),
    ("FOR",       r'\bfor\b'),
    ("IN",        r'\bin\b'),
    ("TYPE",      r'\btype\b'),
    ("MATCH",     r'\bmatch\b'),
    ("PANIC",     r'\bpanic\b'),
    ("ASSERT",    r'\bassert\b'),
    ("TRUE",      r'\btrue\b'),
    ("FALSE",     r'\bfalse\b'),
    ("BREAK",     r'\bbreak\b'),
    ("CONTINUE",  r'\bcontinue\b'),
    ("STRUCT",    r'\bstruct\b'),
    ("NEW",       r'\bnew\b'),
    ("LET",       r'\blet\b'),
    ("ELSE_KW",   r'\belse\b'),
    ("ID",        r'[a-zA-Z_][a-zA-Z0-9_]*'),
    ("NUMBER",    r'[0-9]+'),
    ("USHR_ASSIGN", r'>>>='),
    ("SHL_ASSIGN", r'<<='),
    ("SHR_ASSIGN", r'>>='),
    ("PLUS_ASSIGN", r'\+='),
    ("MINUS_ASSIGN", r'-='),
    ("STAR_ASSIGN", r'\*='),
    ("SLASH_ASSIGN", r'/='),
    ("PERCENT_ASSIGN", r'%='),
    ("AMP_ASSIGN", r'&='),
    ("PIPE_ASSIGN", r'\|='),
    ("CARET_ASSIGN", r'\^='),
    ("USHR",      r'>>>'),
    ("SHL",       r'<<'),
    ("SHR",       r'>>'),
    ("EQEQ",      r'=='),
    ("NEQ",       r'!='),
    ("LTE",       r'<='),
    ("GTE",       r'>='),
    ("AND",       r'&&'),
    ("AMPERSAND", r'&'),
    ("OR",        r'\|\|'),
    ("PIPE",      r'\|'),
    ("CARET",     r'\^'),
    ("TILDE",     r'~'),
    ("ARROW",     r'->'),
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


def scan_fstring(source_text, start, line):
    parts = []
    i = start + 2
    segment_start = i
    while i < len(source_text):
        ch = source_text[i]
        if ch == "\n" or ch == "\r":
            raise LexError("Unterminated f-string literal", line)
        if ch == "\\":
            i += 2
            continue
        if ch == '"':
            if i > segment_start:
                raw = source_text[segment_start:i]
                parts.append(("text", decode_escaped(raw, line), raw))
            return parts, i + 1
        if ch == "}":
            raise LexError("Unexpected '}' in f-string literal", line)
        if ch == "{":
            if i > segment_start:
                raw = source_text[segment_start:i]
                parts.append(("text", decode_escaped(raw, line), raw))
            expr_start = i + 1
            i = expr_start
            parens = 0
            brackets = 0
            braces = 0
            while i < len(source_text):
                c = source_text[i]
                if c == "\n" or c == "\r":
                    raise LexError("Unterminated f-string expression", line)
                if c in ('"', "'"):
                    quote = c
                    i += 1
                    while i < len(source_text):
                        q = source_text[i]
                        if q == "\n" or q == "\r":
                            raise LexError("Unterminated string in f-string expression", line)
                        if q == "\\":
                            i += 2
                            continue
                        if q == quote:
                            i += 1
                            break
                        i += 1
                    else:
                        raise LexError("Unterminated string in f-string expression", line)
                    continue
                if c == "(":
                    parens += 1
                elif c == ")":
                    parens -= 1
                    if parens < 0:
                        raise LexError("Unbalanced ')' in f-string expression", line)
                elif c == "[":
                    brackets += 1
                elif c == "]":
                    brackets -= 1
                    if brackets < 0:
                        raise LexError("Unbalanced ']' in f-string expression", line)
                elif c == "{":
                    braces += 1
                elif c == "}":
                    if parens == 0 and brackets == 0 and braces == 0:
                        expr = source_text[expr_start:i].strip()
                        if not expr:
                            raise LexError("Empty f-string expression", line)
                        parts.append(("expr", expr, expr))
                        i += 1
                        segment_start = i
                        break
                    braces -= 1
                    if braces < 0:
                        raise LexError("Unbalanced '}' in f-string expression", line)
                i += 1
            else:
                raise LexError("Unterminated f-string expression", line)
            continue
        i += 1
    raise LexError("Unterminated f-string literal", line)


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
        line = line_numbers[pos] if pos < len(line_numbers) else 1
        if source_text.startswith('f"', pos):
            value, end = scan_fstring(source_text, pos, line)
            tokens.append(("FSTRING", value, line, ""))
            pos = end
            continue
        m = TOKEN_RE.match(source_text, pos)
        if not m:
            raise LexError(f"Unexpected character {source_text[pos]!r}", line)
        kind = m.lastgroup
        source_spelling = m.group()
        value = source_spelling
        dump_value = source_spelling
        if kind == "WHITESPACE" or kind == "COMMENT":
            pos = m.end()
            continue
        line = line_numbers[m.start()] if m.start() < len(line_numbers) else 1
        if kind == "NUMBER":
            value = int(source_spelling)
        elif kind == "STRING":
            dump_value = source_spelling[1:-1]
            value = decode_escaped(dump_value, line)
        elif kind == "CHAR":
            decoded = decode_escaped(source_spelling[1:-1], line)
            if len(decoded) != 1:
                raise LexError("Character literal must contain exactly one byte", line)
            value = ord(decoded)
            dump_value = str(value)
        elif kind == "NEWLINE":
            dump_value = "\\n"
        tokens.append((kind, value, line, dump_value))
        pos = m.end()
    return tokens


def dump_line(line, kind, dump_value=""):
    return f"{line}\t{kind}\t{len(dump_value)}\t{dump_value}"


def dump_tokens(tokens):
    lines = []
    for kind, value, line, dump_value in tokens:
        if kind == "FSTRING":
            lines.append(dump_line(line, "FSTRING_BEGIN"))
            for part_kind, part_value, part_dump_value in value:
                if part_kind == "text":
                    lines.append(dump_line(line, "FSTRING_TEXT", part_dump_value))
                elif part_kind == "expr":
                    lines.append(dump_line(line, "FSTRING_EXPR", part_dump_value))
                else:
                    raise LexError(f"Unknown f-string part {part_kind}", line)
            lines.append(dump_line(line, "FSTRING_END"))
            continue

        lines.append(dump_line(line, kind, dump_value))

    return "\n".join(lines) + ("\n" if lines else "")
