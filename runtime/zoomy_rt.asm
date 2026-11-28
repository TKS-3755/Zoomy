; =============================================================================
; zoomy_rt.asm - the Zoomy runtime (x86-64 Linux, position independent)
;
; Assemble with:   nasm -f bin zoomy_rt.asm -o zoomy_rt.bin
; (tools/build_runtime.py does this and embeds the bytes into zoomy.py, so
;  users of the compiler never need NASM.)
;
; The blob starts with a jump table of 5-byte entries:
;     +0   rt_print_f64     xmm0 = value            prints it (no newline)
;     +5   rt_read_f64      rdi  = &pushback slot   -> xmm0 = value, eax = 1 ok / 0 failed
;     +10  rt_read_char     rdi  = &pushback slot   -> xmm0 = char code, eax = 1 ok / 0 EOF
;     +15  rt_index_error   (does not return)       prints a message, exit(255)
;     +20  rt_pow           xmm0 = base, xmm1 = exponent   -> xmm0 = base ^ exponent
;     +25  rt_err_step      (does not return)       "a 'for' loop needs a step that is not zero", exit(255)
;     +30  rt_err_long      (does not return)       "this 'for' loop would run too long", exit(255)
;     +35  rt_err_count     (does not return)       "a count cannot be negative", exit(255)
;     +40  rt_err_deep      (does not return)       "too many nested calls", exit(255)
;     +45  rt_print_i64     rax = value             prints it as a signed 64-bit integer (no newline)
;     +50  rt_read_i64      rdi  = &pushback slot   -> rax = value, rdx = 1 ok / 0 failed
;     +55  rt_err_div0      (does not return)       "division by zero", exit(255)
;     +60  rt_pow_i64       rax = base, rcx = exponent -> rax = base ^ exponent (integers)
;     +70  rt_err_bit       (does not return)       "a shift or bit number must be from 0 to 63", exit(255)
;     +75  rt_read_byte     rdi  = &pushback slot   -> rax = next byte 0..255 (no whitespace skipping), rdx = 1 ok / 0 EOF
;     +85  rt_print_u64     rax = value             prints it as an unsigned 64-bit integer (no newline)
;     +90  rt_isqrt_u      rax = n (unsigned)      -> rax = floor(sqrt(n))
;     +95  rt_cores                         -> rax = number of processor cores this process may run on (sched_getaffinity)
;     +100 rt_openarr       rsi = &first slot of an array of character codes (0-terminated) -> rax = open(path, O_RDONLY): fd or -errno
;     +80  rt_clock         -> rax = milliseconds on the monotonic clock
;     +65  rt_isqrt         rax = x -> rax = floor(sqrt(x)) (0 for x <= 0)
;
; Everything is raw Linux syscalls; no libc, no data section, no relocations.
; Number format of rt_print_f64:
;     nan | inf | -inf | 0
;     1e-6 <= |x| < 1e15 : integer part, then up to 6 decimals (trailing zeros dropped)
;     otherwise          : scientific, d[.dddddd]e+XX / e-XX (at least 2 exponent digits)
; =============================================================================
bits 64
default rel

entry_table:
    jmp near rt_print_f64       ; +0
    jmp near rt_read_f64        ; +5
    jmp near rt_read_char       ; +10
    jmp near rt_index_error     ; +15
    jmp near rt_pow             ; +20
    jmp near rt_err_step        ; +25
    jmp near rt_err_long        ; +30
    jmp near rt_err_count       ; +35
    jmp near rt_err_deep        ; +40
    jmp near rt_print_i64       ; +45
    jmp near rt_read_i64        ; +50
    jmp near rt_err_div0        ; +55
    jmp near rt_pow_i64         ; +60
    jmp near rt_isqrt           ; +65
    jmp near rt_err_bit         ; +70
    jmp near rt_read_byte       ; +75
    jmp near rt_clock           ; +80
    jmp near rt_print_u64       ; +85
    jmp near rt_isqrt_u         ; +90
    jmp near rt_cores           ; +95
    jmp near rt_openarr         ; +100

