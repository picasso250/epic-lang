global _start
extern ExitProcess
extern GetStdHandle
extern WriteFile
extern CreateFileA
extern ReadFile
extern SetFilePointer
extern CloseHandle
extern GetFileSize
extern lstrcmpA
extern lstrcpyA
extern lstrlenA
extern CreateProcessA
extern WaitForSingleObject
extern GetExitCodeProcess
extern GetCommandLineA
extern HeapAlloc
extern GetProcessHeap
extern Beep
extern GetCurrentProcess
extern GetCurrentProcessId
extern GetCurrentThreadId
extern GetFileAttributesA
extern GetLastError
extern GetTickCount64
extern MessageBoxA
extern SetLastError
extern Sleep
default rel

section .data
    _buf times 32 db 0
    _buf_end db 0
    _written dd 0
    _heap dq 0
    _argv dq 0

section .text

_start:
    push rbp
    mov rbp, rsp
    sub rsp, 64
    call GetProcessHeap
    mov [_heap], rax
    call _argv_init
    mov [_argv], rax
    mov rax, 0
    mov [rbp-8], rax
    mov rcx, [rbp-8]
    sub rsp, 32
    call ExitProcess
    add rsp, 32
    mov ecx, 0
    call ExitProcess

; ©¤©¤ _str_alloc: deep-copy bytes into heap-allocated str ©¤©¤
; rcx = src pointer, rdx = len
; returns: rax = &str { data: &i8, len: i64 }
; clobbers: rax, rcx, rdx, r8, r9, r10, r11
_str_alloc:
    push rbp
    mov rbp, rsp
    sub rsp, 40           ; 3 save slots (24) + alignment
    mov [rbp-8], rcx      ; save src
    mov [rbp-16], rdx     ; save len
    ; Allocate header (16 bytes)
    mov rcx, [_heap]
    mov edx, 8
    mov r8d, 16
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov [rbp-24], rax     ; save header ptr
    ; Allocate data (len + 1 for null terminator)
    mov rcx, [_heap]
    mov edx, 8
    mov r8, [rbp-16]      ; len
    inc r8                ; +1 for null
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
                          ; rax = data ptr
    ; Store data ptr and len in header
    mov rcx, [rbp-24]     ; rcx = header
    mov [rcx], rax        ; header.data = data (offset 0)
    mov rdx, [rbp-16]     ; rdx = len
    mov [rcx+8], rdx      ; header.len = len (offset 8)
    ; Copy bytes
    test rdx, rdx
    mov r9, rax           ; r9 = dst cursor (set before branch for len=0 case)
    jz _str_alloc_null
    mov r8, [rbp-8]       ; r8 = src
_str_alloc_copy:
    mov r10b, [r8]
    mov [r9], r10b
    inc r8
    inc r9
    dec rdx
    jnz _str_alloc_copy
_str_alloc_null:
    mov byte [r9], 0      ; null terminator
    mov rax, [rbp-24]     ; return header ptr
    mov rsp, rbp
    pop rbp
    ret
; ©¤©¤ _itoa: convert integer to heap-allocated str ©¤©¤
; rcx = number
; returns: rax = &str (heap-allocated { data: &i8, len: i64 })
_itoa:
    push rbp
    mov rbp, rsp
    sub rsp, 88           ; 48 (saves) + 32 (temp) + 8 (align)
    mov r8, 0             ; sign flag
    mov rax, rcx
    test rax, rax
    jns .positive
    neg rax
    mov r8, 1             ; has sign
.positive:
    test rax, rax
    jnz .convert
    lea r10, [zero_str_data]
    mov r11, 1
    mov r8, 0
    jmp .save_state
.convert:
    lea r10, [rbp-80]
    add r10, 31
    sub r10, r8           ; leave room for sign
    mov r11, 0
.digit_loop:
    xor rdx, rdx
    mov rcx, 10
    div rcx
    add dl, '0'
    dec r10
    mov [r10], dl
    inc r11
    test rax, rax
    jnz .digit_loop
.save_state:
    mov [rbp-16], r10     ; save first digit ptr (volatile)
    mov [rbp-24], r11     ; save digit count (volatile)
    mov [rbp-32], r8      ; save sign flag
    ; Allocate header (16 bytes)
    mov rcx, [_heap]
    mov edx, 8
    mov r8d, 16
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov [rbp-8], rax      ; save header
    ; Compute total len
    mov r8, [rbp-24]       ; digit count
    add r8, [rbp-32]       ; + sign flag
    ; Allocate data (total len + 1)
    mov rcx, [_heap]
    mov edx, 8
    push r8               ; save total len
    inc r8                ; +1 for null
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    pop rdx               ; rdx = total len
    mov rcx, [rbp-8]
    mov [rcx], rax        ; header.data = data
    mov [rcx+8], rdx      ; header.len = total len
    ; Restore volatile state
    mov r10, [rbp-16]     ; first digit ptr
    mov r11, [rbp-24]     ; digit count
    mov r8, [rbp-32]      ; sign flag
    ; Write sign if negative
    mov r9, rax           ; dst cursor
    test r8, r8
    jz .copy_digits
    mov byte [r9], '-'
    inc r9
