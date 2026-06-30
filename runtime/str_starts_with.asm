; -- _str_starts_with: byte-oriented string prefix test --
; rcx = &str, rdx = &prefix
; returns: rax = 1 when rcx starts with rdx, else 0
_str_starts_with:
    push rbp
    mov rbp, rsp
    mov r8, [rcx]       ; s data
    mov r9, [rcx+8]     ; s len
    mov r10, [rdx]      ; prefix data
    mov r11, [rdx+8]    ; prefix len
    cmp r11, r9
    jg _str_starts_with_no
    xor rax, rax
_str_starts_with_loop:
    cmp rax, r11
    jge _str_starts_with_yes
    mov cl, [r8+rax]
    cmp cl, [r10+rax]
    jne _str_starts_with_no
    inc rax
    jmp _str_starts_with_loop
_str_starts_with_yes:
    mov eax, 1
    mov rsp, rbp
    pop rbp
    ret
_str_starts_with_no:
    xor eax, eax
    mov rsp, rbp
    pop rbp
    ret

