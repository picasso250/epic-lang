; ── _write_file: write a whole u8[] payload to a file ──
; rcx = &path str, rdx = data pointer, r8 = len
; returns: rax = len on success, or -1 on failure
_write_file:
    push rbp
    mov rbp, rsp
    sub rsp, 64
    mov [rbp-8], rcx       ; &path
    mov [rbp-16], rdx      ; data
    mov [rbp-24], r8       ; len
    ; Reject interior NUL bytes before crossing the C-string boundary.
    mov rdx, [rcx]         ; path.data
    mov r8, [rcx+8]        ; path.len
    xor r9, r9
_write_file_path_scan:
    cmp r9, r8
    jge _write_file_path_ok
    cmp byte [rdx+r9], 0
    je _write_file_fail
    inc r9
    jmp _write_file_path_scan
_write_file_path_ok:
    ; CreateFileA(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL)
    mov rcx, [rbp-8]
    mov rcx, [rcx]
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
    mov qword [rbp-48], 0  ; total written
_write_file_loop:
    mov rax, [rbp-48]
    cmp rax, [rbp-24]
    jge _write_file_close_success
    ; WriteFile(handle, data + total, min(remaining, 0x7fffffff), &written, NULL)
    mov rcx, [rbp-32]
    mov rdx, [rbp-16]
    add rdx, rax
    mov r8, [rbp-24]
    sub r8, rax
    cmp r8, 0x7fffffff
    jbe _write_file_chunk_ready
    mov r8d, 0x7fffffff
_write_file_chunk_ready:
    lea r9, [rbp-40]
    sub rsp, 40
    mov qword [rsp+32], 0
    call WriteFile
    add rsp, 40
    test eax, eax
    jz _write_file_close_fail
    mov eax, [rbp-40]
    test eax, eax
    jz _write_file_close_fail
    add [rbp-48], rax
    jmp _write_file_loop
_write_file_close_success:
    mov rcx, [rbp-32]
    sub rsp, 40
    call CloseHandle
    add rsp, 40
    mov rax, [rbp-24]
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
