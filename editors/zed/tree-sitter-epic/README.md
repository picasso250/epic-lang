# tree-sitter-epic

Tree-sitter grammar and editor queries for the current Epic language surface.

The grammar follows the Python reference parser for declarations, statements,
expressions, ADTs, methods, range loops, `match`, and postfix null checks. Compiler
semantic validation remains authoritative, but removed syntax is not intentionally
kept as an editor compatibility layer.

Local dependency folders such as `node_modules/` are not part of the repository.