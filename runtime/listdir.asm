; ── _listdir: list files matching pattern ──
; rcx = pattern (C string), rdx = max
; returns: rax = pointer to { data: &&str, len: i64, cap: i64 }
_listdir:
    push rbp
    mov rbp, rsp
    sub rsp, 688         ; WIN32_FIND_DATAA(592) + 96
    push r12             ; rbp-696
    push r13             ; rbp-704
    push r14             ; rbp-712
    push r15             ; rbp-720
    push rcx             ; rbp-728 save pattern
    push rdx             ; rbp-736 save max
    ; Allocate header (24 bytes)
    mov rcx, [_heap]
    mov edx, 8
    mov r8d, 24
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov r14, rax         ; r14 = header ptr
    mov qword [r14+8], 0 ; header.len = 0 (offset 8)
    mov rax, [rbp-736]
    mov [r14+16], rax    ; header.cap = max (offset 16)
    ; Allocate pointer array: max * 8
    mov rcx, [_heap]
    mov edx, 8
    mov r8, [rbp-736]    ; max
    imul r8, 8
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov [r14], rax       ; header.data = pointer array (offset 0)
    ; FindFirstFileA
    lea rdx, [rbp-592]
    mov rcx, [rbp-728]   ; pattern
    sub rsp, 40
    call FindFirstFileA
    add rsp, 40
    cmp rax, -1
    je _listdir_done2
    mov r15, rax          ; r15 = find handle
_listdir_loop2:
    mov rcx, [r14+8]      ; current count (offset 8)
    cmp rcx, [rbp-736]    ; max
    jge _listdir_close2
    ; Get filename length
    lea rcx, [rbp-592+44]
    sub rsp, 40
    call lstrlenA
    add rsp, 40
    mov r12, rax          ; r12 = filename length
    ; Allocate str struct (16 bytes)
    mov rcx, [_heap]
    mov edx, 8
    mov r8d, 16
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov r13, rax          ; r13 = str ptr
    mov [r13+8], r12      ; str.len = filename length (offset 8)
    ; Allocate filename buffer (len + 1)
    mov r8, r12
    inc r8
    mov rcx, [_heap]
    mov edx, 8
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov [r13], rax        ; str.data = filename buffer (offset 0)
    ; Copy filename
    mov rcx, rax          ; dst = filename buffer
    lea rdx, [rbp-592+44] ; src = cFileName
    sub rsp, 40
    call lstrcpyA
    add rsp, 40
    ; Store str ptr in pointer array
    mov rcx, [r14]        ; pointer array base (offset 0)
    mov rax, [r14+8]      ; current index (offset 8)
    mov [rcx + rax*8], r13
    inc qword [r14+8]     ; header.len++ (offset 8)
    ; FindNextFileA
    mov rcx, r15
    lea rdx, [rbp-592]
    sub rsp, 40
    call FindNextFileA
    add rsp, 40
    test eax, eax
    jnz _listdir_loop2
_listdir_close2:
    mov rcx, r15
    sub rsp, 40
    call FindClose
    add rsp, 40
_listdir_done2:
    mov rax, r14          ; return header ptr
    pop rdx               ; discard saved max
    pop rcx               ; discard saved pattern
    pop r15
    pop r14
    pop r13
    pop r12
    mov rsp, rbp
    pop rbp
    ret
