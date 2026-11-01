; ── _bytes: copy str bytes into a new u8[] ──
; rcx = &str
; returns: rax = &_arr_u8 { data: &u8, len: i64, cap: i64 }
_bytes:
    push rbp
    mov rbp, rsp
    sub rsp, 40
    mov [rbp-8], rcx       ; save &str

    mov ecx, 24
    sub rsp, 40
    call __ep_alloc
    add rsp, 40
    mov [rbp-16], rax      ; header

    mov rcx, [rbp-8]
    mov rdx, [rcx+16]      ; len
    mov [rbp-24], rdx
    mov r8, rdx
    test r8, r8
    jnz _bytes_have_cap
    mov r8, 1
_bytes_have_cap:
    mov [rbp-32], r8       ; alloc cap

    mov rcx, r8
    sub rsp, 40
    call __ep_alloc
    add rsp, 40
    mov [rbp-40], rax      ; data

    mov rcx, [rbp-16]
    mov rdx, [rbp-40]
    mov [rcx], rdx
    mov rdx, [rbp-24]
    mov [rcx+8], rdx
    mov [rcx+16], rdx

    test rdx, rdx
    jz _bytes_done
    mov rcx, [rbp-8]
    mov r8, [rcx]          ; owner
    add r8, [rcx+8]        ; + offset
    mov r9, [rbp-40]       ; dst data
_bytes_copy:
    mov al, [r8]
    mov [r9], al
    inc r8
    inc r9
    dec rdx
    jnz _bytes_copy
_bytes_done:
    mov rax, [rbp-16]
    mov rsp, rbp
    pop rbp
    ret