.copy_digits:
    mov rcx, r11
    test rcx, rcx
    jz .nullterm
.copy:
    mov al, [r10]
    mov [r9], al
    inc r10
    inc r9
    dec rcx
    jnz .copy
.nullterm:
    mov byte [r9], 0
    mov rax, [rbp-8]
    mov rsp, rbp
    pop rbp
    ret
zero_str_data: db '0', 0
; ©¤©¤ _argv_init: parse GetCommandLineA into argv: str[] ©¤©¤
; returns: rax = pointer to { data: &&str, len: i64, cap: i64 }
; v0 parser: whitespace separates args, double quotes group args.
_argv_init:
    push rbp
    mov rbp, rsp
    sub rsp, 64
    call GetCommandLineA
    mov [rbp-8], rax      ; cursor
    ; Allocate argv header.
    mov rcx, [_heap]
    mov edx, 8
    mov r8d, 24
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov [rbp-16], rax     ; header
    mov qword [rax+8], 0
    mov qword [rax+16], 16
    ; Allocate pointer array.
    mov rcx, [_heap]
    mov edx, 8
    mov r8d, 128
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov rcx, [rbp-16]
    mov [rcx], rax
_argv_skip_ws:
    mov rsi, [rbp-8]
    mov al, [rsi]
    cmp al, 0
    je _argv_done
    cmp al, 32
    je _argv_advance_ws
    cmp al, 9
    je _argv_advance_ws
    cmp al, 13
    je _argv_advance_ws
    cmp al, 10
    je _argv_advance_ws
    jmp _argv_arg_start
_argv_advance_ws:
    inc qword [rbp-8]
    jmp _argv_skip_ws
_argv_arg_start:
    mov rsi, [rbp-8]
    mov al, [rsi]
    xor r11, r11          ; quoted flag
    cmp al, 34
    jne _argv_start_plain
    mov r11, 1
    inc rsi
    mov [rbp-8], rsi
_argv_start_plain:
    mov [rbp-24], rsi     ; arg start
    xor r10, r10          ; len
_argv_scan:
    mov al, [rsi]
    cmp al, 0
    je _argv_emit
    test r11, r11
    jnz _argv_scan_quoted
    cmp al, 32
    je _argv_emit
    cmp al, 9
    je _argv_emit
    cmp al, 13
    je _argv_emit
    cmp al, 10
    je _argv_emit
    jmp _argv_take
_argv_scan_quoted:
    cmp al, 34
    je _argv_emit_quoted
_argv_take:
    inc rsi
    inc r10
    jmp _argv_scan
_argv_emit_quoted:
    mov [rbp-8], rsi
    inc qword [rbp-8]     ; skip closing quote
    jmp _argv_store
_argv_emit:
    mov [rbp-8], rsi
_argv_store:
    mov rcx, [rbp-24]
    mov rdx, r10
    call _str_alloc
    mov rcx, [rbp-16]
    mov rdx, [rcx+8]
    cmp rdx, [rcx+16]
    jge _argv_done        ; fixed cap is enough for v0 self-hosting
    mov r8, [rcx]
    mov [r8+rdx*8], rax
    inc qword [rcx+8]
    jmp _argv_skip_ws
_argv_done:
    mov rax, [rbp-16]
    mov rsp, rbp
    pop rbp
    ret
; ©¤©¤ _system: execute command via CreateProcessA ©¤©¤
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
    mov rax, -1               ; failure ¡ú -1
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
; ©¤©¤ _read_file: read whole file into heap-allocated str ©¤©¤
; rcx = path (C string)
; returns: rax = &str
_read_file:
    push rbp
    mov rbp, rsp
    sub rsp, 64
    mov [rbp-8], rcx       ; path
    ; CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL)
    mov rcx, [rbp-8]
    mov edx, 0x80000000
    mov r8d, 1
    xor r9d, r9d
    sub rsp, 56
    mov dword [rsp+32], 3
    mov dword [rsp+40], 0x80
    mov qword [rsp+48], 0
    call CreateFileA
    add rsp, 56
    cmp rax, -1
    je _read_file_empty
    mov [rbp-16], rax      ; handle
    ; size = GetFileSize(handle, NULL)
    mov rcx, rax
    xor edx, edx
    sub rsp, 40
    call GetFileSize
    add rsp, 40
    mov [rbp-24], rax      ; size
    ; buf = HeapAlloc(heap, zero, size + 1)
    mov rcx, [_heap]
    mov edx, 8
    mov r8, rax
    inc r8
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov [rbp-32], rax      ; buf
    ; ReadFile(handle, buf, size, &read, NULL)
    mov rcx, [rbp-16]
    mov rdx, [rbp-32]
    mov r8, [rbp-24]
    lea r9, [rbp-40]
    sub rsp, 40
    mov qword [rsp+32], 0
    call ReadFile
    add rsp, 40
    ; CloseHandle(handle)
    mov rcx, [rbp-16]
    sub rsp, 40
    call CloseHandle
    add rsp, 40
    ; Deep-copy exactly the bytes read into str.
    mov rcx, [rbp-32]
    mov edx, [rbp-40]
    call _str_alloc
    jmp _read_file_done
