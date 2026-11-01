; Single-threaded conservative non-moving mark-and-sweep collector.
; Managed payloads have no headers. Raw side tables are never scanned.

section .data
_gc_stack_high:
    dq 0
_gc_objects:
    dq 0
_gc_sizes:
    dq 0
_gc_object_count:
    dq 0
_gc_object_capacity:
    dq 0
_gc_live_bytes:
    dq 0
_gc_small_live_bytes:
    dq 0
_gc_small_object_count:
    dq 0
_gc_threshold:
    dq 8388608
_gc_low_addr:
    dq 0x7fffffffffffffff
_gc_high_addr:
    dq 0
_gc_table:
    dq 0
_gc_table_capacity:
    dq 0
_gc_marks:
    dq 0
_gc_work:
    dq 0
_gc_work_count:
    dq 0
_gc_small_arena:
    dq 0
_gc_small_arena_end:
    dq 0
_gc_small_page_classes:
    dq 0
_gc_small_page_bumps:
    dq 0
_gc_small_page_free_heads:
    dq 0
_gc_small_page_alloc_maps:
    dq 0
_gc_small_page_mark_maps:
    dq 0
_gc_small_active_pages:
    dq 0
_gc_small_page_count:
    dq 0

section .text

; Raw zeroed allocation for collector metadata. rcx=size, rax=address/null.
__ep_gc_raw_try_alloc:
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

; Raw allocation which terminates on failure. rcx=size, rax=address.
__ep_gc_raw_alloc:
    push rbp
    mov rbp, rsp
    sub rsp, 32
    call __ep_gc_raw_try_alloc
    test rax, rax
    jnz __ep_gc_raw_alloc_done
    mov ecx, 1
    call ExitProcess
__ep_gc_raw_alloc_done:
    mov rsp, rbp
    pop rbp
    ret

; Raw free. rcx=address.
__ep_gc_raw_free:
    push rbp
    mov rbp, rsp
    sub rsp, 32
    test rcx, rcx
    jz __ep_gc_raw_free_done
    mov r8, rcx
    mov rcx, [_heap]
    xor edx, edx
    call HeapFree
__ep_gc_raw_free_done:
    mov rsp, rbp
    pop rbp
    ret

; Reserve a 1 GiB small-object arena and allocate its side tables.
__ep_gc_small_init:
    push rbp
    mov rbp, rsp
    sub rsp, 32
    xor ecx, ecx
    mov rdx, 1073741824
    mov r8d, 8192
    mov r9d, 4
    call VirtualAlloc
    test rax, rax
    jnz __ep_gc_small_init_metadata
    mov ecx, 1
    call ExitProcess
__ep_gc_small_init_metadata:
    mov [_gc_small_arena], rax
    add rax, 1073741824
    mov [_gc_small_arena_end], rax
    mov rcx, 16384
    call __ep_gc_raw_alloc
    mov [_gc_small_page_classes], rax
    mov rcx, 131072
    call __ep_gc_raw_alloc
    mov [_gc_small_page_bumps], rax
    mov rcx, 131072
    call __ep_gc_raw_alloc
    mov [_gc_small_page_free_heads], rax
    mov rcx, 131072
    call __ep_gc_raw_alloc
    mov [_gc_small_page_alloc_maps], rax
    mov rcx, 131072
    call __ep_gc_raw_alloc
    mov [_gc_small_page_mark_maps], rax
    mov rcx, 32
    call __ep_gc_raw_alloc
    mov [_gc_small_active_pages], rax
    mov rsp, rbp
    pop rbp
    ret

; Commit one 64 KiB page for class rcx (1=8B, ..., 4=32B).
; Returns page index + 1.
__ep_gc_small_acquire_page:
    push rbp
    mov rbp, rsp
    sub rsp, 64
    mov [rbp-8], rcx
    mov rax, [_gc_small_page_count]
    cmp rax, 16384
    jl __ep_gc_small_acquire_commit
    mov ecx, 1
    call ExitProcess