; -----------------------------------------------------------------------------
; rt_print_f64 : print the double in xmm0 to stdout
; local frame: 80 bytes. output is built in [r13-80, r13-32), digit scratch
; in [r13-32, r13).
; -----------------------------------------------------------------------------
rt_print_f64:
    push rbx
    push r12
    push r13
    push r14
    sub rsp, 80
    lea r13, [rsp+80]               ; r13 = end of the frame (scratch end)
    lea rdi, [rsp]                  ; rdi = output cursor
    ucomisd xmm0, xmm0
    jp .nan
    movq rax, xmm0
    mov rcx, rax
    shr rcx, 63                     ; rcx = sign bit
    btr rax, 63                     ; rax = bits of |x|
    movq xmm0, rax                  ; xmm0 = |x|
    mov rdx, 0x7FF0000000000000
    cmp rax, rdx
    je .inf
    test rax, rax
    jz .zero
    mov rdx, 0x430C6BF526340000     ; 1e15
    cmp rax, rdx
    jae .sci
    mov rdx, 0x3EB0C6F7A0B5ED8D     ; 1e-6
    cmp rax, rdx
    jb .sci

    ; ---- plain notation ----------------------------------------------------
    test rcx, rcx
    jz .p1
    mov byte [rdi], '-'
    inc rdi
.p1:
    cvttsd2si rax, xmm0             ; integer part
    cvtsi2sd xmm1, rax
    movapd xmm2, xmm0
    subsd xmm2, xmm1                ; fractional part
    mov rdx, 0x412E848000000000     ; 1e6
    movq xmm3, rdx
    mulsd xmm2, xmm3
    cvtsd2si rdx, xmm2              ; fd = round-half-even(frac * 1e6)
    cmp rdx, 1000000
    jb .p2
    inc rax
    sub rdx, 1000000
.p2:
    mov r14, rdx
    call rt_utoa
    test r14, r14
    jz .done
    call rt_frac
    jmp .done

    ; ---- scientific notation ----------------------------------------------
.sci:
    test rcx, rcx
    jz .s1
    mov byte [rdi], '-'
    inc rdi
.s1:
    xor r12d, r12d                  ; r12 = decimal exponent
    mov rdx, 0x4024000000000000     ; 10.0
    movq xmm3, rdx
    mov rdx, 0x3FF0000000000000     ; 1.0
    movq xmm4, rdx
.sdown:                             ; while m >= 10: m /= 10, e++
    ucomisd xmm0, xmm3
    jb .sup
    divsd xmm0, xmm3
    inc r12
    jmp .sdown
.sup:                               ; while m < 1: m *= 10, e--
    ucomisd xmm0, xmm4
    jae .sfmt
    mulsd xmm0, xmm3
    dec r12
    jmp .sup
.sfmt:
    cvttsd2si rax, xmm0
    cvtsi2sd xmm1, rax
    movapd xmm2, xmm0
    subsd xmm2, xmm1
    mov rdx, 0x412E848000000000     ; 1e6
    movq xmm5, rdx
    mulsd xmm2, xmm5
    cvtsd2si rdx, xmm2
    cmp rdx, 1000000
    jb .sf2
    inc rax
    sub rdx, 1000000
.sf2:
    cmp rax, 10
    jb .sf3
    mov eax, 1                      ; 9.9999996 -> 10.000000 -> 1e+1 step
    inc r12
.sf3:
    mov r14, rdx
    call rt_utoa
    test r14, r14
    jz .sexp
    call rt_frac
.sexp:
    mov byte [rdi], 'e'
    inc rdi
    test r12, r12
    js .sneg
    mov byte [rdi], '+'
    jmp .sexp2
.sneg:
    mov byte [rdi], '-'
    neg r12
.sexp2:
    inc rdi
    mov rax, r12
    cmp rax, 10
    jae .sexp3
    mov byte [rdi], '0'
    inc rdi
.sexp3:
    call rt_utoa
    jmp .done

    ; ---- special values ----------------------------------------------------
.nan:
    mov dword [rdi], 'nan'          ; 'n','a','n',0
    add rdi, 3
    jmp .done
.inf:
    test rcx, rcx
    jz .inf2
    mov byte [rdi], '-'
    inc rdi
