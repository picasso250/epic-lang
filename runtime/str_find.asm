; -- _str_find: byte-oriented substring search --
; rcx = &str, rdx = &needle
; returns: rax = first byte index, or -1 when absent
_str_find:
    push rbp
    mov rbp, rsp
    sub rsp, 32
    mov [rbp-8], rcx        ; s
    mov [rbp-16], rdx       ; needle

    mov rax, [rdx+8]
    test rax, rax
    jnz _str_find_nonempty
    xor eax, eax
    jmp _str_find_done
_str_find_nonempty:
    mov r8, [rcx+8]         ; s len
    cmp rax, r8
    jg _str_find_absent
    sub r8, rax             ; last start index
    xor r9, r9              ; i
_str_find_outer:
    cmp r9, r8
    jg _str_find_absent
    xor r10, r10            ; j
_str_find_inner:
    mov rdx, [rbp-16]
    cmp r10, [rdx+8]
    jge _str_find_found
    mov rcx, [rbp-8]
    mov rax, [rcx]
    add rax, r9
    mov r11b, [rax+r10]
    mov rax, [rdx]
    cmp r11b, [rax+r10]
    jne _str_find_next
    inc r10
    jmp _str_find_inner
_str_find_next:
    inc r9
    jmp _str_find_outer
_str_find_found:
    mov rax, r9
    jmp _str_find_done
_str_find_absent:
    mov rax, -1
_str_find_done:
    mov rsp, rbp
    pop rbp
    ret
