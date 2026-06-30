# Epic for Zed

Minimal Zed language extension for Epic syntax highlighting.

## Local development

1. Generate the parser:

   ```powershell
   cd tree-sitter-epic
   npm install
   npm run generate
   ```

2. Open Zed, run `zed: extensions`, choose `Install Dev Extension`, and select `editors/zed`.

The extension intentionally keeps the Tree-sitter grammar broad and lightweight. It is for editor highlighting, not for compiler validation.
