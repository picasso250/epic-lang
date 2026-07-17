; Non-returning target for pop on an empty dynamic array.
; Entered by jump with the generated function stack already 16-byte aligned.
__ep_pop_fail:
    sub rsp, 48
    mov ecx, -11
    call GetStdHandle
    mov rcx, rax
    lea rdx, [__ep_pop_message]
    mov r8, 41
    lea r9, [_written]
    mov qword [rsp+32], 0
    call WriteFile
    mov ecx, 1
    call ExitProcess

section .data
__ep_pop_message:
    db 69, 112, 105, 99, 32, 114, 117, 110, 116, 105, 109, 101, 32, 101, 114, 114, 111, 114, 58, 32, 112, 111, 112, 32, 102, 114, 111, 109, 32, 101, 109, 112, 116, 121, 32, 97, 114, 114, 97, 121, 10
section .text