__ep_gc_small_acquire_commit:
    mov [rbp-16], rax
    imul rax, 65536
    add rax, [_gc_small_arena]
    mov [rbp-24], rax
    mov rcx, rax
    mov rdx, 65536
    mov r8d, 4096
    mov r9d, 4
    call VirtualAlloc
    test rax, rax
    jnz __ep_gc_small_acquire_maps
    mov ecx, 1
    call ExitProcess
__ep_gc_small_acquire_maps:
    mov rax, 8192
    cqo
    idiv qword [rbp-8]
    mov [rbp-32], rax
    mov rcx, rax
    call __ep_gc_raw_alloc
    mov [rbp-40], rax
    mov rcx, [rbp-32]
    call __ep_gc_raw_alloc
    mov [rbp-48], rax
    mov rax, [rbp-16]
    mov r8, [_gc_small_page_classes]
    mov rcx, [rbp-8]
    mov byte [r8+rax], cl
    mov r8, [_gc_small_page_alloc_maps]
    mov r9, [rbp-40]
    mov [r8+rax*8], r9
    mov r8, [_gc_small_page_mark_maps]
    mov r9, [rbp-48]
    mov [r8+rax*8], r9
    inc rax
    mov [_gc_small_page_count], rax
    mov r8, [_gc_small_active_pages]
    mov rcx, [rbp-8]
    dec rcx
    mov [r8+rcx*8], rax
    mov rsp, rbp
    pop rbp
    ret

; Find reusable committed storage for class rcx. Returns page index + 1 or 0.
__ep_gc_small_find_page:
    push rbp
    mov rbp, rsp
    sub rsp, 48
    mov [rbp-8], rcx
    mov rax, 8192
    cqo
    idiv rcx
    mov [rbp-16], rax
    mov qword [rbp-24], 0
__ep_gc_small_find_page_loop:
    mov rax, [rbp-24]
    cmp rax, [_gc_small_page_count]
    jge __ep_gc_small_find_page_miss
    mov r8, [_gc_small_page_classes]
    movzx ecx, byte [r8+rax]
    cmp rcx, [rbp-8]
    jne __ep_gc_small_find_page_next
    mov r8, [_gc_small_page_free_heads]
    cmp qword [r8+rax*8], 0
    jne __ep_gc_small_find_page_hit
    mov r8, [_gc_small_page_bumps]
    mov r9, [r8+rax*8]
    cmp r9, [rbp-16]
    jl __ep_gc_small_find_page_hit
__ep_gc_small_find_page_next:
    inc qword [rbp-24]
    jmp __ep_gc_small_find_page_loop
__ep_gc_small_find_page_hit:
    inc rax
    mov r8, [_gc_small_active_pages]
    mov rcx, [rbp-8]
    dec rcx
    mov [r8+rcx*8], rax
    mov rsp, rbp
    pop rbp
    ret
__ep_gc_small_find_page_miss:
    xor eax, eax
    mov rsp, rbp
    pop rbp
    ret

; Allocate a zeroed 8/16/24/32-byte slot. rcx=requested size.
__ep_gc_small_alloc:
    push rbp
    mov rbp, rsp
    sub rsp, 80
    mov rax, rcx
    add rax, 7
    mov cl, 3
    shr rax, cl
    test rax, rax
    jnz __ep_gc_small_alloc_class_ready
    mov rax, 1
__ep_gc_small_alloc_class_ready:
    mov [rbp-8], rax
__ep_gc_small_alloc_select:
    mov r8, [_gc_small_active_pages]
    mov rcx, [rbp-8]
    dec rcx
    mov rax, [r8+rcx*8]
    test rax, rax
    jnz __ep_gc_small_alloc_page_ready
    mov rcx, [rbp-8]
    call __ep_gc_small_find_page
    test rax, rax
    jnz __ep_gc_small_alloc_page_ready
    mov rcx, [rbp-8]
    call __ep_gc_small_acquire_page
