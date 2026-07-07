const PREC = {
  assign: 1,
  or: 2,
  and: 3,
  equality: 4,
  compare: 5,
  add: 6,
  multiply: 7,
  unary: 8,
  call: 9,
};

module.exports = grammar({
  name: "epic",

  extras: $ => [
    /\s/,
    $.comment,
  ],

  word: $ => $.identifier,

  rules: {
    source_file: $ => repeat($._item),

    _item: $ => choice(
      $.function_definition,
      $.struct_definition,
      $.statement,
    ),

    function_definition: $ => seq(
      "fun",
      field("name", $.identifier),
      $.parameters,
      ":",
      field("return_type", $.type),
      field("body", $.block),
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
      "struct",
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

    type: $ => seq(
      $.identifier,
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
      $.while_statement,
      $.break_statement,
      $.continue_statement,
      $.assignment_statement,
      $.expression_statement,
    ),

    let_statement: $ => seq(
      "let",
      field("name", $.identifier),
      optional(seq("=", field("value", $.expression))),
    ),

    return_statement: $ => prec.right(seq(
      "ret",
      optional(field("value", $.expression)),
    )),

    if_statement: $ => seq(
      "if",
      field("condition", $.expression),
      field("consequence", $.block),
      optional(seq("else", field("alternative", choice($.if_statement, $.block)))),
    ),

    while_statement: $ => seq(
      "for",
      field("condition", $.expression),
      field("body", $.block),
    ),

    break_statement: _ => "break",

    continue_statement: _ => "continue",

    assignment_statement: $ => prec.right(PREC.assign, seq(
      field("left", choice($.identifier, $.field_expression, $.subscript_expression)),
      "=",
      field("right", $.expression),
    )),

    expression_statement: $ => $.expression,

    expression: $ => choice(
      $.binary_expression,
      $.unary_expression,
      $.call_expression,
      $.field_expression,
      $.subscript_expression,
      $.new_expression,
      $.parenthesized_expression,
      $.identifier,
      $.number,
      $.string,
      $.char,
    ),

    binary_expression: $ => choice(
      ...[
        ["||", PREC.or],
        ["&&", PREC.and],
        ["==", PREC.equality],
        ["!=", PREC.equality],
        ["<", PREC.compare],
        ["<=", PREC.compare],
        [">", PREC.compare],
        [">=", PREC.compare],
        ["+", PREC.add],
        ["-", PREC.add],
        ["*", PREC.multiply],
        ["/", PREC.multiply],
        ["%", PREC.multiply],
      ].map(([operator, precedence]) =>
        prec.left(precedence, seq(
          field("left", $.expression),
          field("operator", operator),
          field("right", $.expression),
        )),
      ),
    ),

    unary_expression: $ => prec(PREC.unary, seq(
      field("operator", choice("!", "-", "&")),
      field("argument", $.expression),
    )),

    call_expression: $ => prec(PREC.call, seq(
      field("function", choice($.identifier, $.field_expression)),
      "(",
      optional(commaSep($.expression)),
      ")",
    )),

    field_expression: $ => prec(PREC.call, seq(
      field("object", $.expression),
      ".",
      field("field", $.identifier),
    )),

    subscript_expression: $ => prec(PREC.call, seq(
      field("object", $.expression),
      "[",
      field("index", $.expression),
      "]",
    )),

    new_expression: $ => prec.right(PREC.call, seq(
      "new",
      field("type", $.identifier),
      optional(seq("[", field("capacity", $.expression), "]")),
    )),

    parenthesized_expression: $ => seq("(", $.expression, ")"),

    identifier: _ => /[A-Za-z_][A-Za-z0-9_]*/,

    number: _ => /[0-9]+/,

    string: _ => /"([^"\\\r\n]|\\[nrt\\"'0])*"/,

    char: _ => /'([^'\\\r\n]|\\[nrt\\"'0])'/,

    comment: _ => token(seq("#", /.*/)),
  },
});

function commaSep(rule) {
  return seq(rule, repeat(seq(",", rule)), optional(","));
}
