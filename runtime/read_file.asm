; -- _read_file: read whole file into heap-allocated i8[] --
; rcx = path (C string)
; returns: rax = &_arr_i8 { data: &i8, len: i64, cap: i64 }
_read_file:
    push rbp
    mov rbp, rsp
    sub rsp, 80
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

    ; header = HeapAlloc(heap, zero, 24)
    mov rcx, [_heap]
    mov edx, 8
    mov r8d, 24
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov [rbp-56], rax      ; header

    ; size = GetFileSize(handle, NULL)
    mov rcx, [rbp-16]
    xor edx, edx
    sub rsp, 40
    call GetFileSize
    add rsp, 40
    mov [rbp-24], rax      ; size
    mov r8, rax
    test r8, r8
    jnz _read_file_cap_ok
    mov r8, 1
_read_file_cap_ok:
    mov [rbp-64], r8       ; cap

    ; buf = HeapAlloc(heap, zero, cap)
    mov rcx, [_heap]
    mov edx, 8
    mov r8, [rbp-64]
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
    ; Fill array header with the bytes read.
    mov rcx, [rbp-56]
    mov rax, [rbp-32]
    mov [rcx], rax
    mov eax, [rbp-40]
    mov [rcx+8], rax
    mov rax, [rbp-64]
    mov [rcx+16], rax
    mov rax, rcx
    jmp _read_file_done
_read_file_empty:
    mov rcx, [_heap]
    mov edx, 8
    mov r8d, 24
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov [rbp-56], rax
    mov rcx, [_heap]
    mov edx, 8
    mov r8d, 1
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov rcx, [rbp-56]
    mov [rcx], rax
    mov qword [rcx+8], 0
    mov qword [rcx+16], 1
    mov rax, rcx
_read_file_done:
    mov rsp, rbp
    pop rbp
    ret
