"""
Epic v0 — NASM helper routines emitted at end of .asm
"""

STR_ALLOC_HELPER = r"""
; ── _str_alloc: deep-copy bytes into heap-allocated str ──
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
"""

ITOA_HELPER = r"""
; ── _itoa: convert integer to heap-allocated str ──
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
"""

SYSTEM_HELPER = r"""
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
"""

LISTDIR_HELPER = r"""
; ── _listdir: list files matching pattern ──
; rcx = pattern (C string), rdx = max
; returns: rax = pointer to { data: &&str, len: i64, cap: i64 }
_listdir:
    push rbp
    mov rbp, rsp
    sub rsp, 688         ; WIN32_FIND_DATAA(592) + 96
    push r12             ; rbp-696
    push r13             ; rbp-704
    push r14             ; rbp-712
    push r15             ; rbp-720
    push rcx             ; rbp-728 save pattern
    push rdx             ; rbp-736 save max
    ; Allocate header (24 bytes)
    mov rcx, [_heap]
    mov edx, 8
    mov r8d, 24
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov r14, rax         ; r14 = header ptr
    mov qword [r14+8], 0 ; header.len = 0 (offset 8)
    mov rax, [rbp-736]
    mov [r14+16], rax    ; header.cap = max (offset 16)
    ; Allocate pointer array: max * 8
    mov rcx, [_heap]
    mov edx, 8
    mov r8, [rbp-736]    ; max
    imul r8, 8
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov [r14], rax       ; header.data = pointer array (offset 0)
    ; FindFirstFileA
    lea rdx, [rbp-592]
    mov rcx, [rbp-728]   ; pattern
    sub rsp, 40
    call FindFirstFileA
    add rsp, 40
    cmp rax, -1
    je _listdir_done2
    mov r15, rax          ; r15 = find handle
_listdir_loop2:
    mov rcx, [r14+8]      ; current count (offset 8)
    cmp rcx, [rbp-736]    ; max
    jge _listdir_close2
    ; Get filename length
    lea rcx, [rbp-592+44]
    sub rsp, 40
    call lstrlenA
    add rsp, 40
    mov r12, rax          ; r12 = filename length
    ; Allocate str struct (16 bytes)
    mov rcx, [_heap]
    mov edx, 8
    mov r8d, 16
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov r13, rax          ; r13 = str ptr
    mov [r13+8], r12      ; str.len = filename length (offset 8)
    ; Allocate filename buffer (len + 1)
    mov r8, r12
    inc r8
    mov rcx, [_heap]
    mov edx, 8
    sub rsp, 40
    call HeapAlloc
    add rsp, 40
    mov [r13], rax        ; str.data = filename buffer (offset 0)
    ; Copy filename
    mov rcx, rax          ; dst = filename buffer
    lea rdx, [rbp-592+44] ; src = cFileName
    sub rsp, 40
    call lstrcpyA
    add rsp, 40
    ; Store str ptr in pointer array
    mov rcx, [r14]        ; pointer array base (offset 0)
    mov rax, [r14+8]      ; current index (offset 8)
    mov [rcx + rax*8], r13
    inc qword [r14+8]     ; header.len++ (offset 8)
    ; FindNextFileA
    mov rcx, r15
    lea rdx, [rbp-592]
    sub rsp, 40
    call FindNextFileA
    add rsp, 40
    test eax, eax
    jnz _listdir_loop2
_listdir_close2:
    mov rcx, r15
    sub rsp, 40
    call FindClose
    add rsp, 40
_listdir_done2:
    mov rax, r14          ; return header ptr
    pop rdx               ; discard saved max
    pop rcx               ; discard saved pattern
    pop r15
    pop r14
    pop r13
    pop r12
    mov rsp, rbp
    pop rbp
    ret
"""

READ_FILE_HELPER = r"""
; ── _read_file: read whole file into heap-allocated str ──
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
"""
