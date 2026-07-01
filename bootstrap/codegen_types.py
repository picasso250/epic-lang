"""Code generation mixin split from bootstrap.codegen."""

from ast_nodes import *


class TypeEmitterMixin:
    def get_var_slot(self, name, typ=None):
        if name not in self.local_offset:
            size = self._type_size(typ) if typ else 8
            # 8-byte align
            if self.local_bytes % 8 != 0:
                self.local_bytes += 8 - (self.local_bytes % 8)
            self.local_bytes += size
            self.local_offset[name] = -self.local_bytes
        return self.local_offset[name]

    def _alloc_temp(self):
        """Allocate a compiler temporary frame slot, return rbp-relative offset."""
        nr = self._temp_count
        self._temp_count += 1
        return -(self._temp_base + (nr + 1) * 8)

    def _type_size(self, typ):
        typ = self._internal_type(typ) if typ else typ
        if typ in ("i64", "bool"):
            return 8
        if typ == "i8":
            return 1
        if typ in self.structs:
            return self.structs[typ]["size"]
        if typ.startswith("&"):
            return 8  # pointers are always 8 bytes
        return 8  # unknown, assume i64

    def _global_symbol(self, name):
        return self.globals.get(name)

    def _emit_global_load(self, sym):
        self.emit_mov("rax", f"[{sym['label']}]")

    def _internal_type(self, typ):
        """Lower user-facing types to the internal pointer-heavy representation."""
        if typ is None:
            return None
        if typ.startswith("&"):
            return typ
        if typ.endswith("[]"):
            elem = self._internal_type(typ[:-2])
            if elem.startswith("&"):
                elem = elem[1:]
            self._ensure_array_type(elem)
            return f"&_arr_{elem}"
        if typ == "map[str]i64":
            self._ensure_map_i64_type()
            return "&_map_str_i64"
        if typ in ("i64", "i8", "bool", "void"):
            return typ
        if typ == "u64":
            return "i64"
        if typ == "u8":
            return "i8"
        return f"&{typ}"

    def _array_data_type(self, elem):
        return f"&{elem}" if elem in ("i64", "i8", "bool") else f"&&{elem}"

    def _register_len_data_type(self, name, elem_ptr_type, has_cap=False):
        """Register a {data, len[, cap]} layout type. data is always offset 0."""
        if name not in self.structs:
            fields = [
                {"name": "data", "type": elem_ptr_type, "offset": 0},
                {"name": "len", "type": "i64", "offset": 8},
            ]
            size = 16
            if has_cap:
                fields.append({"name": "cap", "type": "i64", "offset": 16})
                size = 24
            self.structs[name] = {
                "fields": fields,
                "size": size,
            }

    def _ensure_array_type(self, elem):
        arr_type = f"_arr_{elem}"
        self._register_len_data_type(arr_type, self._array_data_type(elem), has_cap=True)
        return arr_type

    def _ensure_map_i64_type(self):
        if "_map_entry_str_i64" not in self.structs:
            self.structs["_map_entry_str_i64"] = {
                "fields": [
                    {"name": "key", "type": "&str", "offset": 0},
                    {"name": "value", "type": "i64", "offset": 8},
                    {"name": "used", "type": "i64", "offset": 16},
                ],
                "size": 24,
            }
        if "_map_str_i64" not in self.structs:
            self.structs["_map_str_i64"] = {
                "fields": [
                    {"name": "entries", "type": "&_map_entry_str_i64", "offset": 0},
                    {"name": "len", "type": "i64", "offset": 8},
                    {"name": "cap", "type": "i64", "offset": 16},
                ],
                "size": 24,
            }

    def _compute_struct_layouts(self, ast):
        self.structs = {}
        self.adts = {}
        # Built-in str type: { data: &i8, len: i64 }
        self._register_len_data_type("str", "&i8")
        self._ensure_array_type("i8")
        self._ensure_array_type("i64")
        # Array-of-str type used by argv.
        self._register_len_data_type("_arr_str", "&&str", has_cap=True)
        for s in ast.structs:
            fields = []
            offset = 0
            for f in s.fields:
                ftype = self._internal_type(f.type)
                fields.append({"name": f.name, "type": ftype, "offset": offset})
                offset += 8
            self.structs[s.name] = {"fields": fields, "size": offset}
        for t in getattr(ast, "types", []):
            variants = {}
            for tag, variant in enumerate(t.variants):
                payload_name = f"{t.name}_{variant.name}"
                fields = []
                offset = 0
                for f in variant.fields:
                    ftype = self._internal_type(f.type)
                    fields.append({"name": f.name, "type": ftype, "offset": offset})
                    offset += 8
                self.structs[payload_name] = {"fields": fields, "size": offset}
                variants[variant.name] = {"tag": tag, "payload": payload_name}
            self.structs[t.name] = {
                "fields": [
                    {"name": "tag", "type": "i64", "offset": 0},
                    {"name": "data", "type": f"&{t.name}_payload", "offset": 8},
                ],
                "size": 16,
            }
            self.adts[t.name] = variants
