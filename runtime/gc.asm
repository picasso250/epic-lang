; Managed allocation entry point. GC metadata will use separate raw helpers.
; rcx = requested payload size
; returns: rax = zero-initialized payload
__ep_alloc:
    push rbp
    mov rbp, rsp
    sub rsp, 32
    mov r8, rcx
    mov rcx, [_heap]
    mov edx, 8
    call HeapAlloc
    mov rsp, rbp
    pop rbp
    ret
