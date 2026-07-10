"""
Epic minimal PE linker. Takes NASM .obj (COFF), produces .exe.
Handles REL32 for both imports and section-relative references.
"""

import struct, sys, os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
from coff import build_coff_obj

IMAGE_FILE_MACHINE_AMD64 = 0x8664
IMAGE_SUBSYSTEM_WINDOWS_CUI = 3
SECTION_ALIGN = 0x1000
FILE_ALIGN = 0x200
IMAGE_BASE = 0x140000000
DOS_STUB = bytes.fromhex(
    "4d5a780001000000040000000000000000000000000000004000000000000000"
    "0000000000000000000000000000000000000000000000000000000078000000"
    "0e1fba0e00b409cd21b8014ccd21546869732070726f6772616d2063616e6e"
    "6f742062652072756e20696e20444f53206d6f64652e240000"
)

KERNEL32_HINTS = {
    "CloseHandle": 157,
    "CreateFileA": 222,
    "ExitProcess": 390,
    "GetCommandLineA": 511,
    "GetFileSize": 631,
    "GetProcessHeap": 740,
    "GetStdHandle": 805,
    "HeapAlloc": 892,
    "ReadFile": 1193,
    "WriteFile": 1632,
}

IMPORT_HINTS = {
    "kernel32.dll": KERNEL32_HINTS,
}

IMPORT_DLL_BY_FUNC = {
    func: dll
    for dll, hints in IMPORT_HINTS.items()
    for func in hints
}


def sym_name(sym, strtab):
    if sym['name_off'] is not None:
        end = strtab.find(b'\x00', sym['name_off'])
        return strtab[sym['name_off']:end].decode() if end > 0 else ''
    return sym['name_raw'].rstrip(b'\x00').decode()


def link(obj_path, exe_path):
    with open(obj_path, 'rb') as f:
        return link_coff_bytes(f.read(), exe_path)


def link_blocks(exe_path, text, data, text_relocs, data_relocs, symbols):
    obj = build_coff_obj(text, data, text_relocs, data_relocs, symbols)
    return link_coff_bytes(obj, exe_path)


def link_coff_bytes(obj_data, exe_path):
    data = bytes(obj_data)
    # ── COFF header ──
    machine, nsects, _, symtab_off, nsyms, _, _ = struct.unpack_from('<HHIIIHH', data, 0)

    # ── Section headers + raw data ──
    sections = []
    for i in range(nsects):
        off = 20 + i * 40
        raw = struct.unpack_from('<8sIIIIIIHHI', data, off)
        name = raw[0].rstrip(b'\x00').decode()
        sections.append(dict(name=name, raw_sz=raw[3], raw_off=raw[4],
                             rel_off=raw[5], nrel=raw[7],
                             data=bytearray(data[raw[4]:raw[4]+raw[3]]) if raw[3] else bytearray()))

    # ── Symbol table (with placeholders to preserve original indices) ──
    syms = []
    i = 0
    while i < nsyms:
        pos = symtab_off + i * 18
        raw = struct.unpack_from('<8sIhhBB', data, pos)
        off = None
        if raw[0][:4] == b'\x00\x00\x00\x00':
            off = struct.unpack_from('<I', data, pos + 4)[0]
        syms.append(dict(name_off=off, name_raw=raw[0],
                         value=raw[1], section=raw[2], aux=raw[5]))
        for _ in range(raw[5]):
            syms.append(dict(name_off=None, name_raw=b'', value=0, section=-1, aux=0))
        i += 1 + raw[5]

    strtab_start = symtab_off + nsyms * 18
    strtab_sz = struct.unpack_from('<I', data, strtab_start)[0]
    strtab = data[strtab_start:strtab_start + strtab_sz]

    # ── Find imports ──
    imports = []
    for s in syms:
        if s['section'] == 0 and s['aux'] == 0:
            n = sym_name(s, strtab)
            if n and n not in imports:
                imports.append(n)

    # ── Find all REL32 relocations ──
    relocs = []
    for si, sec in enumerate(sections):
        for ri in range(sec['nrel']):
            rp = sec['rel_off'] + ri * 10
            rva, sym_i, rtype = struct.unpack_from('<IIH', data, rp)
            if rtype == 4 and sym_i < len(syms):
                relocs.append((si, rva, sym_i))

    # ── Section layout ──
    text_sec = next(s for s in sections if 'text' in s['name'])
    data_sec = next(s for s in sections if 'data' in s['name'])
    text_rva = 0x1000

    # Match lld-link's stable import ordering for reproducible output.
    imports = sorted(imports, key=str.lower)

    # ── Build thunks ──
    while len(text_sec['data']) % 16:
        text_sec['data'].append(0xCC)
    thunk_base = text_rva + len(text_sec['data'])
    thunks = bytearray()
    thunk_rva = {}
    for func in imports:
        thunk_rva[func] = thunk_base + len(thunks)
        thunks += b'\xff\x25' + b'\x00\x00\x00\x00' + b'\xCC' * 10
    text_sec['data'].extend(thunks)
    text_sec['virtual_sz'] = len(text_sec['data'])

    idata_rva = align(text_rva + text_sec['virtual_sz'], SECTION_ALIGN)
    idata, iat_map, iat_dir_rva, iat_dir_size = build_idata(imports, idata_rva)
    data_rva = align(idata_rva + len(idata), SECTION_ALIGN) if idata else idata_rva

    # Patch thunk RIP-relative IAT references now that .rdata has its final RVA.
    for func in imports:
        off = thunk_rva[func] - text_rva + 2
        disp = idata_rva + iat_map[func] - (thunk_rva[func] + 6)
        struct.pack_into('<i', text_sec['data'], off, disp)

    # Map section index → RVA
    sec_rva = {}
    for j, s in enumerate(sections):
        if 'text' in s['name']: sec_rva[j] = text_rva
        elif 'data' in s['name']: sec_rva[j] = data_rva

    # ── Find entry point from symbol table ──
    entry_rva = text_rva
    for s in syms:
        if s['section'] > 0:
            n = sym_name(s, strtab)
            if n == '_start':
                entry_rva = sec_rva.get(s['section'] - 1, 0) + s['value']
                break

    # ── Patch all REL32s ──
    for (si, rva, sym_i) in relocs:
        s = syms[sym_i]
        target = 0
        if s['section'] == 0 and s['aux'] == 0:
            func = sym_name(s, strtab)
            target = thunk_rva.get(func, 0)
        elif s['section'] > 0:
            rva_base = sec_rva.get(s['section'] - 1, 0)
            target = rva_base + s['value']
        if target:
            old = struct.unpack_from('<i', text_sec['data'], rva)[0]
            disp = old + target - (text_rva + rva + 4)
            struct.pack_into('<i', text_sec['data'], rva, disp)

    # ── Write PE ──
    return write_pe(exe_path, text_sec, data_sec, data_rva, idata, idata_rva, iat_dir_rva, iat_dir_size, entry_rva)


