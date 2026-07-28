; Non-returning runtime error writer.
; RCX = message data, RDX = message length.
; Entered by jump with the generated function stack already 16-byte aligned.
__ep_runtime_fail:
    sub rsp, 64
    mov [rsp+40], rcx
    mov [rsp+48], rdx
    mov ecx, -11
    call GetStdHandle
    mov rcx, rax
    mov rdx, [rsp+40]
    mov r8, [rsp+48]
    lea r9, [_written]
    mov qword [rsp+32], 0
    call WriteFile
    mov ecx, 1
    call ExitProcess
