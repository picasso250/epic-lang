const PREC = {
  assignment: 1,
  logical_or: 2,
  logical_and: 3,
  equality: 4,
  bit_or: 5,
  bit_xor: 6,
  bit_and: 7,
  comparison: 8,
  shift: 9,
  additive: 10,
  multiplicative: 11,
  unary: 12,
  postfix: 13,
};

module.exports = grammar({
  name: "epic",

  extras: $ => [
    /[\s\uFEFF\u2060\u200B]/,
    $.comment,
  ],

  word: $ => $.identifier,

  rules: {
    source_file: $ => repeat($._declaration),

    _declaration: $ => choice(
      $.extern_definition,
      $.function_definition,
      $.struct_definition,
      $.union_definition,
    ),

    extern_definition: $ => seq(
      "extern",
      field("library", $.string),
      "fun",
      field("name", $.identifier),
      field("parameters", $.parameters),
      ":",
      field("return_type", $.type),
    ),

    function_definition: $ => seq(
      "fun",
      optional(field("receiver", $.method_receiver)),
      field("name", $.identifier),
      field("parameters", $.parameters),
      ":",
      field("return_type", $.type),
      field("body", $.block),
    ),

    method_receiver: $ => seq(
      "(",
      field("name", $.identifier),
      ":",
      field("type", $.type),
      ")",
    ),

    parameters: $ => seq(
      "(",
      optional(commaSep($.parameter)),
      ")",
    ),

    parameter: $ => seq(
      field("name", $.identifier),
      ":",
      field("type", $.type),
    ),

    struct_definition: $ => seq(
      "type",
      field("name", $.identifier),
      "{",
      repeat($.struct_field),
      "}",
    ),

    struct_field: $ => seq(
      field("name", $.identifier),
      ":",
      field("type", $.type),
    ),

    union_definition: $ => seq(
      "type",
      field("name", $.identifier),
      "=",
      field("member", $.identifier),
      "|",
      field("member", $.identifier),
      repeat(seq("|", field("member", $.identifier))),
    ),

    type: $ => seq(
      field("name", $.identifier),
      repeat(seq("[", "]")),
    ),

    block: $ => seq(
      "{",
      repeat($.statement),
      "}",
    ),

    statement: $ => choice(
      $.let_statement,
      $.return_statement,
      $.if_statement,
      $.for_statement,
      $.break_statement,
      $.continue_statement,
      $.panic_statement,
      $.match_statement,
      $.assignment_statement,
      $.expression_statement,
    ),

    let_statement: $ => seq(
      "let",
      field("name", $.identifier),
      optional(seq(":", field("type", $.type))),
      "=",
      field("value", $.expression),
    ),

    return_statement: $ => prec.right(seq(
      "ret",
      optional(field("value", $.expression)),
    )),

    if_statement: $ => seq(
      "if",
      field("condition", $.expression),
      field("consequence", $.block),
      optional(seq(
        "else",
        field("alternative", choice($.if_statement, $.block)),
      )),
    ),

    for_statement: $ => choice(
      $.for_range_statement,
      $.for_condition_statement,
    ),

    for_condition_statement: $ => seq(
      "for",
      field("condition", $.expression),
      field("body", $.block),
    ),

    for_range_statement: $ => seq(
      "for",
      field("cursor", $.identifier),
      ":",
      field("start", $.expression),
      ":",
      field("end", $.expression),
      field("body", $.block),
    ),

    break_statement: _ => "break",

    continue_statement: _ => "continue",

    panic_statement: $ => seq(
      "panic",
      field("message", $.expression),
    ),

    match_statement: $ => seq(
      "match",
      field("value", $.expression),
      "{",
      repeat($.match_case),
      optional($.match_default_case),
      "}",
    ),

    match_case: $ => choice(
      $.match_variant_case,
      $.match_literal_case,
    ),

    match_variant_case: $ => seq(
      field("variant", $.identifier),
      field("binding", $.identifier),
      ":",
      field("body", $.block),
    ),

    match_literal_case: $ => seq(
      field("pattern", $.match_literal_pattern),
      ":",
      field("body", $.block),
    ),

    match_literal_pattern: $ => choice(
      $.number,
      $.string,
      $.char,
      $.boolean,
    ),

    match_default_case: $ => seq(
      "_",
      ":",
      field("body", $.block),
    ),

    assignment_statement: $ => prec.right(PREC.assignment, seq(
      field("left", choice($.identifier, $.postfix_expression)),
      field("operator", choice(
        "=", "+=", "-=", "*=", "/=", "%=",
        "<<=", ">>=", ">>>=", "&=", "|=", "^=",
      )),
      field("right", $.expression),
    )),

    expression_statement: $ => $.expression,

    expression: $ => choice(
      $.binary_expression,
      $.unary_expression,
      $.postfix_expression,
      $._primary_expression,
    ),

    _primary_expression: $ => choice(
      $.new_expression,
      $.parenthesized_expression,
      $.boolean,
      $.fstring,
      $.string,
      $.char,
      $.number,
      $.identifier,
    ),

    binary_expression: $ => choice(
      ...[
        ["||", PREC.logical_or],
        ["&&", PREC.logical_and],
        ["==", PREC.equality],
        ["!=", PREC.equality],
        ["|", PREC.bit_or],
        ["^", PREC.bit_xor],
        ["&", PREC.bit_and],
        ["<", PREC.comparison],
        ["<=", PREC.comparison],
        [">", PREC.comparison],
        [">=", PREC.comparison],
        ["<<", PREC.shift],
        [">>", PREC.shift],
        [">>>", PREC.shift],
        ["+", PREC.additive],
        ["-", PREC.additive],
        ["*", PREC.multiplicative],
        ["/", PREC.multiplicative],
        ["%", PREC.multiplicative],
      ].map(([operator, precedence]) =>
        prec.left(precedence, seq(
          field("left", $.expression),
          field("operator", operator),
          field("right", $.expression),
        )),
      ),
    ),

    unary_expression: $ => prec(PREC.unary, seq(
      field("operator", choice("!", "-", "~")),
      field("argument", $.expression),
    )),

    postfix_expression: $ => prec.left(PREC.postfix, seq(
      field("object", $._primary_expression),
      repeat1(choice(
        $.call_suffix,
        $.dot_call_suffix,
        $.field_suffix,
        $.subscript_suffix,
        $.slice_suffix,
        $.null_check_suffix,
      )),
    )),

    call_suffix: $ => field("arguments", $.arguments),

    dot_call_suffix: $ => prec(2, seq(
      ".",
      field("method", $.identifier),
      field("arguments", $.arguments),
    )),

    field_suffix: $ => prec(1, seq(
      ".",
      field("field", $.identifier),
    )),

    subscript_suffix: $ => prec(1, seq(
      "[",
      field("index", $.expression),
      "]",
    )),

    slice_suffix: $ => prec(2, seq(
      "[",
      field("start", $.expression),
      ":",
      field("end", $.expression),
      "]",
    )),

    null_check_suffix: _ => "?",

    arguments: $ => seq(
      "(",
      optional(commaSep($.expression)),
      ")",
    ),

    new_expression: $ => choice(
      $.array_literal,
      $.array_allocation,
      $.union_initializer,
      $.struct_initializer,
    ),

    array_literal: $ => prec(4, seq(
      "new",
      field("element_type", $.identifier),
      "[",
      "]",
      "{",
      repeat(seq(field("element", $.expression), optional(","))),
      "}",
    )),

    array_allocation: $ => prec(3, seq(
      "new",
      field("element_type", $.identifier),
      "[",
      optional(field("capacity", $.expression)),
      "]",
    )),

    union_initializer: $ => prec(2, seq(
      "new",
      field("type", $.identifier),
      "(",
      field("payload", $.expression),
      ")",
    )),

    struct_initializer: $ => prec.right(1, seq(
      "new",
      field("type", $.identifier),
      optional($.field_initializer_list),
    )),

    field_initializer_list: $ => seq(
      "{",
      repeat(seq($.field_initializer, optional(","))),
      "}",
    ),

    field_initializer: $ => seq(
      field("name", $.identifier),
      ":",
      field("value", $.expression),
    ),

    parenthesized_expression: $ => seq(
      "(",
      $.expression,
      ")",
    ),

    boolean: _ => choice("true", "false"),

    identifier: _ => /[A-Za-z_][A-Za-z0-9_]*/,

    number: _ => /[0-9]+/,

    fstring: $ => seq(
      "f\"",
      repeat(choice(
        $.fstring_text,
        $.escape_sequence,
        $.fstring_interpolation,
      )),
      "\"",
    ),

    fstring_text: _ => token.immediate(/[^"\\{]+/),

    fstring_interpolation: $ => seq(
      "{",
      field("value", $.expression),
      "}",
    ),

    escape_sequence: _ => token.immediate(/\\[nrt\\"'0]/),

    string: _ => /"([^"\\\r\n]|\\[nrt\\"'0])*"/,

    char: _ => /'([^'\\\r\n]|\\[nrt\\"'0])'/,

    comment: _ => token(seq("#", /.*/)),
  },
});

function commaSep(rule) {
  return seq(rule, repeat(seq(",", rule)), optional(","));
}

function sep1(rule, separator) {
  return seq(rule, repeat(seq(separator, rule)));
}