__ep_gc_small_alloc_page_ready:
    dec rax
    mov [rbp-16], rax
    mov r8, [_gc_small_page_free_heads]
    mov r9, [r8+rax*8]
    test r9, r9
    jz __ep_gc_small_alloc_bump
    dec r9
    mov [rbp-24], r9
    mov rcx, [rbp-8]
    imul rcx, 8
    mov r10, rax
    imul r10, 65536
    mov r11, r9
    imul r11, rcx
    add r10, r11
    add r10, [_gc_small_arena]
    mov r11, [r10]
    mov [r8+rax*8], r11
    jmp __ep_gc_small_alloc_record
__ep_gc_small_alloc_bump:
    mov r8, [_gc_small_page_bumps]
    mov r9, [r8+rax*8]
    mov [rbp-24], r9
    mov rcx, [rbp-8]
    mov rax, 8192
    cqo
    idiv rcx
    cmp r9, rax
    jl __ep_gc_small_alloc_use_bump
    mov r8, [_gc_small_active_pages]
    mov rcx, [rbp-8]
    dec rcx
    mov qword [r8+rcx*8], 0
    jmp __ep_gc_small_alloc_select
__ep_gc_small_alloc_use_bump:
    mov rax, [rbp-16]
    inc qword [r8+rax*8]
    mov rcx, [rbp-8]
    imul rcx, 8
    mov r10, rax
    imul r10, 65536
    mov r11, r9
    imul r11, rcx
    add r10, r11
    add r10, [_gc_small_arena]
__ep_gc_small_alloc_record:
    mov [rbp-32], r10
    mov rax, [rbp-16]
    mov r8, [_gc_small_page_alloc_maps]
    mov r8, [r8+rax*8]
    mov r9, [rbp-24]
    mov byte [r8+r9], 1
    mov qword [r10], 0
    mov rax, [rbp-8]
    cmp rax, 1
    je __ep_gc_small_alloc_zeroed
    mov qword [r10+8], 0
    cmp rax, 2
    je __ep_gc_small_alloc_zeroed
    mov qword [r10+16], 0
    cmp rax, 3
    je __ep_gc_small_alloc_zeroed
    mov qword [r10+24], 0
__ep_gc_small_alloc_zeroed:
    inc qword [_gc_small_object_count]
    mov rax, [rbp-8]
    imul rax, 8
    add [_gc_small_live_bytes], rax
    add [_gc_live_bytes], rax
    mov rax, [rbp-32]
    mov rsp, rbp
    pop rbp
    ret

; Grow persistent parallel address/size tables. rcx=new capacity.
__ep_gc_grow_objects:
    push rbp
    mov rbp, rsp
    sub rsp, 64
    mov [rbp-8], rcx
    mov rax, rcx
    imul rax, 8
    mov rcx, rax
    call __ep_gc_raw_alloc
    mov [rbp-16], rax
    mov rax, [rbp-8]
    imul rax, 8
    mov rcx, rax
    call __ep_gc_raw_alloc
    mov [rbp-24], rax
    mov qword [rbp-32], 0
__ep_gc_grow_copy:
    mov rax, [rbp-32]
    cmp rax, [_gc_object_count]
    jge __ep_gc_grow_copied
    mov r8, [_gc_objects]
    mov r9, [r8+rax*8]
    mov r10, [rbp-16]
    mov [r10+rax*8], r9
    mov r8, [_gc_sizes]
    mov r9, [r8+rax*8]
    mov r10, [rbp-24]
    mov [r10+rax*8], r9
    inc qword [rbp-32]
    jmp __ep_gc_grow_copy
__ep_gc_grow_copied:
    mov rcx, [_gc_objects]
    call __ep_gc_raw_free
    mov rcx, [_gc_sizes]
    call __ep_gc_raw_free
    mov rax, [rbp-16]
    mov [_gc_objects], rax
    mov rax, [rbp-24]
    mov [_gc_sizes], rax
    mov rax, [rbp-8]
    mov [_gc_object_capacity], rax
    mov rsp, rbp
    pop rbp
    ret

