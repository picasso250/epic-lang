; -- _str_trim: trim leading and trailing ASCII whitespace --
; rcx = &str
; returns: rax = copied trimmed str
_str_trim:
    push rbp
    mov rbp, rsp
    sub rsp, 64
    mov [rbp-8], rcx        ; s
    xor rdx, rdx            ; start
    mov r8, [rcx+8]         ; end
    mov [rbp-16], r8

_str_trim_left:
    cmp rdx, [rbp-16]
    jge _str_trim_slice
    mov rax, [rbp-8]
    mov rax, [rax]
    mov al, [rax+rdx]
    cmp al, 32
    je _str_trim_left_inc
    cmp al, 9
    jl _str_trim_right
    cmp al, 13
    jg _str_trim_right
_str_trim_left_inc:
    inc rdx
    jmp _str_trim_left

_str_trim_right:
    mov r8, [rbp-16]
    cmp r8, rdx
    jle _str_trim_slice
    mov rax, [rbp-8]
    mov rax, [rax]
    mov r9, r8
    dec r9
    mov al, [rax+r9]
    cmp al, 32
    je _str_trim_right_dec
    cmp al, 9
    jl _str_trim_slice
    cmp al, 13
    jg _str_trim_slice
_str_trim_right_dec:
    dec qword [rbp-16]
    jmp _str_trim_right

_str_trim_slice:
    mov rcx, [rbp-8]
    mov r8, [rbp-16]
    sub rsp, 32
    call _str_slice
    add rsp, 32
    mov rsp, rbp
    pop rbp
    ret

