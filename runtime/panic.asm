; Non-returning panic helper.
; rcx = &str { data: &u8, len: i64 }
__ep_panic:
    sub rsp, 72
    mov rax, [rcx]
    mov [rsp+40], rax
    mov rax, [rcx+8]
    mov [rsp+48], rax

    mov ecx, -12
    call GetStdHandle
    mov [rsp+56], rax

    mov rcx, rax
    lea rdx, [__ep_panic_prefix]
    mov r8, 12
    lea r9, [_written]
    mov qword [rsp+32], 0
    call WriteFile

    mov rcx, [rsp+56]
    mov rdx, [rsp+40]
    mov r8, [rsp+48]
    lea r9, [_written]
    mov qword [rsp+32], 0
    call WriteFile

    mov rcx, [rsp+56]
    lea rdx, [__ep_panic_newline]
    mov r8, 1
    lea r9, [_written]
    mov qword [rsp+32], 0
    call WriteFile

    mov ecx, 1
    call ExitProcess

section .data
__ep_panic_prefix:
    db 69, 112, 105, 99, 32, 112, 97, 110, 105, 99, 58, 32
__ep_panic_newline:
    db 10
section .text