__ep_gc_ensure_object_capacity:
    push rbp
    mov rbp, rsp
    sub rsp, 32
    mov rax, [_gc_object_count]
    cmp rax, [_gc_object_capacity]
    jl __ep_gc_ensure_done
    mov rcx, [_gc_object_capacity]
    test rcx, rcx
    jnz __ep_gc_ensure_double
    mov rcx, 1024
    jmp __ep_gc_ensure_grow
__ep_gc_ensure_double:
    add rcx, rcx
__ep_gc_ensure_grow:
    call __ep_gc_grow_objects
__ep_gc_ensure_done:
    mov rsp, rbp
    pop rbp
    ret

; Insert address rcx -> object index rdx into the current hash table.
__ep_gc_table_insert:
    push rbp
    mov rbp, rsp
    sub rsp, 32
    mov [rbp-8], rcx
    mov [rbp-16], rdx
    mov rax, rcx
    mov cl, 4
    shr rax, cl
    mov r8, [_gc_table_capacity]
    dec r8
    and rax, r8
__ep_gc_table_insert_probe:
    mov r9, [_gc_table]
    cmp qword [r9+rax*8], 0
    je __ep_gc_table_insert_store
    inc rax
    and rax, r8
    jmp __ep_gc_table_insert_probe
__ep_gc_table_insert_store:
    mov rdx, [rbp-16]
    inc rdx
    mov [r9+rax*8], rdx
    mov rsp, rbp
    pop rbp
    ret

; Exact-base lookup. rcx=candidate, rax=index or -1.
__ep_gc_lookup:
    push rbp
    mov rbp, rsp
    sub rsp, 32
    mov [rbp-8], rcx
    test rcx, rcx
    jz __ep_gc_lookup_miss
    mov r8, [_gc_low_addr]
    cmp rcx, r8
    jl __ep_gc_lookup_miss
    mov r8, [_gc_high_addr]
    cmp rcx, r8
    jg __ep_gc_lookup_miss
    mov rax, rcx
    mov cl, 4
    shr rax, cl
    mov r8, [_gc_table_capacity]
    dec r8
    and rax, r8
__ep_gc_lookup_probe:
    mov r9, [_gc_table]
    mov r10, [r9+rax*8]
    test r10, r10
    jz __ep_gc_lookup_miss
    dec r10
    mov r9, [_gc_objects]
    mov r9, [r9+r10*8]
    cmp r9, [rbp-8]
    je __ep_gc_lookup_hit
    inc rax
    and rax, r8
    jmp __ep_gc_lookup_probe
__ep_gc_lookup_hit:
    mov rax, r10
    mov rsp, rbp
    pop rbp
    ret
__ep_gc_lookup_miss:
    mov rax, -1
    mov rsp, rbp
    pop rbp
    ret

; Allocate temporary hash, mark bytes, and work stack.
__ep_gc_prepare_collection:
    push rbp
    mov rbp, rsp
    sub rsp, 64
    mov rax, [_gc_object_count]
    add rax, rax
    mov [rbp-8], rax
    mov qword [rbp-16], 1
__ep_gc_prepare_cap_loop:
    mov rax, [rbp-16]
    cmp rax, [rbp-8]
    jge __ep_gc_prepare_cap_done
    add rax, rax
    mov [rbp-16], rax
    jmp __ep_gc_prepare_cap_loop
__ep_gc_prepare_cap_done:
    mov rax, [rbp-16]
    mov [_gc_table_capacity], rax
    imul rax, 8
    mov rcx, rax
    call __ep_gc_raw_alloc
    mov [_gc_table], rax
    mov rcx, [_gc_object_count]
    test rcx, rcx
    jnz __ep_gc_prepare_marks_size
    mov rcx, 1
__ep_gc_prepare_marks_size:
    call __ep_gc_raw_alloc
    mov [_gc_marks], rax
    mov rcx, [_gc_object_count]
    add rcx, [_gc_small_object_count]
    test rcx, rcx
    jnz __ep_gc_prepare_work_size
    mov rcx, 1
__ep_gc_prepare_work_size:
    imul rcx, 8
    call __ep_gc_raw_alloc
    mov [_gc_work], rax
    mov qword [_gc_work_count], 0
    mov qword [rbp-24], 0
