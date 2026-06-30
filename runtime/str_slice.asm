; ── _str_slice: copy s[start:end] into a new str ──
; rcx = &str, rdx = start, r8 = end
; returns: rax = &str { data: &i8, len: i64 }
_str_slice:
    push rbp
    mov rbp, rsp
    sub rsp, 64
    mov [rbp-8], rcx
    mov [rbp-16], rdx
    mov [rbp-24], r8

    test rdx, rdx
    jl _str_slice_fail
    cmp r8, rdx
    jl _str_slice_fail
    cmp r8, [rcx+8]
    jg _str_slice_fail

    sub r8, rdx
    mov [rbp-32], r8
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
    add rsi, [rbp-16]
    mov rdi, rax
_str_slice_copy:
    test rdx, rdx
    jz _str_slice_done
    mov al, [rsi]
    mov [rdi], al
    inc rsi
    inc rdi
    dec rdx
    jmp _str_slice_copy
_str_slice_done:
    mov byte [rdi], 0
    mov rax, [rbp-40]
    mov rsp, rbp
    pop rbp
    ret
_str_slice_fail:
    mov ecx, 1
    call ExitProcess