_read_file_empty:
    lea rcx, [_read_file_empty_data]
    xor edx, edx
    call _str_alloc
_read_file_done:
    mov rsp, rbp
    pop rbp
    ret
_read_file_empty_data: db 0
; ©¤©¤ _write_file: write whole str to a file ©¤©¤
; rcx = path (C string), rdx = data pointer, r8 = len
; returns: rax = bytes written, or -1 on failure
_write_file:
    push rbp
    mov rbp, rsp
    sub rsp, 64
    mov [rbp-8], rcx       ; path
    mov [rbp-16], rdx      ; data
    mov [rbp-24], r8       ; len
    ; CreateFileA(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL)
    mov rcx, [rbp-8]
    mov edx, 0x40000000
    xor r8d, r8d
    xor r9d, r9d
    sub rsp, 56
    mov dword [rsp+32], 2
    mov dword [rsp+40], 0x80
    mov qword [rsp+48], 0
    call CreateFileA
    add rsp, 56
    cmp rax, -1
    je _write_file_fail
    mov [rbp-32], rax      ; handle
    ; WriteFile(handle, data, len, &written, NULL)
    mov rcx, [rbp-32]
    mov rdx, [rbp-16]
    mov r8, [rbp-24]
    lea r9, [rbp-40]
    sub rsp, 40
    mov qword [rsp+32], 0
    call WriteFile
    add rsp, 40
    test eax, eax
    jz _write_file_close_fail
    ; CloseHandle(handle)
    mov rcx, [rbp-32]
    sub rsp, 40
    call CloseHandle
    add rsp, 40
    mov eax, [rbp-40]
    jmp _write_file_done
_write_file_close_fail:
    mov rcx, [rbp-32]
    sub rsp, 40
    call CloseHandle
    add rsp, 40
_write_file_fail:
    mov rax, -1
_write_file_done:
    mov rsp, rbp
    pop rbp
    ret
; ©¤©¤ _append_file: append whole str to a file ©¤©¤
; rcx = path (C string), rdx = data pointer, r8 = len
; returns: rax = bytes written, or -1 on failure
_append_file:
    push rbp
    mov rbp, rsp
    sub rsp, 64
    mov [rbp-8], rcx       ; path
    mov [rbp-16], rdx      ; data
    mov [rbp-24], r8       ; len
    ; CreateFileA(path, GENERIC_WRITE, 0, NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL)
    mov rcx, [rbp-8]
    mov edx, 0x40000000
    xor r8d, r8d
    xor r9d, r9d
    sub rsp, 56
    mov dword [rsp+32], 4
    mov dword [rsp+40], 0x80
    mov qword [rsp+48], 0
    call CreateFileA
    add rsp, 56
    cmp rax, -1
    je _append_file_fail
    mov [rbp-32], rax      ; handle
    ; SetFilePointer(handle, 0, NULL, FILE_END)
    mov rcx, [rbp-32]
    xor edx, edx
    xor r8d, r8d
    mov r9d, 2
    sub rsp, 40
    call SetFilePointer
    add rsp, 40
    cmp eax, -1
    je _append_file_close_fail
    ; WriteFile(handle, data, len, &written, NULL)
    mov rcx, [rbp-32]
    mov rdx, [rbp-16]
    mov r8, [rbp-24]
    lea r9, [rbp-40]
    sub rsp, 40
    mov qword [rsp+32], 0
    call WriteFile
    add rsp, 40
    test eax, eax
    jz _append_file_close_fail
    ; CloseHandle(handle)
    mov rcx, [rbp-32]
    sub rsp, 40
    call CloseHandle
    add rsp, 40
    mov eax, [rbp-40]
    jmp _append_file_done
_append_file_close_fail:
    mov rcx, [rbp-32]
    sub rsp, 40
    call CloseHandle
    add rsp, 40
_append_file_fail:
    mov rax, -1
_append_file_done:
    mov rsp, rbp
    pop rbp
    ret
