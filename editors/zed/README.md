# Epic for Zed

Zed language extension for the current Epic syntax.

## Local development

1. Generate and test the parser:

   ```powershell
   cd tree-sitter-epic
   npm install
   npm run generate
   npm test
   ```

2. Open Zed, run `zed: extensions`, choose `Install Dev Extension`, and select `editors/zed`.

The compiler remains the semantic oracle, while the tracked Tree-sitter grammar is
kept aligned with the accepted source syntax rather than preserving removed forms.