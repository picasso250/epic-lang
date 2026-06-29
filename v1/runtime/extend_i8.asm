; ── _extend_i8: append src i8[] bytes into dst i8[] ──
; rcx = &dst array, rdx = &src array
; returns: rax = 0
_extend_i8:
    push rbp
    mov rbp, rsp
    sub rsp, 72
    mov [rbp-8], rcx       ; dst header
    mov [rbp-16], rdx      ; src header

    mov rax, [rdx]         ; snapshot src.data
    mov [rbp-24], rax
    mov rax, [rdx+8]       ; snapshot src.len
    mov [rbp-32], rax

    mov rax, [rcx+8]       ; dst len
    mov [rbp-40], rax
    add rax, [rbp-32]      ; needed len
    mov [rbp-48], rax

    cmp [rcx+16], rax      ; dst cap >= needed?
    jge _extend_i8_have_cap

    mov r8, [rcx+16]
    test r8, r8
    jnz _extend_i8_cap_loop
    mov r8, 2
_extend_i8_cap_loop:
    cmp r8, [rbp-48]
    jge _extend_i8_cap_ready
    add r8, r8
    jmp _extend_i8_cap_loop
_extend_i8_cap_ready:
    mov [rbp-56], r8
    mov rcx, [_heap]
    mov edx, 8
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov [rbp-64], rax

    mov rcx, [rbp-8]
    mov r8, [rcx]          ; old dst data
    mov r9, [rbp-64]       ; new dst data
    mov r10, [rbp-40]      ; old dst len
    test r10, r10
    jz _extend_i8_swap
_extend_i8_copy_old:
    mov al, [r8]
    mov [r9], al
    inc r8
    inc r9
    dec r10
    jnz _extend_i8_copy_old
_extend_i8_swap:
    mov rcx, [rbp-8]
    mov rax, [rbp-64]
    mov [rcx], rax
    mov rax, [rbp-56]
    mov [rcx+16], rax
_extend_i8_have_cap:
    mov rcx, [rbp-8]
    mov r8, [rcx]
    add r8, [rbp-40]       ; dst write cursor
    mov r9, [rbp-24]       ; src data
    mov r10, [rbp-32]      ; src len snapshot
    test r10, r10
    jz _extend_i8_finish
_extend_i8_copy_src:
    mov al, [r9]
    mov [r8], al
    inc r8
    inc r9
    dec r10
    jnz _extend_i8_copy_src
_extend_i8_finish:
    mov rcx, [rbp-8]
    mov rax, [rbp-48]
    mov [rcx+8], rax
    xor eax, eax
    mov rsp, rbp
    pop rbp
    ret
