; ── _read_file: read whole file into heap-allocated str ──
; rcx = path (C string)
; returns: rax = &str
_read_file:
    push rbp
    mov rbp, rsp
    sub rsp, 64
    mov [rbp-8], rcx       ; path
    ; CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL)
    mov rcx, [rbp-8]
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
    ; buf = HeapAlloc(heap, zero, size + 1)
    mov rcx, [_heap]
    mov edx, 8
    mov r8, rax
    inc r8
    sub rsp, 40
    call HeapAlloc
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
    ; CloseHandle(handle)
    mov rcx, [rbp-16]
    sub rsp, 40
    call CloseHandle
    add rsp, 40
    ; Deep-copy exactly the bytes read into str.
    mov rcx, [rbp-32]
    mov edx, [rbp-40]
    call _str_alloc
    jmp _read_file_done
_read_file_empty:
    lea rcx, [_read_file_empty_data]
    xor edx, edx
    call _str_alloc
_read_file_done:
    mov rsp, rbp
    pop rbp
    ret
_read_file_empty_data:
    db 0
