; ── _extend: append src T[] elements into dst T[] ──
; rcx = &dst array, rdx = &src array, r8 = sizeof(T)
; len and cap remain element counts; allocation and copying use byte counts.
; returns: rax = 0
_extend:
    push rbp
    mov rbp, rsp
    sub rsp, 88
    mov [rbp-8], rcx       ; dst header
    mov [rbp-16], rdx      ; src header
    mov [rbp-72], r8       ; element size

    mov rax, [rdx]         ; snapshot src.data for self-extend
    mov [rbp-24], rax
    mov rax, [rdx+8]       ; snapshot src.len in elements
    mov [rbp-32], rax

    mov rax, [rcx+8]       ; dst len in elements
    mov [rbp-40], rax
    add rax, [rbp-32]      ; needed len in elements
    mov [rbp-48], rax

    cmp [rcx+16], rax      ; dst cap >= needed?
    jge _extend_have_cap

    mov r8, [rcx+16]
    test r8, r8
    jnz _extend_cap_loop
    mov r8, 2
_extend_cap_loop:
    cmp r8, [rbp-48]
    jge _extend_cap_ready
    add r8, r8
    jmp _extend_cap_loop
_extend_cap_ready:
    mov [rbp-56], r8
    imul r8, [rbp-72]      ; allocation size in bytes
    mov rcx, r8
    sub rsp, 40
    call __ep_alloc
    add rsp, 40
    mov [rbp-64], rax

    mov rcx, [rbp-8]
    mov r8, [rcx]          ; old dst data
    mov r9, [rbp-64]       ; new dst data
    mov r10, [rbp-40]
    imul r10, [rbp-72]     ; old dst byte count
    test r10, r10
    jz _extend_swap
_extend_copy_old:
    mov al, [r8]
    mov [r9], al
    inc r8
    inc r9
    dec r10
    jnz _extend_copy_old
_extend_swap:
    mov rcx, [rbp-8]
    mov rax, [rbp-64]
    mov [rcx], rax
    mov rax, [rbp-56]
    mov [rcx+16], rax
_extend_have_cap:
    mov rcx, [rbp-8]
    mov r8, [rcx]
    mov rax, [rbp-40]
    imul rax, [rbp-72]
    add r8, rax            ; dst write cursor in bytes
    mov r9, [rbp-24]       ; snapshotted src data
    mov r10, [rbp-32]
    imul r10, [rbp-72]     ; source byte count
    test r10, r10
    jz _extend_finish
_extend_copy_src:
    mov al, [r9]
    mov [r8], al
    inc r8
    inc r9
    dec r10
    jnz _extend_copy_src
_extend_finish:
    mov rcx, [rbp-8]
    mov rax, [rbp-48]
    mov [rcx+8], rax
    xor eax, eax
    mov rsp, rbp
    pop rbp
    ret
