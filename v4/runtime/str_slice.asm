; ── _str_slice: allocate only a new header for s[start:end] ──
; rcx = &str, rdx = start, r8 = end
; returns: rax = &str { owner: &u8, offset: i64, len: i64 }
_str_slice:
    push rbp
    mov rbp, rsp
    sub rsp, 48
    mov [rbp-8], rcx
    sub r8, rdx
    mov [rbp-16], rdx
    mov [rbp-24], r8
    mov ecx, 24
    sub rsp, 40
    call __ep_alloc
    add rsp, 40
    mov rcx, [rbp-8]
    mov rdx, [rcx]
    mov [rax], rdx
    mov rdx, [rcx+8]
    add rdx, [rbp-16]
    mov [rax+8], rdx
    mov rdx, [rbp-24]
    mov [rax+16], rdx
    mov rsp, rbp
    pop rbp
    ret

