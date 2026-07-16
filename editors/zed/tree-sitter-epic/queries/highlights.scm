(comment) @comment

[
  "extern"
  "fun"
  "type"
  "let"
  "ret"
  "if"
  "else"
  "for"
  "panic"
  "match"
  "new"
] @keyword

(break_statement) @keyword
(continue_statement) @keyword
(boolean) @boolean

((identifier) @type.builtin
  (#match? @type.builtin "^(i64|u64|i32|u32|u8|bool|void|str)$"))

(number) @number
(string) @string
(fstring) @string
(char) @character

(function_definition
  name: (identifier) @function)

(extern_definition
  name: (identifier) @function)

(postfix_expression
  object: (identifier) @function.call
  (call_suffix))

(dot_call_suffix
  method: (identifier) @function.method.call)

(struct_definition
  name: (identifier) @type)

(union_definition
  name: (identifier) @type)

(union_definition
  member: (identifier) @type)

(type
  name: (identifier) @type)

(method_receiver
  type: (type
    name: (identifier) @type))

(parameter
  name: (identifier) @variable.parameter)

(method_receiver
  name: (identifier) @variable.parameter)

(let_statement
  name: (identifier) @variable)

(for_range_statement
  cursor: (identifier) @variable)

(struct_field
  name: (identifier) @property)

(field_initializer
  name: (identifier) @property)

(field_suffix
  field: (identifier) @property)

(match_variant_case
  variant: (identifier) @type)

(match_variant_case
  binding: (identifier) @variable)

[
  "=" "+=" "-=" "*=" "/=" "%="
  "<<=" ">>=" ">>>=" "&=" "|=" "^="
  "+" "-" "*" "/" "%"
  "==" "!=" "<" "<=" ">" ">="
  "&&" "||" "&" "|" "^" "~"
  "<<" ">>" ">>>" "!"
] @operator

(null_check_suffix) @operator

[
  "(" ")" "{" "}" "[" "]"
] @punctuation.bracket

[
  "," ":" "."
] @punctuation.delimiter
