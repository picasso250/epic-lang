; Non-returning target for an indirect call through a null callable value.
; Entered by jump with the generated function stack already 16-byte aligned.
__ep_null_callable:
    sub rsp, 48
    mov ecx, -11
    call GetStdHandle
    mov rcx, rax
    lea rdx, [__ep_null_callable_message]
    mov r8, 42
    lea r9, [_written]
    mov qword [rsp+32], 0
    call WriteFile
    mov ecx, 1
    call ExitProcess

section .data
__ep_null_callable_message:
    db 69, 112, 105, 99, 32, 114, 117, 110, 116, 105, 109, 101, 32, 101, 114, 114, 111, 114, 58, 32, 99, 97, 108, 108, 32, 111, 102, 32, 110, 117, 108, 108, 32, 99, 97, 108, 108, 97, 98, 108, 101, 10
section .text