__ep_gc_prepare_insert_loop:
    mov rdx, [rbp-24]
    cmp rdx, [_gc_object_count]
    jge __ep_gc_prepare_done
    mov r8, [_gc_objects]
    mov rcx, [r8+rdx*8]
    call __ep_gc_table_insert
    inc qword [rbp-24]
    jmp __ep_gc_prepare_insert_loop
__ep_gc_prepare_done:
    mov rsp, rbp
    pop rbp
    ret

; Mark one exact large candidate and enqueue it once. rcx=candidate.
__ep_gc_mark_large_candidate:
    push rbp
    mov rbp, rsp
    sub rsp, 32
    call __ep_gc_lookup
    cmp rax, -1
    je __ep_gc_mark_large_candidate_done
    mov r8, [_gc_marks]
    movzx ecx, byte [r8+rax]
    test ecx, ecx
    jnz __ep_gc_mark_large_candidate_done
    mov byte [r8+rax], 1
    mov r9, [_gc_work]
    mov r10, [_gc_work_count]
    add rax, rax
    mov [r9+r10*8], rax
    inc r10
    mov [_gc_work_count], r10
__ep_gc_mark_large_candidate_done:
    mov rsp, rbp
    pop rbp
    ret

; Mark an exact small-slot base. Returns 1 for every address owned by the arena.
__ep_gc_mark_small_candidate:
    push rbp
    mov rbp, rsp
    sub rsp, 64
    mov [rbp-8], rcx
    mov r8, [_gc_small_arena]
    cmp rcx, r8
    jl __ep_gc_mark_small_outside
    mov r9, [_gc_small_arena_end]
    cmp rcx, r9
    jge __ep_gc_mark_small_outside
    sub rcx, r8
    mov rax, rcx
    mov cl, 16
    shr rax, cl
    cmp rax, [_gc_small_page_count]
    jge __ep_gc_mark_small_owned
    mov [rbp-16], rax
    mov rdx, [rbp-8]
    sub rdx, r8
    and rdx, 65535
    mov r8, [_gc_small_page_classes]
    movzx ecx, byte [r8+rax]
    test ecx, ecx
    jz __ep_gc_mark_small_owned
    mov [rbp-24], rcx
    imul rcx, 8
    mov rax, rdx
    cqo
    idiv rcx
    test rdx, rdx
    jnz __ep_gc_mark_small_owned
    mov [rbp-32], rax
    mov r8, [_gc_small_page_bumps]
    mov r9, [rbp-16]
    cmp rax, [r8+r9*8]
    jge __ep_gc_mark_small_owned
    mov r8, [_gc_small_page_alloc_maps]
    mov r8, [r8+r9*8]
    movzx ecx, byte [r8+rax]
    test ecx, ecx
    jz __ep_gc_mark_small_owned
    mov r8, [_gc_small_page_mark_maps]
    mov r8, [r8+r9*8]
    movzx ecx, byte [r8+rax]
    test ecx, ecx
    jnz __ep_gc_mark_small_owned
    mov byte [r8+rax], 1
    mov r10, r9
    imul r10, 8192
    add r10, rax
    add r10, r10
    inc r10
    mov r8, [_gc_work]
    mov r9, [_gc_work_count]
    mov [r8+r9*8], r10
    inc r9
    mov [_gc_work_count], r9
__ep_gc_mark_small_owned:
    mov rax, 1
    mov rsp, rbp
    pop rbp
    ret
__ep_gc_mark_small_outside:
    xor eax, eax
    mov rsp, rbp
    pop rbp
    ret

; Mark one exact candidate and enqueue it once. rcx=candidate.
__ep_gc_mark_candidate:
    push rbp
    mov rbp, rsp
    sub rsp, 32
    mov [rbp-8], rcx
    call __ep_gc_mark_small_candidate
    test rax, rax
    jnz __ep_gc_mark_candidate_done
    mov rcx, [rbp-8]
    call __ep_gc_mark_large_candidate
