; Non-returning target for an indirect call through a null callable value.
; Entered by jump with the generated function stack already 16-byte aligned.
__ep_null_callable:
    lea rcx, [__ep_null_callable_message]
    mov edx, 42
    jmp __ep_runtime_fail

section .data
__ep_null_callable_message:
    db 69, 112, 105, 99, 32, 114, 117, 110, 116, 105, 109, 101, 32, 101, 114, 114, 111, 114, 58, 32, 99, 97, 108, 108, 32, 111, 102, 32, 110, 117, 108, 108, 32, 99, 97, 108, 108, 97, 98, 108, 101, 10
section .text
