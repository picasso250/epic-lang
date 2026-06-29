import epicfmt


def test_formats_basic_blocks():
    source = """fun main(): void {
let x = 1
if x {
putc(65)
} else {
putc(66)
}
}
"""
    assert epicfmt.format_text(source) == """fun main(): void {
    let x = 1
    if x {
        putc(65)
    } else {
        putc(66)
    }
}
"""


def test_ignores_braces_in_literals_and_comments():
    source = """fun main(): void {
putstr("{")
putstr("}")
# {
if 1 {
putc('}')
}
}
"""
    assert epicfmt.format_text(source) == """fun main(): void {
    putstr("{")
    putstr("}")
    # {
    if 1 {
        putc('}')
    }
}
"""


def test_preserves_blank_lines_and_trailing_text():
    source = "fun main(): void {\n\nputc(65)    \n}\n"
    assert epicfmt.format_text(source) == "fun main(): void {\n\n    putc(65)    \n}\n"


def test_preserves_crlf_newlines():
    source = "fun main(): void {\r\nputc(65)\r\n}\r\n"
    assert epicfmt.format_text(source) == "fun main(): void {\r\n    putc(65)\r\n}\r\n"


def test_splits_statements_after_open_braces_and_before_close_braces():
    source = """fun main(): void {
if a { x = 1
y = 2
} else if b { z = 3
w = 4 } else { q = 5 }
}
"""
    assert epicfmt.format_text(source) == """fun main(): void {
    if a {
        x = 1
        y = 2
    } else if b {
        z = 3
        w = 4
    } else {
        q = 5
    }
}
"""


def test_does_not_split_braces_in_literals_or_comments():
    source = """fun main(): void { putstr("{ }") # } {
}
"""
    assert epicfmt.format_text(source) == """fun main(): void {
    putstr("{ }") # } {
}
"""