__ep_gc_mark_candidate_done:
    mov rsp, rbp
    pop rbp
    ret

; Roots are the explicit argv slot and every aligned word on the active stack.
__ep_gc_mark_roots:
    push rbp
    mov rbp, rsp
    sub rsp, 32
    mov rcx, [_argv]
    call __ep_gc_mark_candidate
    mov rax, rsp
    mov [rbp-8], rax
    mov rax, [_gc_stack_high]
    mov [rbp-16], rax
__ep_gc_mark_stack_loop:
    mov r8, [rbp-8]
    cmp r8, [rbp-16]
    jge __ep_gc_mark_roots_done
    mov rcx, [r8]
    add r8, 8
    mov [rbp-8], r8
    call __ep_gc_mark_candidate
    jmp __ep_gc_mark_stack_loop
__ep_gc_mark_roots_done:
    mov rsp, rbp
    pop rbp
    ret

; Transitively scan every marked payload as aligned 8-byte words.
__ep_gc_drain_marks:
    push rbp
    mov rbp, rsp
    sub rsp, 64
__ep_gc_drain_next_object:
    mov rax, [_gc_work_count]
    test rax, rax
    jz __ep_gc_drain_done
    dec rax
    mov [_gc_work_count], rax
    mov r8, [_gc_work]
    mov rax, [r8+rax*8]
    mov [rbp-8], rax
    mov r9, rax
    and r9, 1
    jnz __ep_gc_drain_small_object
    mov cl, 1
    shr rax, cl
    mov r8, [_gc_objects]
    mov r9, [r8+rax*8]
    mov [rbp-16], r9
    mov r8, [_gc_sizes]
    mov r9, [r8+rax*8]
    mov [rbp-24], r9
    jmp __ep_gc_drain_scan_ready
__ep_gc_drain_small_object:
    mov cl, 1
    shr rax, cl
    mov r9, rax
    and r9, 8191
    mov r10, rax
    mov cl, 13
    shr r10, cl
    mov r8, [_gc_small_page_classes]
    movzx ecx, byte [r8+r10]
    imul rcx, 8
    mov [rbp-24], rcx
    imul r10, 65536
    imul r9, rcx
    add r10, r9
    add r10, [_gc_small_arena]
    mov [rbp-16], r10
__ep_gc_drain_scan_ready:
    mov qword [rbp-32], 0
__ep_gc_drain_payload_loop:
    mov rax, [rbp-32]
    add rax, 8
    cmp rax, [rbp-24]
    jg __ep_gc_drain_next_object
    mov r8, [rbp-16]
    mov r9, [rbp-32]
    mov rcx, [r8+r9]
    add r9, 8
    mov [rbp-32], r9
    call __ep_gc_mark_candidate
    jmp __ep_gc_drain_payload_loop
__ep_gc_drain_done:
    mov rsp, rbp
    pop rbp
    ret

; Free unmarked large payloads and compact persistent side tables in place.
__ep_gc_sweep:
    push rbp
    mov rbp, rsp
    sub rsp, 64
    mov qword [rbp-8], 0
    mov qword [rbp-16], 0
    mov qword [rbp-24], 0
__ep_gc_sweep_loop:
    mov rax, [rbp-8]
    cmp rax, [_gc_object_count]
    jge __ep_gc_sweep_done
    mov r8, [_gc_marks]
    movzx ecx, byte [r8+rax]
    test ecx, ecx
    jz __ep_gc_sweep_dead
    mov r9, [_gc_objects]
    mov r10, [r9+rax*8]
    mov r8, [_gc_sizes]
    mov r11, [r8+rax*8]
    mov rdx, [rbp-16]
    mov [r9+rdx*8], r10
    mov [r8+rdx*8], r11
    inc qword [rbp-16]
    mov rax, r11
    cmp rax, 8
    jge __ep_gc_sweep_charge
    mov rax, 8
__ep_gc_sweep_charge:
    add [rbp-24], rax
    jmp __ep_gc_sweep_next
