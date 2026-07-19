; ── _str_alloc: internal deep-copy bridge into an immutable str view ──
; rcx = src pointer, rdx = len
; returns: rax = &str { owner: &u8, offset: i64, len: i64 }
; clobbers: rax, rcx, rdx, r8, r9, r10, r11
_str_alloc:
    push rbp
    mov rbp, rsp
    sub rsp, 40           ; 3 save slots (24) + alignment
    mov [rbp-8], rcx      ; save src
    mov [rbp-16], rdx     ; save len
    ; Allocate header (24 bytes)
    mov ecx, 24
    sub rsp, 40
    call __ep_alloc
    add rsp, 40
    mov [rbp-24], rax     ; save header ptr
    ; Allocate exactly the string bytes (one byte for an empty GC object).
    mov rcx, [rbp-16]     ; len
    test rcx, rcx
    jnz _str_alloc_size_ready
    mov rcx, 1
_str_alloc_size_ready:
    sub rsp, 40
    call __ep_alloc
    add rsp, 40
                          ; rax = data ptr
    ; Store owner, zero offset, and len in header.
    mov rcx, [rbp-24]     ; rcx = header
    mov [rcx], rax        ; header.owner
    mov qword [rcx+8], 0  ; header.offset
    mov rdx, [rbp-16]     ; rdx = len
    mov [rcx+16], rdx     ; header.len
    ; Copy bytes
    test rdx, rdx
    mov r9, rax
    jz _str_alloc_done
    mov r8, [rbp-8]       ; r8 = src
_str_alloc_copy:
    mov r10b, [r8]
    mov [r9], r10b
    inc r8
    inc r9
    dec rdx
    jnz _str_alloc_copy
_str_alloc_done:
    mov rax, [rbp-24]     ; return header ptr
    mov rsp, rbp
    pop rbp
    ret