.inf2:
    mov dword [rdi], 'inf'
    add rdi, 3
    jmp .done
.zero:
    mov byte [rdi], '0'
    inc rdi

    ; ---- write the buffer --------------------------------------------------
.done:
    lea rsi, [r13-80]
    mov rdx, rdi
    sub rdx, rsi
    mov eax, 1
    mov edi, 1
    syscall
    add rsp, 80
    pop r14
    pop r13
    pop r12
    pop rbx
    ret

; rt_utoa : append the unsigned decimal of rax at [rdi], advancing rdi
rt_utoa:
    mov r8, r13                     ; scratch end
    mov r9d, 10
.u1:
    xor edx, edx
    div r9
    add dl, '0'
    dec r8
    mov [r8], dl
    test rax, rax
    jnz .u1
.u2:
    mov al, [r8]
    mov [rdi], al
    inc r8
    inc rdi
    cmp r8, r13
    jb .u2
    ret

; rt_frac : append '.' and the six decimals held in r14 (1..999999), dropping
;         trailing zeros
rt_frac:
    mov byte [rdi], '.'
    inc rdi
    mov rax, r14
    mov r9d, 100000                 ; current divisor
    mov r10d, 6
.f1:
    xor edx, edx
    div r9                          ; rax = digit, rdx = remainder
    add al, '0'
    mov [rdi], al
    inc rdi
    mov rcx, rdx                    ; rcx = remainder
    mov rax, r9
    xor edx, edx
    mov r11d, 10
    div r11
    mov r9, rax                     ; divisor /= 10
    mov rax, rcx
    dec r10d
    jnz .f1
.f2:
    cmp byte [rdi-1], '0'
    jne .f3
    dec rdi
    jmp .f2
.f3:
    ret

; -----------------------------------------------------------------------------
; rt_getc : rdi = &pushback slot -> rax = next byte (0..255) or -1 at EOF
;         the slot holds -1 when empty, otherwise a pushed-back byte
; -----------------------------------------------------------------------------
rt_getc:
    mov rax, [rdi]
    cmp rax, -1
    je .g1
    mov qword [rdi], -1
    ret
.g1:
    push rdi
    sub rsp, 16
    xor eax, eax                    ; sys_read
    mov rdi, [rdi-16]               ; the input file's descriptor (hidden slot 2; 0 = standard input)
    lea rsi, [rsp]
    mov edx, 1
    syscall
    cmp rax, 1
    jne .g2
    movzx eax, byte [rsp]
    jmp .g3
.g2:
    mov rax, -1
.g3:
    add rsp, 16
    pop rdi
    ret

; -----------------------------------------------------------------------------
; rt_read_char : skip whitespace, return the next character's code
; -----------------------------------------------------------------------------
rt_read_char:
    push rbx
    mov rbx, rdi
.rc1:
    mov rdi, rbx
    call rt_getc
    cmp rax, -1
    je .rcfail
    cmp rax, 32
    je .rc1
    lea rcx, [rax-9]
    cmp rcx, 4                      ; 9..13 are \t \n \v \f \r
    jbe .rc1
    cvtsi2sd xmm0, rax
    mov eax, 1
    pop rbx
    ret
.rcfail:
    xorpd xmm0, xmm0
    xor eax, eax
    pop rbx
    ret

; -----------------------------------------------------------------------------
; rt_read_f64 : read  [whitespace] [+|-] digits [. digits]
;   m = m*10 + digit over all digits; result = m / 10^(digits after the dot)
;   the character that ends the number is pushed back; an unusable first
;   character is consumed so input never gets stuck
; -----------------------------------------------------------------------------
rt_read_f64:
    push rbx
    push r12
    push r13
    push r14
    push r15
    mov rbx, rdi
.sk:
    mov rdi, rbx
    call rt_getc
    cmp rax, -1
    je .fail
    cmp rax, 32
    je .sk
    lea rcx, [rax-9]
    cmp rcx, 4
    jbe .sk
    xor r12d, r12d                  ; r12 = negative?
    cmp rax, '-'
    jne .plus
    mov r12d, 1
    jmp .next0