def build_idata(imports, idata_rva):
    if not imports:
        return b'', {}, 0, 0

    groups = {}
    for func in imports:
        if func.startswith("__ep_import$"):
            _, dll, symbol = func.split("$", 2)
            groups.setdefault(dll.lower(), []).append((func, symbol))
            continue
        dll = IMPORT_DLL_BY_FUNC.get(func)
        if dll is None:
            raise RuntimeError(f"unsupported import: {func}")
        groups.setdefault(dll, []).append((func, func))
    ordered = [(dll, sorted(funcs, key=lambda item: item[1].lower())) for dll, funcs in sorted(groups.items(), key=lambda item: item[0].lower())]

    descriptor_size = (len(ordered) + 1) * 20
    buf = bytearray(b'\x00' * descriptor_size)
    ilt_offsets = {}
    iat_offsets = {}
    hint_offsets = {}
    dll_name_offsets = {}
    iat_map = {}

    def pad_to(n):
        while len(buf) % n:
            buf.append(0)

    for dll, funcs in ordered:
        pad_to(8)
        ilt_offsets[dll] = len(buf)
        buf.extend(b'\x00' * ((len(funcs) + 1) * 8))

    iat_dir_rva = 0
    iat_dir_size = 0
    for dll, funcs in ordered:
        pad_to(8)
        if iat_dir_rva == 0:
            iat_dir_rva = idata_rva + len(buf)
        iat_offsets[dll] = len(buf)
        for idx, (encoded, func) in enumerate(funcs):
            iat_map[encoded] = len(buf) + idx * 8
        buf.extend(b'\x00' * ((len(funcs) + 1) * 8))
    if iat_dir_rva:
        iat_dir_size = idata_rva + len(buf) - iat_dir_rva

    for dll, funcs in ordered:
        hints = IMPORT_HINTS.get(dll, {})
        for encoded, func in funcs:
            pad_to(2)
            hint_offsets[func] = len(buf)
            buf.extend(struct.pack('<H', hints.get(func, 0)))
            buf.extend(func.encode('ascii') + b'\x00')
            pad_to(2)

    for dll, _ in ordered:
        dll_name_offsets[dll] = len(buf)
        buf.extend(dll.encode('ascii') + b'\x00')

    for desc_idx, (dll, funcs) in enumerate(ordered):
        ilt_off = ilt_offsets[dll]
        iat_off = iat_offsets[dll]
        for idx, (encoded, func) in enumerate(funcs):
            thunk = struct.pack('<Q', idata_rva + hint_offsets[func])
            struct.pack_into('<Q', buf, ilt_off + idx * 8, struct.unpack('<Q', thunk)[0])
            struct.pack_into('<Q', buf, iat_off + idx * 8, struct.unpack('<Q', thunk)[0])
        struct.pack_into(
            '<IIIII',
            buf,
            desc_idx * 20,
            idata_rva + ilt_off,
            0,
            0,
            idata_rva + dll_name_offsets[dll],
            idata_rva + iat_off,
        )

    return bytes(buf), iat_map, iat_dir_rva, iat_dir_size


