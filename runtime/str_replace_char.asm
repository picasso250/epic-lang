; ── _str_replace_char: copy str while replacing one byte ──
; rcx = &str, rdx = from byte, r8 = to byte
; returns: rax = &str { data: &u8, len: i64 }
_str_replace_char:
    push rbp
    mov rbp, rsp
    sub rsp, 64
    mov [rbp-8], rcx
    mov [rbp-16], rdx
    mov [rbp-24], r8
    mov r9, [rcx+8]
    mov [rbp-32], r9

    mov rcx, [_heap]
    mov edx, 8
    mov r8d, 16
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov [rbp-40], rax

    mov rcx, [_heap]
    mov edx, 8
    mov r8, [rbp-32]
    inc r8
    sub rsp, 40
    call HeapAlloc
    add rsp, 40

    mov rcx, [rbp-40]
    mov [rcx], rax
    mov rdx, [rbp-32]
    mov [rcx+8], rdx

    mov rcx, [rbp-8]
    mov rsi, [rcx]
    mov rdi, rax
    mov r10b, byte [rbp-16]
    mov r11b, byte [rbp-24]
_str_replace_char_copy:
    test rdx, rdx
    jz _str_replace_char_done
    mov al, [rsi]
    cmp al, r10b
    jne _str_replace_char_store
    mov al, r11b
_str_replace_char_store:
    mov [rdi], al
    inc rsi
    inc rdi
    dec rdx
    jmp _str_replace_char_copy
_str_replace_char_done:
    mov byte [rdi], 0
    mov rax, [rbp-40]
    mov rsp, rbp
    pop rbp
    ret