.plus:
    cmp rax, '+'
    jne .start
.next0:
    mov rdi, rbx
    call rt_getc
.start:
    xorpd xmm0, xmm0                ; m = 0
    mov rdx, 0x4024000000000000
    movq xmm1, rdx                  ; 10.0
    xor r13d, r13d                  ; digits seen
    xor r14d, r14d                  ; digits after the dot
    xor r15d, r15d                  ; seen the dot?
.loop:
    cmp rax, -1
    je .end_nopb
    mov rcx, rax
    sub rcx, '0'
    cmp rcx, 9
    ja .notdigit
    mulsd xmm0, xmm1
    cvtsi2sd xmm2, rcx
    addsd xmm0, xmm2
    inc r13
    test r15, r15
    jz .nxt
    inc r14
.nxt:
    mov rdi, rbx
    call rt_getc
    jmp .loop
.notdigit:
    cmp rax, '.'
    jne .end_pb
    test r15, r15
    jnz .end_pb
    mov r15d, 1
    jmp .nxt
.end_pb:
    mov [rbx], rax                  ; push the terminator back
.end_nopb:
    test r13, r13
    jz .fail2
    mov rdx, 0x3FF0000000000000
    movq xmm3, rdx                  ; p = 1.0
    mov rcx, r14
.pw:
    test rcx, rcx
    jz .pwdone
    mulsd xmm3, xmm1
    dec rcx
    jmp .pw
.pwdone:
    divsd xmm0, xmm3
    test r12, r12
    jz .ok
    movq rax, xmm0
    btc rax, 63
    movq xmm0, rax
.ok:
    mov eax, 1
    jmp .rfret
.fail2:
    mov qword [rbx], -1             ; consume the offending character
.fail:
    xorpd xmm0, xmm0
    xor eax, eax
.rfret:
    pop r15
    pop r14
    pop r13
    pop r12
    pop rbx
    ret

; -----------------------------------------------------------------------------
; rt_index_error : array index outside 0..size-1
; -----------------------------------------------------------------------------
rt_index_error:
    mov eax, 1
    mov edi, 2
    lea rsi, [rel .msg]
    mov edx, .msg_end - .msg
    syscall
    mov edi, 255
    mov eax, 60
    syscall
.msg:
    db "zoomy: runtime error: array index out of range", 10
.msg_end:

; -----------------------------------------------------------------------------
; rt_pow : xmm0 ^ xmm1
;   whole exponent (|e| < 2^63): exponentiation by squaring, 1/result for negative e
;   otherwise: x87  2^(e*log2(x))  (NaN for a negative base, like math.pow raising ValueError)
; -----------------------------------------------------------------------------
rt_pow:
    ucomisd xmm1, xmm1
    jp .nonwhole                    ; NaN exponent
    movapd xmm2, xmm1
    mov rax, 0x7FFFFFFFFFFFFFFF
    movq rcx, xmm2
    and rcx, rax                    ; rcx = bits of |e|
    mov rdx, 0x43E0000000000000     ; 2^63
    cmp rcx, rdx
    jae .nonwhole                   ; |e| >= 2^63 (or inf)
    movq xmm2, rcx                  ; xmm2 = |e|
    cvttsd2si rax, xmm2             ; n = |e| truncated
    cvtsi2sd xmm3, rax
    ucomisd xmm3, xmm2
    jne .nonwhole                   ; not a whole number
    mov rdx, 0x3FF0000000000000
    movq xmm2, rdx                  ; result = 1.0
.sq:
    test rax, rax
    jz .sqdone
    test al, 1
    jz .sq2
    mulsd xmm2, xmm0
.sq2:
    mulsd xmm0, xmm0
    shr rax, 1
    jmp .sq
.sqdone:
    movq rcx, xmm1
    test rcx, rcx
    jns .sqpos
    mov rdx, 0x3FF0000000000000
    movq xmm0, rdx
    divsd xmm0, xmm2                ; 1 / result
    ret
.sqpos:
    movapd xmm0, xmm2
    ret
