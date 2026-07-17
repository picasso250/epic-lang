; ── _itoa: convert integer to heap-allocated str ──
; rcx = number
; returns: rax = &str (heap-allocated { data: &u8, len: i64 })
_itoa:
    push rbp
    mov rbp, rsp
    sub rsp, 88           ; 48 (saves) + 32 (temp) + 8 (align)
    mov r8, 0             ; sign flag
    mov rax, rcx
    test rax, rax
    jns .positive
    neg rax
    mov r8, 1             ; has sign
.positive:
    test rax, rax
    jnz .convert
    lea r10, [zero_str_data]
    mov r11, 1
    mov r8, 0
    jmp .save_state
.convert:
    lea r10, [rbp-80]
    add r10, 31
    sub r10, r8           ; leave room for sign
    mov r11, 0
.digit_loop:
    xor rdx, rdx
    mov rcx, 10
    div rcx
    add dl, 48
    dec r10
    mov [r10], dl
    inc r11
    test rax, rax
    jnz .digit_loop
.save_state:
    mov [rbp-16], r10     ; save first digit ptr (volatile)
    mov [rbp-24], r11     ; save digit count (volatile)
    mov [rbp-32], r8      ; save sign flag
    ; Allocate header (16 bytes)
    mov ecx, 16
    sub rsp, 40
    call __ep_alloc
    add rsp, 40
    mov [rbp-8], rax      ; save header
    ; Compute total len
    mov r8, [rbp-24]       ; digit count
    add r8, [rbp-32]       ; + sign flag
    ; Allocate data (total len + 1)
    push r8               ; save total len
    mov rcx, r8
    inc rcx               ; +1 for null
    sub rsp, 40
    call __ep_alloc
    add rsp, 40
    pop rdx               ; rdx = total len
    mov rcx, [rbp-8]
    mov [rcx], rax        ; header.data = data
    mov [rcx+8], rdx      ; header.len = total len
    ; Restore volatile state
    mov r10, [rbp-16]     ; first digit ptr
    mov r11, [rbp-24]     ; digit count
    mov r8, [rbp-32]      ; sign flag
    ; Write sign if negative
    mov r9, rax           ; dst cursor
    test r8, r8
    jz .copy_digits
    mov byte [r9], 45
    inc r9
.copy_digits:
    mov rcx, r11
    test rcx, rcx
    jz .nullterm
.copy:
    mov al, [r10]
    mov [r9], al
    inc r10
    inc r9
    dec rcx
    jnz .copy
.nullterm:
    mov byte [r9], 0
    mov rax, [rbp-8]
    mov rsp, rbp
    pop rbp
    ret
zero_str_data:
    db 48, 0
