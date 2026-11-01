; ── _str_cat: concatenate two str values ──
; rcx = left &str, rdx = right &str
; returns: rax = &str { data: &u8, len: i64 }
_str_cat:
    push rbp
    mov rbp, rsp
    sub rsp, 64
    mov [rbp-8], rcx
    mov [rbp-16], rdx
    mov r8, [rcx+8]
    add r8, [rdx+8]
    mov [rbp-24], r8

    mov rcx, [_heap]
    mov edx, 8
    mov r8d, 16
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov [rbp-32], rax

    mov rcx, [_heap]
    mov edx, 8
    mov r8, [rbp-24]
    inc r8
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov [rbp-40], rax

    mov rcx, [rbp-32]
    mov [rcx], rax
    mov rdx, [rbp-24]
    mov [rcx+8], rdx

    mov rcx, [rbp-8]
    mov rsi, [rcx]
    mov rdx, [rcx+8]
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
    mov rdx, [rcx+8]
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
    mov byte [rdi], 0
    mov rax, [rbp-32]
    mov rsp, rbp
    pop rbp
    ret