.nonwhole:
    sub rsp, 16
    movsd [rsp], xmm1
    fld qword [rsp]                 ; st0 = e
    movsd [rsp], xmm0
    fld qword [rsp]                 ; st0 = x, st1 = e
    fyl2x                           ; st0 = e * log2(x)
    fld st0
    frndint
    fsub st1, st0                   ; st1 = fractional part
    fxch
    f2xm1
    fld1
    faddp st1, st0
    fscale
    fstp st1
    fstp qword [rsp]
    movsd xmm0, [rsp]
    add rsp, 16
    ret

; -----------------------------------------------------------------------------
; runtime errors that only print a message and exit(255)
; -----------------------------------------------------------------------------
rt_err_step:
    lea rsi, [rel .msg]
    mov edx, .msg_end - .msg
    jmp rt_fail
.msg:
    db "zoomy: runtime error: a 'for' loop needs a step that is not zero", 10
.msg_end:

rt_err_long:
    lea rsi, [rel .msg]
    mov edx, .msg_end - .msg
    jmp rt_fail
.msg:
    db "zoomy: runtime error: this 'for' loop would run too long", 10
.msg_end:

rt_err_count:
    lea rsi, [rel .msg]
    mov edx, .msg_end - .msg
    jmp rt_fail
.msg:
    db "zoomy: runtime error: a count cannot be negative", 10
.msg_end:

rt_err_deep:
    lea rsi, [rel .msg]
    mov edx, .msg_end - .msg
    jmp rt_fail
.msg:
    db "zoomy: runtime error: too many nested calls (a function calls itself without stopping?)", 10
.msg_end:

; -----------------------------------------------------------------------------
; integer mode (Zoomy 5.5): print / read a signed 64-bit integer
; -----------------------------------------------------------------------------
rt_print_i64:
    push rbx
    sub rsp, 32
    lea rsi, [rsp+32]
    mov rbx, rax
    test rax, rax
    jns .pos
    neg rax
.pos:
    mov r8d, 10
.dl:
    xor edx, edx
    div r8
    add dl, '0'
    dec rsi
    mov [rsi], dl
    test rax, rax
    jnz .dl
    test rbx, rbx
    jns .nosign
    dec rsi
    mov byte [rsi], '-'
.nosign:
    lea rdx, [rsp+32]
    sub rdx, rsi
    mov eax, 1
    mov edi, 1
    syscall
    add rsp, 32
    pop rbx
    ret

rt_print_u64:
    push rbx
    sub rsp, 32
    lea rsi, [rsp+32]
    mov r8d, 10
.dl:
    xor edx, edx
    div r8
    add dl, '0'
    dec rsi
    mov [rsi], dl
    test rax, rax
    jnz .dl
    lea rdx, [rsp+32]
    sub rdx, rsi
    mov eax, 1
    mov edi, 1
    syscall
    add rsp, 32
    pop rbx
    ret

rt_isqrt_u:
    mov r8, rax
    xor eax, eax
    mov ecx, 1
    shl rcx, 62
.a:
    cmp rcx, r8
    jbe .loop
    shr rcx, 2
    jnz .a
    ret
.loop:
    lea rdx, [rax+rcx]
    cmp r8, rdx
    jb .no
    sub r8, rdx
    shr rax, 1
    add rax, rcx
    jmp .nx
.no:
    shr rax, 1
.nx:
    shr rcx, 2
    jnz .loop
    ret

rt_read_i64:
    push rbx
    push r12
    push r13
    push r14
    mov rbx, rdi
.sk:
    mov rdi, rbx
    call rt_getc
    cmp rax, -1
    je .fail
    cmp rax, 32
    je .sk
    lea rcx, [rax-9]
    cmp rcx, 4
    jbe .sk
    xor r12d, r12d
    cmp rax, '-'
    jne .plus
    mov r12d, 1
    jmp .next0
.plus:
    cmp rax, '+'
    jne .start
.next0:
    mov rdi, rbx
    call rt_getc
.start:
    xor r13d, r13d
    xor r14d, r14d
.loop:
    cmp rax, -1
    je .end_nopb
    mov rcx, rax
    sub rcx, '0'
    cmp rcx, 9
    ja .end_pb
    imul r14, r14, 10
    add r14, rcx
    inc r13
    mov rdi, rbx
    call rt_getc
    jmp .loop
