; ── _argv_init: parse GetCommandLineA into argv: str[] ──
; returns: rax = pointer to { data: &&str, len: i64, cap: i64 }
; v0 parser: whitespace separates args, double quotes group args.
_argv_init:
    push rbp
    mov rbp, rsp
    sub rsp, 64
    call GetCommandLineA
    mov [rbp-8], rax      ; cursor
    ; Allocate argv header.
    mov ecx, 24
    sub rsp, 40
    call __ep_alloc
    add rsp, 40
    mov [rbp-16], rax     ; header
    mov qword [rax+8], 0
    mov qword [rax+16], 16
    ; Allocate pointer array.
    mov ecx, 128
    sub rsp, 40
    call __ep_alloc
    add rsp, 40
    mov rcx, [rbp-16]
    mov [rcx], rax
_argv_skip_ws:
    mov rsi, [rbp-8]
    mov al, [rsi]
    cmp al, 0
    je _argv_done
    cmp al, 32
    je _argv_advance_ws
    cmp al, 9
    je _argv_advance_ws
    cmp al, 13
    je _argv_advance_ws
    cmp al, 10
    je _argv_advance_ws
    jmp _argv_arg_start
_argv_advance_ws:
    inc qword [rbp-8]
    jmp _argv_skip_ws
_argv_arg_start:
    mov rsi, [rbp-8]
    mov al, [rsi]
    xor r11, r11          ; quoted flag
    cmp al, 34
    jne _argv_start_plain
    mov r11, 1
    inc rsi
    mov [rbp-8], rsi
_argv_start_plain:
    mov [rbp-24], rsi     ; arg start
    xor r10, r10          ; len
_argv_scan:
    mov al, [rsi]
    cmp al, 0
    je _argv_emit
    test r11, r11
    jnz _argv_scan_quoted
    cmp al, 32
    je _argv_emit
    cmp al, 9
    je _argv_emit
    cmp al, 13
    je _argv_emit
    cmp al, 10
    je _argv_emit
    jmp _argv_take
_argv_scan_quoted:
    cmp al, 34
    je _argv_emit_quoted
_argv_take:
    inc rsi
    inc r10
    jmp _argv_scan
_argv_emit_quoted:
    mov [rbp-8], rsi
    inc qword [rbp-8]     ; skip closing quote
    jmp _argv_store
_argv_emit:
    mov [rbp-8], rsi
_argv_store:
    mov rcx, [rbp-24]
    mov rdx, r10
    call _str_alloc
    mov rcx, [rbp-16]
    mov rdx, [rcx+8]
    cmp rdx, [rcx+16]
    jge _argv_done        ; fixed cap is enough for v0 self-hosting
    mov r8, [rcx]
    mov [r8+rdx*8], rax
    inc qword [rcx+8]
    jmp _argv_skip_ws
_argv_done:
    mov rax, [rbp-16]
    mov rsp, rbp
    pop rbp
    ret
