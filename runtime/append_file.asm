; ── _append_file: append whole str to a file ──
; rcx = path (C string), rdx = data pointer, r8 = len
; returns: rax = bytes written, or -1 on failure
_append_file:
    push rbp
    mov rbp, rsp
    sub rsp, 64
    mov [rbp-8], rcx       ; path
    mov [rbp-16], rdx      ; data
    mov [rbp-24], r8       ; len
    ; CreateFileA(path, GENERIC_WRITE, 0, NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL)
    mov rcx, [rbp-8]
    mov edx, 0x40000000
    xor r8d, r8d
    xor r9d, r9d
    sub rsp, 56
    mov dword [rsp+32], 4
    mov dword [rsp+40], 0x80
    mov qword [rsp+48], 0
    call CreateFileA
    add rsp, 56
    cmp rax, -1
    je _append_file_fail
    mov [rbp-32], rax      ; handle
    ; SetFilePointer(handle, 0, NULL, FILE_END)
    mov rcx, [rbp-32]
    xor edx, edx
    xor r8d, r8d
    mov r9d, 2
    sub rsp, 40
    call SetFilePointer
    add rsp, 40
    cmp eax, -1
    je _append_file_close_fail
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
    jz _append_file_close_fail
    ; CloseHandle(handle)
    mov rcx, [rbp-32]
    sub rsp, 40
    call CloseHandle
    add rsp, 40
    mov eax, [rbp-40]
    jmp _append_file_done
_append_file_close_fail:
    mov rcx, [rbp-32]
    sub rsp, 40
    call CloseHandle
    add rsp, 40
_append_file_fail:
    mov rax, -1
_append_file_done:
    mov rsp, rbp
    pop rbp
    ret
