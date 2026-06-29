; ── _system: execute command via CreateProcessA ──
; rcx = command line string
; returns: rax = exit code, or -1 on failure
_system:
    push rbp
    mov rbp, rsp
    sub rsp, 248         ; 128(SI+PI) + 80(call frame: 32 shadow + 48 params) + 40 pad
    push rcx             ; save cmd
    ; Zero STARTUPINFOA + PROCESS_INFORMATION (128 bytes)
    lea rdi, [rsp+96]    ; SI+PI at rsp+96 (above call frame)
    mov ecx, 32          ; 128/4 = 32 dwords
    xor eax, eax
    rep stosd
    ; si.cb = sizeof(STARTUPINFOA) = 104
    mov dword [rsp+96], 104
    ; CreateProcessA(NULL, cmd, NULL, NULL, 0, 0, NULL, NULL, &si, &pi)
    xor ecx, ecx              ; lpApplicationName = NULL
    pop rdx                   ; lpCommandLine
    xor r8, r8                ; lpProcessAttributes = NULL
    xor r9, r9                ; lpThreadAttributes = NULL
    mov qword [rsp+32], 0     ; bInheritHandles = FALSE
    mov qword [rsp+40], 0     ; dwCreationFlags = 0
    mov qword [rsp+48], 0     ; lpEnvironment = NULL
    mov qword [rsp+56], 0     ; lpCurrentDirectory = NULL
    lea rax, [rsp+96]
    mov [rsp+64], rax         ; lpStartupInfo
    lea rax, [rsp+200]
    mov [rsp+72], rax         ; lpProcessInformation
    call CreateProcessA
    ; Check result
    test eax, eax
    jnz _system_ok
    mov rax, -1               ; failure → -1
    jmp _system_done
_system_ok:
    ; WaitForSingleObject(pi.hProcess, INFINITE)
    mov rcx, [rsp+200]       ; pi.hProcess
    mov edx, -1               ; INFINITE
    sub rsp, 40
    call WaitForSingleObject
    add rsp, 40
    ; GetExitCodeProcess
    mov rcx, [rsp+200]       ; pi.hProcess
    lea rdx, [rbp-8]          ; exit code out
    sub rsp, 40
    call GetExitCodeProcess
    add rsp, 40
    ; CloseHandle(pi.hProcess)
    mov rcx, [rsp+200]
    sub rsp, 32
    call CloseHandle
    add rsp, 32
    ; CloseHandle(pi.hThread)
    mov rcx, [rsp+208]
    sub rsp, 32
    call CloseHandle
    add rsp, 32
    mov rax, [rbp-8]          ; return exit code
_system_done:
    mov rsp, rbp
    pop rbp
    ret