__ep_gc_sweep_dead:
    mov r8, [_gc_objects]
    mov rcx, [r8+rax*8]
    call __ep_gc_raw_free
__ep_gc_sweep_next:
    inc qword [rbp-8]
    jmp __ep_gc_sweep_loop
__ep_gc_sweep_done:
    mov rax, [rbp-16]
    mov [_gc_object_count], rax
    mov rax, [rbp-24]
    mov [_gc_live_bytes], rax
    mov rsp, rbp
    pop rbp
    ret

; Sweep small slots, rebuild free lists, and select active pages.
__ep_gc_sweep_small:
    push rbp
    mov rbp, rsp
    sub rsp, 96
    mov r8, [_gc_small_active_pages]
    mov qword [r8], 0
    mov qword [r8+8], 0
    mov qword [r8+16], 0
    mov qword [r8+24], 0
    mov qword [rbp-8], 0
    mov qword [rbp-24], 0
    mov qword [rbp-32], 0
__ep_gc_sweep_small_page:
    mov rax, [rbp-8]
    cmp rax, [_gc_small_page_count]
    jge __ep_gc_sweep_small_done
    mov r8, [_gc_small_page_classes]
    movzx ecx, byte [r8+rax]
    mov [rbp-40], rcx
    imul rcx, 8
    mov [rbp-48], rcx
    mov rax, 8192
    cqo
    mov rcx, [rbp-40]
    idiv rcx
    mov [rbp-56], rax
    mov qword [rbp-16], 0
__ep_gc_sweep_small_slot:
    mov rax, [rbp-16]
    cmp rax, [rbp-56]
    jge __ep_gc_sweep_small_page_done
    mov r9, [rbp-8]
    mov r8, [_gc_small_page_alloc_maps]
    mov r8, [r8+r9*8]
    movzx ecx, byte [r8+rax]
    test ecx, ecx
    jz __ep_gc_sweep_small_next_slot
    mov r8, [_gc_small_page_mark_maps]
    mov r8, [r8+r9*8]
    movzx ecx, byte [r8+rax]
    test ecx, ecx
    jz __ep_gc_sweep_small_dead
    mov byte [r8+rax], 0
    inc qword [rbp-24]
    mov r8, [rbp-48]
    add [rbp-32], r8
    jmp __ep_gc_sweep_small_next_slot
__ep_gc_sweep_small_dead:
    mov r8, [_gc_small_page_alloc_maps]
    mov r8, [r8+r9*8]
    mov byte [r8+rax], 0
    mov r10, r9
    imul r10, 65536
    mov r11, rax
    imul r11, [rbp-48]
    add r10, r11
    add r10, [_gc_small_arena]
    mov r8, [_gc_small_page_free_heads]
    mov r11, [r8+r9*8]
    mov [r10], r11
    inc rax
    mov [r8+r9*8], rax
__ep_gc_sweep_small_next_slot:
    inc qword [rbp-16]
    jmp __ep_gc_sweep_small_slot
__ep_gc_sweep_small_page_done:
    mov rcx, [rbp-40]
    dec rcx
    mov r8, [_gc_small_active_pages]
    cmp qword [r8+rcx*8], 0
    jne __ep_gc_sweep_small_next_page
    mov rax, [rbp-8]
    mov r9, [_gc_small_page_free_heads]
    cmp qword [r9+rax*8], 0
    jne __ep_gc_sweep_small_select_page
    mov r9, [_gc_small_page_bumps]
    mov r10, [r9+rax*8]
    cmp r10, [rbp-56]
    jge __ep_gc_sweep_small_next_page
__ep_gc_sweep_small_select_page:
    inc rax
    mov [r8+rcx*8], rax
__ep_gc_sweep_small_next_page:
    inc qword [rbp-8]
    jmp __ep_gc_sweep_small_page
__ep_gc_sweep_small_done:
    mov rax, [rbp-24]
    mov [_gc_small_object_count], rax
    mov rax, [rbp-32]
    mov [_gc_small_live_bytes], rax
    add [_gc_live_bytes], rax
    mov rax, [_gc_live_bytes]
    add rax, rax
    cmp rax, 8388608
    jge __ep_gc_sweep_small_threshold
    mov rax, 8388608
