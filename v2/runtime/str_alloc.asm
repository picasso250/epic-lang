; ── _str_alloc: deep-copy bytes into heap-allocated str ──
; rcx = src pointer, rdx = len
; returns: rax = &str { data: &i8, len: i64 }
; clobbers: rax, rcx, rdx, r8, r9, r10, r11
_str_alloc:
    push rbp
    mov rbp, rsp
    sub rsp, 40           ; 3 save slots (24) + alignment
    mov [rbp-8], rcx      ; save src
    mov [rbp-16], rdx     ; save len
    ; Allocate header (16 bytes)
    mov rcx, [_heap]
    mov edx, 8
    mov r8d, 16
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov [rbp-24], rax     ; save header ptr
    ; Allocate data (len + 1 for null terminator)
    mov rcx, [_heap]
    mov edx, 8
    mov r8, [rbp-16]      ; len
    inc r8                ; +1 for null
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
                          ; rax = data ptr
    ; Store data ptr and len in header
    mov rcx, [rbp-24]     ; rcx = header
    mov [rcx], rax        ; header.data = data (offset 0)
    mov rdx, [rbp-16]     ; rdx = len
    mov [rcx+8], rdx      ; header.len = len (offset 8)
    ; Copy bytes
    test rdx, rdx
    mov r9, rax           ; r9 = dst cursor (set before branch for len=0 case)
    jz _str_alloc_null
    mov r8, [rbp-8]       ; r8 = src
_str_alloc_copy:
    mov r10b, [r8]
    mov [r9], r10b
    inc r8
    inc r9
    dec rdx
    jnz _str_alloc_copy
_str_alloc_null:
    mov byte [r9], 0      ; null terminator
    mov rax, [rbp-24]     ; return header ptr
    mov rsp, rbp
    pop rbp
    ret
