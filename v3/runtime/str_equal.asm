; _str_equal: length-aware byte equality for immutable string views.
; rcx = left &str, rdx = right &str
; returns eax = 1 when equal, otherwise 0
_str_equal:
    push rsi
    push rdi
    mov rax, [rcx+16]
    cmp rax, [rdx+16]
    jne _str_equal_no
    mov rsi, [rcx]
    add rsi, [rcx+8]
    mov rdi, [rdx]
    add rdi, [rdx+8]
    mov rcx, rax
_str_equal_loop:
    test rcx, rcx
    jz _str_equal_yes
    movzx eax, byte [rsi]
    movzx edx, byte [rdi]
    cmp eax, edx
    jne _str_equal_no
    inc rsi
    inc rdi
    dec rcx
    jmp _str_equal_loop
_str_equal_yes:
    mov eax, 1
    pop rdi
    pop rsi
    ret
_str_equal_no:
    xor eax, eax
    pop rdi
    pop rsi
    ret