__ep_gc_sweep_small_threshold:
    mov [_gc_threshold], rax
    mov rsp, rbp
    pop rbp
    ret

__ep_gc_release_collection:
    push rbp
    mov rbp, rsp
    sub rsp, 32
    mov rcx, [_gc_table]
    call __ep_gc_raw_free
    mov rcx, [_gc_marks]
    call __ep_gc_raw_free
    mov rcx, [_gc_work]
    call __ep_gc_raw_free
    mov qword [_gc_table], 0
    mov qword [_gc_marks], 0
    mov qword [_gc_work], 0
    mov qword [_gc_table_capacity], 0
    mov qword [_gc_work_count], 0
    mov rsp, rbp
    pop rbp
    ret

__ep_gc_collect:
    push rbp
    mov rbp, rsp
    sub rsp, 32
    call __ep_gc_prepare_collection
    call __ep_gc_mark_roots
    call __ep_gc_drain_marks
    call __ep_gc_sweep
    call __ep_gc_sweep_small
    call __ep_gc_release_collection
    mov rsp, rbp
    pop rbp
    ret

; Managed zeroed allocation. rcx=requested payload size, rax=payload.
__ep_alloc:
    push rbp
    mov rbp, rsp
    sub rsp, 128
    mov [rbp-8], rcx
    mov [rbp-16], rax
    mov [rbp-24], rdx
    mov [rbp-32], r8
    mov [rbp-40], r9
    mov [rbp-48], r10
    mov [rbp-56], r11
    mov [rbp-64], rbx
    mov [rbp-72], rsi
    mov [rbp-80], rdi
    test rcx, rcx
    jns __ep_alloc_size_ok
    mov ecx, 1
    call ExitProcess
__ep_alloc_size_ok:
    mov rax, rcx
    cmp rax, 8
    jge __ep_alloc_charge_ready
    mov rax, 8
__ep_alloc_charge_ready:
    mov [rbp-120], rax
    add rax, [_gc_live_bytes]
    cmp rax, [_gc_threshold]
    jl __ep_alloc_after_threshold
    call __ep_gc_collect
__ep_alloc_after_threshold:
    mov rax, [rbp-8]
    cmp rax, 32
    jg __ep_alloc_large
    mov rcx, rax
    call __ep_gc_small_alloc
    jmp __ep_alloc_return
__ep_alloc_large:
    call __ep_gc_ensure_object_capacity
    mov rcx, [rbp-8]
    test rcx, rcx
    jnz __ep_alloc_try
    mov rcx, 1
__ep_alloc_try:
    call __ep_gc_raw_try_alloc
    test rax, rax
    jnz __ep_alloc_record
    call __ep_gc_collect
    mov rcx, [rbp-8]
    test rcx, rcx
    jnz __ep_alloc_retry
    mov rcx, 1
__ep_alloc_retry:
    call __ep_gc_raw_try_alloc
    test rax, rax
    jnz __ep_alloc_record
    mov ecx, 1
    call ExitProcess
__ep_alloc_record:
    mov r8, [_gc_low_addr]
    cmp rax, r8
    jge __ep_alloc_check_high
    mov [_gc_low_addr], rax
__ep_alloc_check_high:
    mov r8, [_gc_high_addr]
    cmp rax, r8
    jle __ep_alloc_bounds_done
    mov [_gc_high_addr], rax
__ep_alloc_bounds_done:
    mov r8, [_gc_object_count]
    mov r9, [_gc_objects]
    mov [r9+r8*8], rax
    mov r9, [_gc_sizes]
    mov r10, [rbp-8]
    mov [r9+r8*8], r10
    inc r8
    mov [_gc_object_count], r8
    mov r8, [_gc_live_bytes]
    add r8, [rbp-120]
    mov [_gc_live_bytes], r8
__ep_alloc_return:
    mov rsp, rbp
    pop rbp
    ret