.end_pb:
    mov [rbx], rax
.end_nopb:
    test r13, r13
    jz .fail2
    test r12, r12
    jz .ok
    neg r14
.ok:
    mov rax, r14
    mov edx, 1
    jmp .ret
.fail2:
    mov qword [rbx], -1
.fail:
    xor eax, eax
    xor edx, edx
.ret:
    pop r14
    pop r13
    pop r12
    pop rbx
    ret

rt_err_div0:
    lea rsi, [rel .msg]
    mov edx, .msg_end - .msg
    jmp rt_fail
.msg:
    db "zoomy: runtime error: division by zero", 10
.msg_end:

rt_pow_i64:
    test rcx, rcx
    js .neg
    mov rdx, 1
.l:
    test rcx, rcx
    jz .d
    test cl, 1
    jz .s
    imul rdx, rax
.s:
    imul rax, rax
    shr rcx, 1
    jmp .l
.d:
    mov rax, rdx
    ret
.neg:
    cmp rax, 1
    je .one
    cmp rax, -1
    jne .n2
    test cl, 1
    jz .one
    mov rax, -1
    ret
.n2:
    test rax, rax
    jz rt_err_div0
    xor eax, eax
    ret
.one:
    mov eax, 1
    ret

rt_isqrt:
    test rax, rax
    jle .z
    mov r8, rax
    cvtsi2sd xmm0, rax
    sqrtsd xmm0, xmm0
    cvttsd2si rcx, xmm0
.dn:
    mov rax, rcx
    imul rax, rax
    cmp rax, r8
    jbe .up
    dec rcx
    jmp .dn
.up:
    lea rax, [rcx+1]
    imul rax, rax
    cmp rax, r8
    ja .done
    inc rcx
    jmp .up
.done:
    mov rax, rcx
    ret
.z:
    xor eax, eax
    ret

rt_read_byte:
    call rt_getc
    cmp rax, -1
    je .rb1
    mov edx, 1
    ret
.rb1:
    xor eax, eax
    xor edx, edx
    ret

rt_cores:
    sub rsp, 136
    mov eax, 204                    ; sched_getaffinity(0, 128, &mask): up to 1024 cores
    xor edi, edi
    mov esi, 128
    mov rdx, rsp
    syscall
    xor ecx, ecx
    test rax, rax
    jle .done
    shr rax, 3                      ; bytes -> 64-bit words
    xor edx, edx
.lp:
    cmp rdx, rax
    jge .done
    popcnt rsi, [rsp+rdx*8]
    add rcx, rsi
    inc rdx
    jmp .lp
.done:
    mov rax, rcx
    test rax, rax
    jnz .ok
    mov eax, 1
.ok:
    add rsp, 136
    ret

rt_openarr:
    sub rsp, 264
    mov rdi, rsp
    xor ecx, ecx
.lp:
    mov rax, [rsi+rcx*8]
    mov [rdi+rcx], al
    test al, al
    jz .go
    inc rcx
    cmp rcx, 255
    jb .lp
    mov byte [rdi+rcx], 0
.go:
    xor esi, esi
    xor edx, edx
    mov eax, 2                      ; open(path, O_RDONLY)
    syscall
    add rsp, 264
    ret

rt_clock:
    sub rsp, 16
    mov eax, 228                    ; clock_gettime(CLOCK_MONOTONIC, &ts)
    mov edi, 1
    mov rsi, rsp
    syscall
    mov rax, [rsp+8]
    xor edx, edx
    mov ecx, 1000000
    div rcx
    mov rcx, rax
    mov rax, [rsp]
    imul rax, rax, 1000
    add rax, rcx
    add rsp, 16
    ret

rt_err_bit:
    lea rsi, [rel .msg]
    mov edx, .msg_end - .msg
    jmp rt_fail
.msg:
    db "zoomy: runtime error: a shift or bit number must be from 0 to 63", 10
.msg_end:

rt_fail:
    mov eax, 1
    mov edi, 2
    syscall
    mov edi, 255
    mov eax, 60
    syscall
