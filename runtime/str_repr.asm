; ── _str_repr: quote and escape a str for structured repr ──
; rcx = &str
; returns: rax = &str with surrounding quotes
_str_repr:
    push rbp
    mov rbp, rsp
    sub rsp, 80
    mov [rbp-8], rcx          ; input str

    ; First pass: compute output length.
    mov rsi, [rcx]
    mov rdx, [rcx+8]
    mov r8, 2                 ; surrounding quotes
_str_repr_len_loop:
    test rdx, rdx
    jz _str_repr_len_done
    mov al, [rsi]
    cmp al, 34                ; "
    je _str_repr_len_escape
    cmp al, 92                ; backslash
    je _str_repr_len_escape
    cmp al, 10                ; newline
    je _str_repr_len_escape
    cmp al, 13                ; carriage return
    je _str_repr_len_escape
    cmp al, 9                 ; tab
    je _str_repr_len_escape
    inc r8
    jmp _str_repr_len_next
_str_repr_len_escape:
    add r8, 2
_str_repr_len_next:
    inc rsi
    dec rdx
    jmp _str_repr_len_loop
_str_repr_len_done:
    mov [rbp-16], r8          ; output len

    ; Allocate header.
    mov rcx, [_heap]
    mov edx, 8
    mov r8d, 16
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov [rbp-24], rax         ; header

    ; Allocate data.
    mov rcx, [_heap]
    mov edx, 8
    mov r8, [rbp-16]
    inc r8
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov [rbp-32], rax         ; data

    mov rcx, [rbp-24]
    mov [rcx], rax
    mov rdx, [rbp-16]
    mov [rcx+8], rdx

    ; Second pass: copy with escapes.
    mov rdi, [rbp-32]
    mov byte [rdi], 34
    inc rdi
    mov rcx, [rbp-8]
    mov rsi, [rcx]
    mov rdx, [rcx+8]
_str_repr_copy_loop:
    test rdx, rdx
    jz _str_repr_copy_done
    mov al, [rsi]
    cmp al, 34
    je _str_repr_copy_quote
    cmp al, 92
    je _str_repr_copy_backslash
    cmp al, 10
    je _str_repr_copy_newline
    cmp al, 13
    je _str_repr_copy_cr
    cmp al, 9
    je _str_repr_copy_tab
    mov [rdi], al
    inc rdi
    jmp _str_repr_copy_next
_str_repr_copy_quote:
    mov byte [rdi], 92
    inc rdi
    mov byte [rdi], 34
    inc rdi
    jmp _str_repr_copy_next
_str_repr_copy_backslash:
    mov byte [rdi], 92
    inc rdi
    mov byte [rdi], 92
    inc rdi
    jmp _str_repr_copy_next
_str_repr_copy_newline:
    mov byte [rdi], 92
    inc rdi
    mov byte [rdi], 110
    inc rdi
    jmp _str_repr_copy_next
_str_repr_copy_cr:
    mov byte [rdi], 92
    inc rdi
    mov byte [rdi], 114
    inc rdi
    jmp _str_repr_copy_next
_str_repr_copy_tab:
    mov byte [rdi], 92
    inc rdi
    mov byte [rdi], 116
    inc rdi
_str_repr_copy_next:
    inc rsi
    dec rdx
    jmp _str_repr_copy_loop
_str_repr_copy_done:
    mov byte [rdi], 34
    inc rdi
    mov byte [rdi], 0
    mov rax, [rbp-24]
    mov rsp, rbp
    pop rbp
    ret
