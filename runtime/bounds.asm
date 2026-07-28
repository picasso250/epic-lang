; Non-returning target for checked str/array subscripts.
; Entered by jump with the generated function stack already 16-byte aligned.
__ep_bounds_fail:
    lea rcx, [__ep_bounds_message]
    mov edx, 40
    jmp __ep_runtime_fail

__ep_slice_bounds_fail:
    lea rcx, [__ep_slice_bounds_message]
    mov edx, 40
    jmp __ep_runtime_fail

section .data
__ep_bounds_message:
    db 69, 112, 105, 99, 32, 114, 117, 110, 116, 105, 109, 101, 32, 101, 114, 114, 111, 114, 58, 32, 105, 110, 100, 101, 120, 32, 111, 117, 116, 32, 111, 102, 32, 98, 111, 117, 110, 100, 115, 10
__ep_slice_bounds_message:
    db 69, 112, 105, 99, 32, 114, 117, 110, 116, 105, 109, 101, 32, 101, 114, 114, 111, 114, 58, 32, 115, 108, 105, 99, 101, 32, 111, 117, 116, 32, 111, 102, 32, 98, 111, 117, 110, 100, 115, 10
section .text
