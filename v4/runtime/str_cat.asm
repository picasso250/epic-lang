; ── _str_cat: concatenate two str values ──
; rcx = left &str, rdx = right &str
; returns: rax = &str { owner: &u8, offset: i64, len: i64 }
_str_cat:
    push rbp
    mov rbp, rsp
    sub rsp, 64
    mov [rbp-8], rcx
    mov [rbp-16], rdx
    mov r8, [rcx+16]
    add r8, [rdx+16]
    mov [rbp-24], r8

    mov ecx, 24
    sub rsp, 40
    call __ep_alloc
    add rsp, 40
    mov [rbp-32], rax

    mov rcx, [rbp-24]
    test rcx, rcx
    jnz _str_cat_size_ready
    mov rcx, 1
_str_cat_size_ready:
    sub rsp, 40
    call __ep_alloc
    add rsp, 40
    mov [rbp-40], rax

    mov rcx, [rbp-32]
    mov [rcx], rax
    mov qword [rcx+8], 0
    mov rdx, [rbp-24]
    mov [rcx+16], rdx

    mov rcx, [rbp-8]
    mov rsi, [rcx]
    add rsi, [rcx+8]
    mov rdx, [rcx+16]
    mov rdi, [rbp-40]
_str_cat_left:
    test rdx, rdx
    jz _str_cat_right_start
    mov al, [rsi]
    mov [rdi], al
    inc rsi
    inc rdi
    dec rdx
    jmp _str_cat_left

_str_cat_right_start:
    mov rcx, [rbp-16]
    mov rsi, [rcx]
    add rsi, [rcx+8]
    mov rdx, [rcx+16]
_str_cat_right:
    test rdx, rdx
    jz _str_cat_done
    mov al, [rsi]
    mov [rdi], al
    inc rsi
    inc rdi
    dec rdx
    jmp _str_cat_right

_str_cat_done:
    mov rax, [rbp-32]
    mov rsp, rbp
    pop rbp
    ret
