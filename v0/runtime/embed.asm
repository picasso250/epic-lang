; _embed_bytes: copy bytes embedded in the executable into a mutable u8[].
; rcx = source bytes, rdx = byte count
; returns: rax = &u8[] { data, len, cap }
_embed_bytes:
    push rbp
    mov rbp, rsp
    sub rsp, 64
    mov [rbp-8], rcx
    mov [rbp-16], rdx

    mov rcx, [_heap]
    mov edx, 8
    mov r8d, 24
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov [rbp-24], rax

    mov r8, [rbp-16]
    test r8, r8
    jnz _embed_bytes_have_size
    mov r8, 1
_embed_bytes_have_size:
    mov rcx, [_heap]
    mov edx, 8
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov [rbp-32], rax

    mov rcx, [rbp-24]
    mov [rcx], rax
    mov rdx, [rbp-16]
    mov [rcx+8], rdx
    mov [rcx+16], rdx

    mov r8, [rbp-8]
    mov r9, [rbp-32]
    test rdx, rdx
    jz _embed_bytes_done
_embed_bytes_copy:
    mov al, [r8]
    mov [r9], al
    inc r8
    inc r9
    dec rdx
    jnz _embed_bytes_copy
_embed_bytes_done:
    mov rax, [rbp-24]
    mov rsp, rbp
    pop rbp
    ret
