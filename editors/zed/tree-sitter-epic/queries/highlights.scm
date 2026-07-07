(comment) @comment

[
  (function_definition)
  (struct_definition)
  (let_statement)
  (return_statement)
  (if_statement)
  (while_statement)
  (new_expression)
  (break_statement)
  (continue_statement)
] @keyword

((identifier) @type.builtin
  (#match? @type.builtin "^(i64|i8|void|str)$"))

(number) @number
(string) @string
(char) @character

(function_definition
  name: (identifier) @function)

(call_expression
  function: (identifier) @function)

(struct_definition
  name: (identifier) @type)

(type
  (identifier) @type)

(parameter
  name: (identifier) @variable.parameter)

(let_statement
  name: (identifier) @variable)

(field_expression
  field: (identifier) @property)

[
  "+"
  "-"
  "*"
  "/"
  "%"
  "=="
  "!="
  "<"
  "<="
  ">"
  ">="
  "&&"
  "||"
  "!"
  "&"
  "="
] @operator

[
  "("
  ")"
  "{"
  "}"
  "["
  "]"
] @punctuation.bracket

[
  ","
  ":"
  "."
] @punctuation.delimiter