def write_pe(path, text_sec, data_sec, data_rva, idata, idata_rva, iat_dir_rva, iat_dir_size, entry_rva):
    TEXT_RVA = 0x1000
    all_sec = [
        ('.text', TEXT_RVA, bytes(text_sec['data']), 0x60000020, text_sec.get('virtual_sz', len(text_sec['data']))),
    ]
    if idata:
        all_sec.append(('.rdata', idata_rva, idata, 0x40000040, len(idata)))
    all_sec.append(('.data', data_rva, bytes(data_sec['data']), 0xC0000040, len(data_sec['data'])))
    num_sec = len(all_sec)

    text_raw = align(len(text_sec['data']), FILE_ALIGN)
    data_raw = align(len(data_sec['data']), FILE_ALIGN)
    idata_raw = align(len(idata), FILE_ALIGN) if idata else 0
    last_rva = all_sec[-1][1]
    last_sz = all_sec[-1][4]
    image_size = align(last_rva + last_sz, SECTION_ALIGN)

    OPT_HDR = 240
    headers_sz = 0x400

    buf = bytearray(DOS_STUB)
    buf += b'PE\x00\x00'
    buf += struct.pack('<HHIIIHH', IMAGE_FILE_MACHINE_AMD64, num_sec,
                       0, 0, 0, OPT_HDR, 0x0022)
    buf += struct.pack('<HBB', 0x020B, 14, 0)
    buf += struct.pack('<III', text_raw, data_raw + idata_raw, 0)
    buf += struct.pack('<II', entry_rva, TEXT_RVA)
    buf += struct.pack('<Q', IMAGE_BASE)
    buf += struct.pack('<II', SECTION_ALIGN, FILE_ALIGN)
    buf += struct.pack('<HHHH', 6, 0, 0, 0)
    buf += struct.pack('<HH', 6, 0)
    buf += struct.pack('<I', 0)
    buf += struct.pack('<II', image_size, headers_sz)
    buf += struct.pack('<I', 0)
    buf += struct.pack('<HH', IMAGE_SUBSYSTEM_WINDOWS_CUI, 0x8160)
    buf += struct.pack('<QQ', 0x100000, 0x1000)
    buf += struct.pack('<QQ', 0x100000, 0x1000)
    buf += struct.pack('<II', 0, 16)
    # Data directories
    buf += struct.pack('<II', 0, 0)
    if idata:
        buf += struct.pack('<II', idata_rva, len(idata))
    else:
        buf += struct.pack('<II', 0, 0)
    buf += bytes(10 * 8)
    if idata:
        buf += struct.pack('<II', iat_dir_rva, iat_dir_size)
    else:
        buf += struct.pack('<II', 0, 0)
    buf += bytes(3 * 8)
    # Section headers
    for name, rva, sdata, chars, virtual_sz in all_sec:
        raw_sz = align(len(sdata), FILE_ALIGN)
        buf += struct.pack('<8sIIIIIIHHI', name.encode().ljust(8, b'\x00'),
                           virtual_sz, rva, raw_sz, 0, 0, 0, 0, 0, chars)
    # Pad
    while len(buf) < headers_sz: buf.append(0)
    # Patch PointerToRawData
    raw_pos = headers_sz
    opt_start = len(DOS_STUB) + 4 + 20
    for i, (_, _, sdata, _, _) in enumerate(all_sec):
        hdr_pos = opt_start + OPT_HDR + i * 40
        struct.pack_into('<I', buf, hdr_pos + 20, raw_pos)
        struct.pack_into('<I', buf, hdr_pos + 16, align(len(sdata), FILE_ALIGN))
        raw_pos += align(len(sdata), FILE_ALIGN)
    # Section data
    for name, _, sdata, _, _ in all_sec:
        buf += sdata
        pad_byte = 0xCC if name == '.text' else 0
        while len(buf) % FILE_ALIGN: buf.append(pad_byte)

    with open(path, 'wb') as f: f.write(bytes(buf))
    return len(buf)


def align(n, a): return ((n + a - 1) // a) * a


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python bootstrap/link.py <file.obj> [-o out.exe]")
        sys.exit(1)
    obj = sys.argv[1]
    out = sys.argv[sys.argv.index('-o') + 1] if '-o' in sys.argv else os.path.splitext(obj)[0] + '.exe'
    sz = link(obj, out)
    print(f"  OK: {out} ({sz} bytes)")
