"""Minimal text MIR parser for runtime helper files.

This parser is intentionally small: it parses the text MIR subset we keep under
runtime/mir and produces the existing MIR object model. Text sigils are syntax
only: module symbols may be written with @, locals are written with %, and both
are stored raw in the object model.
"""

from __future__ import annotations

import re
from pathlib import Path

from mir import (
    BOOL,
    I32,
    I64,
    I8,
    PTR,
    VOID,
    Br,
    CondBr,
    ConstBoolOperand,
    ConstIntOperand,
    ConstNullOperand,
    MirBlock,
    MirExtern,
    MirFunction,
    MirGlobal,
    MirImport,
    MirInst,
    MirParam,
    MirProgram,
    MirSignature,
    MirValue,
    Ret,
    SymbolOperand,
    ValueOperand,
    array,
    struct,
    validate,
)


class MirParseError(RuntimeError):
    pass


_SIMPLE_TYPES = {
    "i64": I64,
    "i32": I32,
    "i8": I8,
    "bool": BOOL,
    "void": VOID,
    "ptr": PTR,
}


def parse_mir_file(path):
    return parse_mir_text(Path(path).read_text(encoding="utf-8"), filename=str(path))


def parse_mir_text(text, filename="<mir>"):
    parser = _MirTextParser(text, filename)
    program = parser.parse_program()
    validate(program)
    return program


def _strip_module_sigil(name):
    return name[1:] if name.startswith("@") else name


def _strip_local_sigil(name):
    if not name.startswith("%"):
        raise MirParseError(f"local value must use % sigil in text MIR: {name}")
    return name[1:]


