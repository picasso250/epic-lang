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
