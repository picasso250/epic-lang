import epicfmt


def test_formats_basic_blocks():
    source = """fun main(): void {
let x = 1
if x {
println(65)
} else {
println(66)
}
}
"""
    assert epicfmt.format_text(source) == """fun main(): void {
    let x = 1
    if x {
        println(65)
    } else {
        println(66)
    }
}
"""


def test_ignores_braces_in_literals_and_comments():
    source = """fun main(): void {
println("{")
println("}")
# {
if 1 {
println('}')
}
}
"""
    assert epicfmt.format_text(source) == """fun main(): void {
    println("{")
    println("}")
    # {
    if 1 {
        println('}')
    }
}
"""


def test_preserves_blank_lines_and_trailing_text():
    source = "fun main(): void {\n\nprintln(65)    \n}\n"
    assert epicfmt.format_text(source) == "fun main(): void {\n\n    println(65)    \n}\n"


def test_preserves_crlf_newlines():
    source = "fun main(): void {\r\nprintln(65)\r\n}\r\n"
    assert epicfmt.format_text(source) == "fun main(): void {\r\n    println(65)\r\n}\r\n"


def test_preserves_existing_line_breaks():
    source = """fun main(): void {
if a { x = 1
y = 2
} else if b { z = 3
w = 4 } else { q = 5 }
}
"""
    assert epicfmt.format_text(source) == """fun main(): void {
    if a { x = 1
        y = 2
    } else if b { z = 3
        w = 4 } else { q = 5 }
}
"""


def test_keeps_inline_match_patterns_on_one_line():
    source = """fun main(): void {
match t.data {
TokenData.FString { parts }: {
println("x")
}
}
}
"""
    assert epicfmt.format_text(source) == """fun main(): void {
    match t.data {
        TokenData.FString { parts }: {
            println("x")
        }
    }
}
"""


def test_does_not_split_braces_in_literals_or_comments():
    source = """fun main(): void { println("{ }") # } {
}
"""
    assert epicfmt.format_text(source) == """fun main(): void { println("{ }") # } {
}
"""