class _MirTextParser:
    def __init__(self, text, filename):
        self.filename = filename
        self.lines = []
        for line_no, raw in enumerate(text.splitlines(), 1):
            line = raw.split("//", 1)[0].strip()
            if line:
                self.lines.append((line_no, line))
        self.i = 0

    def parse_program(self):
        program = MirProgram()
        while not self._done():
            line_no, line = self._peek()
            if line.startswith("import "):
                program.imports.append(self._parse_import(line_no, line))
                self.i += 1
            elif line.startswith("declare "):
                program.externs.append(self._parse_declare(line_no, line))
                self.i += 1
            elif line.startswith("define "):
                program.functions.append(self._parse_function())
            elif " = global " in line:
                program.globals.append(self._parse_global(line_no, line))
                self.i += 1
            else:
                self._error(line_no, f"expected import, declare, global, or define; got: {line}")
        return program

    def _parse_import(self, line_no, line):
        m = re.fullmatch(r"import\s+(.+?)\s+(@?[A-Za-z_.$][A-Za-z0-9_.$]*)\((.*)\)", line)
        if not m:
            self._error(line_no, f"invalid import: {line}")
        return MirImport(
            _strip_module_sigil(m.group(2)),
            self._parse_signature_parts(m.group(3), m.group(1), line_no),
        )

    def _parse_declare(self, line_no, line):
        m = re.fullmatch(r"declare\s+(.+?)\s+(@?[A-Za-z_.$][A-Za-z0-9_.$]*)\((.*)\)", line)
        if not m:
            self._error(line_no, f"invalid declare: {line}")
        return MirExtern(
            _strip_module_sigil(m.group(2)),
            self._parse_signature_parts(m.group(3), m.group(1), line_no),
        )

    def _parse_global(self, line_no, line):
        m = re.fullmatch(r"(@?[A-Za-z_.$][A-Za-z0-9_.$]*):\s*(.+?)\s*=\s*global\s*(.*)", line)
        if not m:
            self._error(line_no, f"invalid global: {line}")
        return MirGlobal(_strip_module_sigil(m.group(1)), self._parse_type(m.group(2)), self._parse_global_init(m.group(3)))

    def _parse_global_init(self, text):
        text = text.strip()
        if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
            return bytes(text[1:-1], "utf-8").decode("unicode_escape")
        return text

    def _parse_function(self):
        line_no, header = self._next()
        m = re.fullmatch(r"define\s+(.+?)\s+(@?[A-Za-z_.$][A-Za-z0-9_.$]*)\((.*)\)\s*\{", header)
        if not m:
            self._error(line_no, f"invalid function header: {header}")
        name = _strip_module_sigil(m.group(2))
        params = self._parse_params(m.group(3), line_no)
        ret = self._parse_type(m.group(1))
        blocks = []
        current = None
        while not self._done():
            body_line_no, line = self._next()
            if line == "}":
                if current is not None:
                    blocks.append(current)
                return MirFunction(name, params, ret, blocks)
            if line.endswith(":"):
                if current is not None:
                    blocks.append(current)
                current = MirBlock(line[:-1], [], None)
                continue
            if current is None:
                self._error(body_line_no, "instruction before first block label")
            parsed = self._parse_statement(body_line_no, line)
            if isinstance(parsed, (Br, CondBr, Ret)):
                current.terminator = parsed
            else:
                current.instructions.append(parsed)
        self._error(line_no, f"missing closing }} for function {name}")

    def _parse_params(self, text, line_no):
        text = text.strip()
        if not text:
            return []
        params = []
        for part in self._split_commas(text):
            typ, name = self._parse_typed_name(part, line_no)
            params.append(MirParam(_strip_local_sigil(name), typ))
        return params

    def _parse_signature_parts(self, params_text, ret_text, line_no):
        params = [] if not params_text.strip() else [self._parse_type(part) for part in self._split_commas(params_text)]
        return MirSignature(params, self._parse_type(ret_text))

    def _parse_statement(self, line_no, line):
        if line.startswith("br "):
            m = re.fullmatch(r"br\s+label\s+%([A-Za-z_.$][A-Za-z0-9_.$]*)", line)
            if not m:
                self._error(line_no, f"invalid br: {line}")
            return Br(m.group(1))
        if line.startswith("condbr "):
            rest = line[len("condbr "):]
            parts = self._split_commas(rest)
            if len(parts) != 3:
                self._error(line_no, f"invalid condbr: {line}")
            cond = self._parse_typed_operand(parts[0], line_no)
            then_target = self._parse_label_operand(parts[1], line_no)
            else_target = self._parse_label_operand(parts[2], line_no)
            return CondBr(cond, then_target, else_target)
        if line.startswith("ret "):
            rest = line[len("ret "):]
            if rest == "void":
                return Ret(None)
            return Ret(self._parse_typed_operand(rest, line_no))

        result = None
        result_type = None
        if " = " in line:
            lhs, line = line.split(" = ", 1)
            result_name, result_type = self._parse_result_lhs(lhs, line_no)
            result = MirValue(_strip_local_sigil(result_name), result_type)

        if line.startswith("alloca "):
            return MirInst("alloca", result=result, type=self._parse_type(line[len("alloca "):]))
        if line.startswith("load "):
            typ, rest = self._parse_type_prefix(line[len("load "):], line_no)
            rest = rest.strip()
            if rest.startswith(","):
                rest = rest[1:].strip()
            return MirInst("load", [self._parse_typed_operand(rest, line_no)], result=result, type=typ)
        if line.startswith("store "):
            parts = self._split_commas(line[len("store "):])
            if len(parts) != 2:
                self._error(line_no, f"invalid store: {line}")
            return MirInst("store", [self._parse_typed_operand(parts[0], line_no), self._parse_typed_operand(parts[1], line_no)])
        if line.startswith("call "):
            typ, rest = self._parse_type_prefix(line[len("call "):], line_no)
            m = re.fullmatch(r"(@?[A-Za-z_.$][A-Za-z0-9_.$]*)\((.*)\)", rest.strip())
            if not m:
                self._error(line_no, f"invalid call: {line}")
            args_text = m.group(2).strip()
            args = [] if not args_text else [self._parse_typed_operand(part, line_no) for part in self._split_commas(args_text)]
            return MirInst("call", args, result=result, type=typ, callee=_strip_module_sigil(m.group(1)))
        if line.startswith("const "):
            return MirInst("const", [self._parse_typed_operand(line[len("const "):], line_no)], result=result, type=result_type)
        if line.startswith("not "):
            return MirInst("not", [self._parse_typed_operand(line[len("not "):], line_no)], result=result)
        if line.startswith("gep "):
            typ, rest = self._parse_type_prefix(line[len("gep "):], line_no)
            rest = rest.strip()
            if rest.startswith(","):
                rest = rest[1:].strip()
            parts = self._split_commas(rest)
            if not parts:
                self._error(line_no, f"invalid gep: {line}")
            return MirInst("gep", [self._parse_typed_operand(part, line_no) for part in parts], result=result, type=typ)
        if line.startswith("ptrtoint "):
            m = re.fullmatch(r"(.+)\s+to\s+(.+)", line[len("ptrtoint "):])
            if not m:
                self._error(line_no, f"invalid ptrtoint: {line}")
            return MirInst("ptrtoint", [self._parse_typed_operand(m.group(1), line_no)], result=result, type=self._parse_type(m.group(2)))

        op, _, operands_text = line.partition(" ")
        if op in {"add", "sub", "mul", "sdiv", "udiv", "srem", "urem", "and", "or", "xor", "shl", "sar", "shr"} or op.startswith("icmp."):
            operands = [self._parse_typed_operand(part, line_no) for part in self._split_commas(operands_text)]
            return MirInst(op, operands, result=result)
        self._error(line_no, f"unsupported instruction: {line}")

    def _parse_label_operand(self, text, line_no):
        m = re.fullmatch(r"label\s+%([A-Za-z_.$][A-Za-z0-9_.$]*)", text.strip())
        if not m:
            self._error(line_no, f"invalid label operand: {text}")
        return m.group(1)

    def _parse_typed_operand(self, text, line_no):
        typ, rest = self._parse_type_prefix(text, line_no)
        value = rest.strip()
        if not value:
            self._error(line_no, f"missing operand value: {text}")
        if value.startswith("%"):
            return ValueOperand(MirValue(_strip_local_sigil(value), typ))
        if value.startswith("@"):
            return SymbolOperand(typ, _strip_module_sigil(value))
        if value == "null":
            return ConstNullOperand()
        if value == "true":
            return ConstBoolOperand(True)
        if value == "false":
            return ConstBoolOperand(False)
        if re.fullmatch(r"-?[0-9]+", value):
            return ConstIntOperand(typ, int(value))
        return SymbolOperand(typ, _strip_module_sigil(value))

    def _parse_typed_name(self, text, line_no):
        typ, rest = self._parse_type_prefix(text, line_no)
        name = rest.strip()
        if not name:
            self._error(line_no, f"missing name after type: {text}")
        return typ, name

    def _parse_result_lhs(self, text, line_no):
        if ":" in text:
            name, typ = text.split(":", 1)
            return name.strip(), self._parse_type(typ.strip())
        typ, name = self._parse_typed_name(text, line_no)
        return name, typ

    def _parse_type(self, text):
        typ, rest = self._parse_type_prefix(text, None)
        if rest.strip():
            raise MirParseError(f"trailing tokens after type {text!r}: {rest!r}")
        return typ

    def _parse_type_prefix(self, text, line_no):
        tokens = text.strip().split()
        if not tokens:
            self._error(line_no, "expected type")
        typ, used = self._parse_type_tokens(tokens, 0, line_no)
        return typ, " ".join(tokens[used:])

    def _parse_type_tokens(self, tokens, pos, line_no):
        tok = tokens[pos]
        if tok in _SIMPLE_TYPES:
            return _SIMPLE_TYPES[tok], pos + 1
        if tok == "struct":
            if pos + 1 >= len(tokens):
                self._error(line_no, "struct type needs a name")
            return struct(tokens[pos + 1]), pos + 2
        if tok == "array":
            if pos + 3 >= len(tokens) or tokens[pos + 2] != "x":
                self._error(line_no, "array type must be `array N x T`")
            elem, end = self._parse_type_tokens(tokens, pos + 3, line_no)
            return array(int(tokens[pos + 1]), elem), end
        self._error(line_no, f"unknown type: {tok}")

    def _split_commas(self, text):
        parts = []
        current = []
        depth = 0
        in_string = False
        escaped = False
        for ch in text:
            if in_string:
                current.append(ch)
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
                current.append(ch)
            elif ch in "([":
                depth += 1
                current.append(ch)
            elif ch in ")]":
                depth -= 1
                current.append(ch)
            elif ch == "," and depth == 0:
                parts.append("".join(current).strip())
                current = []
            else:
                current.append(ch)
        last = "".join(current).strip()
        if last:
            parts.append(last)
        return parts

    def _peek(self):
        return self.lines[self.i]

    def _next(self):
        line = self.lines[self.i]
        self.i += 1
        return line

    def _done(self):
        return self.i >= len(self.lines)

    def _error(self, line_no, message):
        prefix = f"{self.filename}:{line_no}: " if line_no is not None else f"{self.filename}: "
        raise MirParseError(prefix + message)
