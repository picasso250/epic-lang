; Non-returning target for pop on an empty dynamic array.
; Entered by jump with the generated function stack already 16-byte aligned.
__ep_pop_fail:
    lea rcx, [__ep_pop_message]
    mov edx, 41
    jmp __ep_runtime_fail

section .data
__ep_pop_message:
    db 69, 112, 105, 99, 32, 114, 117, 110, 116, 105, 109, 101, 32, 101, 114, 114, 111, 114, 58, 32, 112, 111, 112, 32, 102, 114, 111, 109, 32, 101, 109, 112, 116, 121, 32, 97, 114, 114, 97, 121, 10
section .text
