; ── _write_file: write whole str to a file ──
; rcx = path (C string), rdx = data pointer, r8 = len
; returns: rax = bytes written, or -1 on failure
_write_file:
    push rbp
    mov rbp, rsp
    sub rsp, 64
    mov [rbp-8], rcx       ; path
    mov [rbp-16], rdx      ; data
    mov [rbp-24], r8       ; len
    ; CreateFileA(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL)
    mov rcx, [rbp-8]
    mov edx, 0x40000000
    xor r8d, r8d
    xor r9d, r9d
    sub rsp, 56
    mov dword [rsp+32], 2
    mov dword [rsp+40], 0x80
    mov qword [rsp+48], 0
    call CreateFileA
    add rsp, 56
    cmp rax, -1
    je _write_file_fail
    mov [rbp-32], rax      ; handle
    ; WriteFile(handle, data, len, &written, NULL)
    mov rcx, [rbp-32]
    mov rdx, [rbp-16]
    mov r8, [rbp-24]
    lea r9, [rbp-40]
    sub rsp, 40
    mov qword [rsp+32], 0
    call WriteFile
    add rsp, 40
    test eax, eax
    jz _write_file_close_fail
    ; CloseHandle(handle)
    mov rcx, [rbp-32]
    sub rsp, 40
    call CloseHandle
    add rsp, 40
    mov eax, [rbp-40]
    jmp _write_file_done
_write_file_close_fail:
    mov rcx, [rbp-32]
    sub rsp, 40
    call CloseHandle
    add rsp, 40
_write_file_fail:
    mov rax, -1
_write_file_done:
    mov rsp, rbp
    pop rbp
    ret
