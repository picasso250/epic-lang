; _cstr: copy a v2 string into a fresh NUL-terminated allocation.
; rcx = &str { data, len }, returns rax = allocation base
_cstr:
    push rbp
    mov rbp, rsp
    sub rsp, 48
    mov [rbp-8], rcx
    mov rdx, [rcx+8]
    mov [rbp-16], rdx
    lea rcx, [rdx+1]
    sub rsp, 40
    call __ep_alloc
    add rsp, 40
    mov [rbp-24], rax
    mov rcx, [rbp-8]
    mov r8, [rcx]
    mov r9, rax
    mov rdx, [rbp-16]
_cstr_copy:
    test rdx, rdx
    jz _cstr_terminate
    mov cl, [r8]
    mov [r9], cl
    inc r8
    inc r9
    dec rdx
    jmp _cstr_copy
_cstr_terminate:
    mov byte [r9], 0
    mov rax, [rbp-24]
    mov rsp, rbp
    pop rbp
    ret
