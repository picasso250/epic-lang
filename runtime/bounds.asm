; Non-returning target for checked str/array subscripts.
; Entered by jump with the generated function stack already 16-byte aligned.
__ep_bounds_fail:
    sub rsp, 48
    mov ecx, -11
    call GetStdHandle
    mov rcx, rax
    lea rdx, [__ep_bounds_message]
    mov r8, 40
    lea r9, [_written]
    mov qword [rsp+32], 0
    call WriteFile
    mov ecx, 1
    call ExitProcess

section .data
__ep_bounds_message:
    db 69, 112, 105, 99, 32, 114, 117, 110, 116, 105, 109, 101, 32, 101, 114, 114, 111, 114, 58, 32, 105, 110, 100, 101, 120, 32, 111, 117, 116, 32, 111, 102, 32, 98, 111, 117, 110, 100, 115, 10
section .text
