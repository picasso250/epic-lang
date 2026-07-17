"""
Epic minimal PE linker. Takes NASM .obj (COFF), produces .exe.
Handles REL32 for both imports and section-relative references.
"""

import struct, sys, os

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
    "HeapAlloc": 892,
    "ReadFile": 1193,
    "SetFilePointer": 1384,
    "WriteFile": 1632,
}


def sym_name(sym, strtab):
    if sym['name_off'] is not None:
        end = strtab.find(b'\x00', sym['name_off'])
        return strtab[sym['name_off']:end].decode() if end > 0 else ''
    return sym['name_raw'].rstrip(b'\x00').decode()


def link(obj_path, exe_path):
    data = open(obj_path, 'rb').read()

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
    idata, iat_map = build_idata(imports, idata_rva)
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
    return write_pe(exe_path, text_sec, data_sec, data_rva, idata, idata_rva, imports, entry_rva)


def build_idata(imports, idata_rva):
    if not imports: return b'', {}
    ILT_OFF = 40
    TABLE_SIZE = len(imports) * 8 + 8
    IAT_OFF = ILT_OFF + TABLE_SIZE
    HINT_OFF = IAT_OFF + TABLE_SIZE

    iat_map = {}
    hint_blob = bytearray()
    for func in imports:
        hint_blob += struct.pack('<H', KERNEL32_HINTS.get(func, 0)) + func.encode() + b'\x00'
        if len(hint_blob) % 2: hint_blob += b'\x00'

    DLL_OFF = HINT_OFF + len(hint_blob)
    ilt = bytearray()
    for idx, func in enumerate(imports):
        hoff = sum(2 + len(f.encode()) + 1 + (1 if (2 + len(f.encode()) + 1) % 2 else 0)
                   for f in imports[:idx])
        ilt += struct.pack('<Q', idata_rva + HINT_OFF + hoff)
        iat_map[func] = IAT_OFF + idx * 8
    ilt += struct.pack('<Q', 0)
    iat = bytearray(ilt)

    idt = struct.pack('<IIIII', idata_rva + ILT_OFF, 0, 0,
                      idata_rva + DLL_OFF, idata_rva + IAT_OFF)
    idt += bytes(20)
    return bytes(idt + ilt + iat + hint_blob) + b'KERNEL32.dll\x00', iat_map


def write_pe(path, text_sec, data_sec, data_rva, idata, idata_rva, imports, entry_rva):
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
        buf += struct.pack('<II', idata_rva, 40)
    else:
        buf += struct.pack('<II', 0, 0)
    buf += bytes(10 * 8)
    if idata:
        buf += struct.pack('<II', idata_rva + 40 + (len(imports) + 1) * 8, (len(imports) + 1) * 8)
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
        print("Usage: python link.py <file.obj> [-o out.exe]")
        sys.exit(1)
    obj = sys.argv[1]
    out = sys.argv[sys.argv.index('-o') + 1] if '-o' in sys.argv else os.path.splitext(obj)[0] + '.exe'
    sz = link(obj, out)
    print(f"  OK: {out} ({sz} bytes)")
