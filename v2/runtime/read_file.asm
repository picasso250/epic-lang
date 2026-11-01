; ── _read_file: read a whole file into a fresh mutable u8[] ──
; rcx = &path str
; returns: rax = &u8[] { data, len, cap }; empty on failure
_read_file:
    push rbp
    mov rbp, rsp
    sub rsp, 64
    mov [rbp-8], rcx       ; &path
    ; Reject interior NUL bytes before crossing the C-string boundary.
    mov rdx, [rcx]         ; path.data
    mov r8, [rcx+8]        ; path.len
    xor r9, r9
_read_file_path_scan:
    cmp r9, r8
    jge _read_file_path_ok
    cmp byte [rdx+r9], 0
    je _read_file_empty
    inc r9
    jmp _read_file_path_scan
_read_file_path_ok:
    ; CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL)
    mov rcx, [rbp-8]
    mov rcx, [rcx]
    mov edx, 0x80000000
    mov r8d, 1
    xor r9d, r9d
    sub rsp, 56
    mov dword [rsp+32], 3
    mov dword [rsp+40], 0x80
    mov qword [rsp+48], 0
    call CreateFileA
    add rsp, 56
    cmp rax, -1
    je _read_file_empty
    mov [rbp-16], rax      ; handle
    ; size = GetFileSize(handle, NULL)
    mov rcx, rax
    xor edx, edx
    sub rsp, 40
    call GetFileSize
    add rsp, 40
    mov [rbp-24], rax      ; size
    ; buf = __ep_alloc(size + 1)
    mov rcx, rax
    inc rcx
    sub rsp, 40
    call __ep_alloc
    add rsp, 40
    mov [rbp-32], rax      ; buf
    ; ReadFile(handle, buf, size, &read, NULL)
    mov rcx, [rbp-16]
    mov rdx, [rbp-32]
    mov r8, [rbp-24]
    lea r9, [rbp-40]
    sub rsp, 40
    mov qword [rsp+32], 0
    call ReadFile
    add rsp, 40
    mov [rbp-48], rax      ; ReadFile result
    ; CloseHandle(handle)
    mov rcx, [rbp-16]
    sub rsp, 40
    call CloseHandle
    add rsp, 40
    cmp qword [rbp-48], 0
    je _read_file_empty
    ; Copy exactly the bytes read into an independent mutable array.
    mov rcx, [rbp-32]
    mov edx, [rbp-40]
    call _embed_bytes
    jmp _read_file_done
_read_file_empty:
    lea rcx, [_read_file_empty_data]
    xor edx, edx
    call _embed_bytes
_read_file_done:
    mov rsp, rbp
    pop rbp
    ret
_read_file_empty_data:
    db 0
