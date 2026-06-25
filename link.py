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
    imports = [sym_name(s, strtab) for s in syms
               if s['section'] == 0 and s['aux'] == 0 and s['name_off'] is not None]

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
    data_rva = 0x2000
    idata_rva = 0x3000

    # Map section index → RVA
    sec_rva = {}
    for j, s in enumerate(sections):
        if 'text' in s['name']: sec_rva[j] = text_rva
        elif 'data' in s['name']: sec_rva[j] = data_rva

    # ── Build .idata ──
    idata, iat_map = build_idata(imports, idata_rva)

    # ── Build thunks ──
    thunk_base = text_rva + len(text_sec['data'])
    thunks = bytearray()
    thunk_rva = {}
    for func in imports:
        thunk_rva[func] = thunk_base + len(thunks)
        disp = idata_rva + iat_map[func] - (thunk_rva[func] + 6)
        thunks += b'\xff\x25' + struct.pack('<i', disp)
    text_sec['data'].extend(thunks)

    # ── Patch all REL32s ──
    for (si, rva, sym_i) in relocs:
        s = syms[sym_i]
        target = 0
        if s['section'] == 0 and s['aux'] == 0 and s['name_off'] is not None:
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
    return write_pe(exe_path, text_sec, data_sec, idata, idata_rva, imports)


def build_idata(imports, idata_rva):
    if not imports: return b'', {}
    ILT_OFF = 40
    ILT_SIZE = len(imports) * 8 + 8
    HINT_OFF = ILT_OFF + ILT_SIZE

    iat_map = {}
    hint_blob = bytearray()
    for func in imports:
        hint_blob += struct.pack('<H', 0) + func.encode() + b'\x00'
        if len(hint_blob) % 2: hint_blob += b'\x00'

    DLL_OFF = HINT_OFF + len(hint_blob)
    ilt = bytearray()
    for idx, func in enumerate(imports):
        hoff = sum(2 + len(f.encode()) + 1 + (1 if (2 + len(f.encode()) + 1) % 2 else 0)
                   for f in imports[:idx])
        ilt += struct.pack('<Q', idata_rva + HINT_OFF + hoff)
        iat_map[func] = ILT_OFF + idx * 8
    ilt += struct.pack('<Q', 0)

    idt = struct.pack('<IIIII', idata_rva + ILT_OFF, 0, 0,
                      idata_rva + DLL_OFF, idata_rva + ILT_OFF)
    idt += bytes(20)
    return bytes(idt + ilt + hint_blob) + b'kernel32.dll\x00', iat_map


def write_pe(path, text_sec, data_sec, idata, idata_rva, imports):
    TEXT_RVA, DATA_RVA = 0x1000, 0x2000
    all_sec = [
        ('.text', TEXT_RVA, bytes(text_sec['data']), 0x60000020),
        ('.data', DATA_RVA, bytes(data_sec['data']), 0xC0000040),
    ]
    if idata:
        all_sec.append(('.idata', idata_rva, idata, 0xC0000040))
    num_sec = len(all_sec)

    text_raw = align(len(text_sec['data']), FILE_ALIGN)
    data_raw = align(len(data_sec['data']), FILE_ALIGN)
    idata_raw = align(len(idata), FILE_ALIGN) if idata else 0
    last_rva = idata_rva if idata else DATA_RVA
    last_sz = len(idata) if idata else len(data_sec['data'])
    image_size = align(last_rva + last_sz, SECTION_ALIGN)

    OPT_HDR = 240
    headers_sz = align(64 + 4 + 20 + OPT_HDR + num_sec * 40, FILE_ALIGN)

    buf = bytearray(b'MZ' + b'\x00' * 58)
    buf[0x3C:0x40] = struct.pack('<I', 0x40)
    buf += b'PE\x00\x00'
    buf += struct.pack('<HHIIIHH', IMAGE_FILE_MACHINE_AMD64, num_sec,
                       0, 0, 0, OPT_HDR, 0x0022)
    buf += struct.pack('<HBB', 0x020B, 0, 0)
    buf += struct.pack('<III', text_raw, data_raw + idata_raw, 0)
    buf += struct.pack('<II', TEXT_RVA, TEXT_RVA)
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
        buf += struct.pack('<II', idata_rva, (len(imports) + 1) * 20)
    else:
        buf += struct.pack('<II', 0, 0)
    buf += bytes(14 * 8)
    # Section headers
    for name, rva, sdata, chars in all_sec:
        raw_sz = align(len(sdata), FILE_ALIGN)
        buf += struct.pack('<8sIIIIIIHHI', name.encode().ljust(8, b'\x00'),
                           len(sdata), rva, raw_sz, 0, 0, 0, 0, 0, chars)
    # Pad
    while len(buf) < headers_sz: buf.append(0)
    # Patch PointerToRawData
    raw_pos = headers_sz
    opt_start = 64 + 4 + 20
    for i, (_, _, sdata, _) in enumerate(all_sec):
        hdr_pos = opt_start + OPT_HDR + i * 40
        struct.pack_into('<I', buf, hdr_pos + 20, raw_pos)
        struct.pack_into('<I', buf, hdr_pos + 16, align(len(sdata), FILE_ALIGN))
        raw_pos += align(len(sdata), FILE_ALIGN)
    # Section data
    for _, _, sdata, _ in all_sec:
        buf += sdata
        while len(buf) % FILE_ALIGN: buf.append(0)

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
