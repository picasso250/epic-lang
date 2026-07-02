"""Minimal AMD64 COFF object writer for Epic's machine backend."""

import struct


IMAGE_FILE_MACHINE_AMD64 = 0x8664
IMAGE_SCN_CNT_CODE = 0x00000020
IMAGE_SCN_CNT_INITIALIZED_DATA = 0x00000040
IMAGE_SCN_MEM_EXECUTE = 0x20000000
IMAGE_SCN_MEM_READ = 0x40000000
IMAGE_SCN_MEM_WRITE = 0x80000000
IMAGE_REL_AMD64_REL32 = 0x0004


def _align(data, n):
    while len(data) % n:
        data.append(0)


def _coff_name(name, strings):
    raw = name.encode("ascii")
    if len(raw) <= 8:
        return raw.ljust(8, b"\x00")
    off = 4 + len(strings)
    strings.extend(raw + b"\x00")
    return b"\x00\x00\x00\x00" + struct.pack("<I", off)


def build_coff_obj(text, data, text_relocs, data_relocs, symbols):
    """Build a two-section COFF object.

    symbols is a dict: name -> (section_number, value). section 0 means external.
    reloc entries are (section_offset, symbol_name).
    """
    section_count = 2
    header_size = 20
    section_table_size = section_count * 40
    raw_offset = header_size + section_table_size

    text_raw = raw_offset
    text_data = bytearray(text)
    data_raw = text_raw + len(text_data)
    data_data = bytearray(data)
    text_rel_off = data_raw + len(data_data)
    data_rel_off = text_rel_off + len(text_relocs) * 10
    symtab_off = data_rel_off + len(data_relocs) * 10

    strings = bytearray()
    symbol_items = list(symbols.items())
    symbol_index = {name: idx for idx, (name, _) in enumerate(symbol_items)}

    symtab = bytearray()
    for name, (section, value) in symbol_items:
        symtab += _coff_name(name, strings)
        symtab += struct.pack("<IhHBB", value, section, 0, 2, 0)

    strtab = struct.pack("<I", 4 + len(strings)) + strings

    def section_header(name, size, raw, rel_off, rel_count, chars):
        return struct.pack(
            "<8sIIIIIIHHI",
            name.encode("ascii").ljust(8, b"\x00"),
            0,
            0,
            size,
            raw if size else 0,
            rel_off if rel_count else 0,
            0,
            rel_count,
            0,
            chars,
        )

    buf = bytearray()
    buf += struct.pack(
        "<HHIIIHH",
        IMAGE_FILE_MACHINE_AMD64,
        section_count,
        0,
        symtab_off,
        len(symbol_items),
        0,
        0,
    )
    buf += section_header(
        ".text",
        len(text_data),
        text_raw,
        text_rel_off,
        len(text_relocs),
        IMAGE_SCN_CNT_CODE | IMAGE_SCN_MEM_EXECUTE | IMAGE_SCN_MEM_READ,
    )
    buf += section_header(
        ".data",
        len(data_data),
        data_raw,
        data_rel_off,
        len(data_relocs),
        IMAGE_SCN_CNT_INITIALIZED_DATA | IMAGE_SCN_MEM_READ | IMAGE_SCN_MEM_WRITE,
    )
    buf += text_data
    buf += data_data
    for off, sym in text_relocs:
        buf += struct.pack("<IIH", off, symbol_index[sym], IMAGE_REL_AMD64_REL32)
    for off, sym in data_relocs:
        buf += struct.pack("<IIH", off, symbol_index[sym], IMAGE_REL_AMD64_REL32)
    buf += symtab
    buf += strtab

    return bytes(buf)


def write_coff_obj(path, text, data, text_relocs, data_relocs, symbols):
    obj = build_coff_obj(text, data, text_relocs, data_relocs, symbols)
    with open(path, "wb") as f:
        f.write(obj)

