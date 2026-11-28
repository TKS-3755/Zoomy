#!/usr/bin/env python3
"""
Zoomy 5.5 - an English-like language ("pseudocode that compiles"): native x86-64 Linux programs, or a standalone Python file.

    python3 zoomy.py program.zmy                 compile to ./program
    python3 zoomy.py program.zmy -o app --run    compile to ./app and run it
    python3 zoomy.py program.zmy --asm           print the generated assembly

Two ways to build, one code generator:
  * default  - writes a zero-dependency static ELF executable straight from Python
               (no assembler, no linker, no gcc needed).
  * gcc mode - used automatically when the program declares `extern` functions
               (or with --gcc): the same code is emitted as assembly text and
               linked with gcc so you can call libm / libc functions.

See README.md for the language reference.
"""
import os
import re
import struct
import subprocess
import sys
import tempfile

VERSION = "8.1"

# =============================================================================
# Errors
# =============================================================================
class ZoomyError(Exception):
    def __init__(self, message, file=None, line=None):
        super().__init__(message)
        self.message, self.file, self.line = message, file, line

    def __str__(self):
        if self.file and self.line:
            return f"{self.file}:{self.line}: {self.message}"
        if self.file:
            return f"{self.file}: {self.message}"
        return self.message


# =============================================================================
# Lexical pieces
# =============================================================================
NUM = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
CHR = r"'(?:[^'\\]|\\[nt0\\'])'"
IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
OPD = rf"(?:{NUM}|{CHR}|{IDENT})"          # operand: number, 'c' character, or variable

_NUM_RE = re.compile(NUM)
_CHR_RE = re.compile(CHR)
_IDENT_RE = re.compile(IDENT)
_OPD_RE = re.compile(OPD)

_ESC = {'n': 10, 't': 9, '0': 0, '\\': 92, "'": 39, '"': 34}


def is_number(tok):
    return _NUM_RE.fullmatch(tok) is not None


def is_char(tok):
    return _CHR_RE.fullmatch(tok) is not None


def is_literal(tok):
    return is_number(tok) or is_char(tok)


def literal_value(tok):
    if is_char(tok):
        body = tok[1:-1]
        return float(_ESC[body[1]] if body[0] == '\\' else ord(body))
    return float(tok)


def f64_bits(value):
    return struct.unpack('<Q', struct.pack('<d', value))[0]


# =============================================================================
# Source -> tree
# =============================================================================
class Node:
    __slots__ = ("kind", "text", "children", "else_children", "file", "line")

    def __init__(self, kind, text, file, line):
        self.kind, self.text, self.file, self.line = kind, text, file, line
        self.children = []
        self.else_children = None


def _balanced_tail(line, j):
    """True if line[j:] is one parenthetical: it opens at j and its matching ')' is the last non-blank character."""
    depth = 0
    end = len(line.rstrip())
    for k in range(j, end):
        c = line[k]
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0 and k != end - 1:
                return False
            if depth < 0:
                return False
    return depth == 0 and line[end - 1] == ')'


def strip_comment(line):
    """Comments are a (parenthetical) that follows a gap of at least 4 spaces or a tab, or that fills a whole line.
    The line must still carry its tabs (tabs are expanded after this)."""
    body = line.strip()
    if body.startswith("(") and _balanced_tail(line, len(line) - len(line.lstrip())):
        return ""
    in_str, i, n = False, len(line) - len(line.lstrip()), len(line)
    while i < n:
        c = line[i]
        if in_str:
            if c == '\\':
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "'":
            m = _CHR_RE.match(line, i) if "_CHR_RE" in globals() else CHR_RE.match(line, i)
            if m:
                i = m.end() - 1
        elif c in " \t":
            j = i
            while j < n and line[j] in " \t":
                j += 1
            if j < n and line[j] == '(' and ('\t' in line[i:j] or j - i >= 4) and _balanced_tail(line, j):
                return line[:i]
            i = j - 1
        i += 1
    return line


def parse_source(text, filename):
    """Turn source text into a list of Nodes using indentation for blocks."""
    items = []                                   # (lineno, indent, statement)
    for lineno, raw in enumerate(text.splitlines(), 1):
        stmt = strip_comment(raw).strip()
        raw = raw.expandtabs(4)
        if stmt:
            items.append((lineno, len(raw) - len(raw.lstrip()), stmt))

    def parse_block(idx, indent):
        nodes = []
        while idx < len(items):
            lineno, ind, stmt = items[idx]
            if ind < indent:
                break
            if ind > indent:
                raise ZoomyError("unexpected indentation", filename, lineno)
            if stmt.endswith(':'):
                head = stmt[:-1].strip()
                if head == "else":
                    prev = nodes[-1] if nodes else None
                    if prev is None or prev.kind != "if" or prev.else_children is not None:
                        raise ZoomyError("'else:' must directly follow an 'if' block", filename, lineno)
                    body, idx = parse_body(idx + 1, ind, filename, lineno, "else")
                    prev.else_children = body
                    continue
                kind = ("if" if head.startswith("if ") else
                        "while" if head.startswith("while ") else
                        "routine" if head.startswith("routine ") else
                        "action" if head == "action" or head.startswith("action ") else None)
                if kind is None:
                    raise ZoomyError(f"unknown block '{stmt}'", filename, lineno)
                node = Node(kind, head, filename, lineno)
                node.children, idx = parse_body(idx + 1, ind, filename, lineno, kind)
                nodes.append(node)
            else:
                nodes.append(Node("simple", stmt, filename, lineno))
                idx += 1
        return nodes, idx

    def parse_body(idx, parent_indent, fname, lineno, what):
        if idx < len(items) and items[idx][1] > parent_indent:
            return parse_block(idx, items[idx][1])
        return [], idx                            # empty block is allowed

    nodes, idx = parse_block(0, items[0][1] if items else 0)
    if idx < len(items):
        raise ZoomyError("inconsistent indentation", filename, items[idx][0])
    return nodes


# =============================================================================
# Statement grammar
# =============================================================================
_S = r"\s+"
STATEMENTS = [
    ("alloc",    rf"allocate{_S}array{_S}({IDENT}){_S}with{_S}(\d+){_S}slots"),
    ("store",    rf"store{_S}({OPD}){_S}in{_S}({IDENT}){_S}at{_S}index{_S}({OPD})"),
    ("load",     rf"load{_S}from{_S}({IDENT}){_S}at{_S}index{_S}({OPD}){_S}into{_S}({IDENT})"),
    ("set",      rf"set{_S}({IDENT}){_S}to{_S}({OPD})"),
    ("mul",      rf"multiply{_S}({IDENT}){_S}by{_S}({OPD})"),
    ("div",      rf"divide{_S}({IDENT}){_S}by{_S}({OPD})"),
    ("add",      rf"add{_S}({OPD}){_S}to{_S}({IDENT})"),
    ("sub",      rf"subtract{_S}({OPD}){_S}from{_S}({IDENT})"),
    ("rem",      rf"calculate{_S}remainder{_S}of{_S}({OPD}){_S}divided{_S}by{_S}({OPD}){_S}store{_S}in{_S}({IDENT})"),
    ("unary",    rf"calculate{_S}(square{_S}root|absolute{_S}value|floor|ceiling){_S}of{_S}({OPD}){_S}store{_S}in{_S}({IDENT})"),
    ("readchar", rf"read{_S}char{_S}({IDENT})"),
    ("read",     rf"read{_S}({IDENT})"),
    ("runwith",  rf"run{_S}({IDENT}){_S}with{_S}({OPD})"),
    ("run",      rf"run{_S}({IDENT})"),
    ("finish",   rf"finish(?:{_S}with{_S}({OPD}))?"),
    ("print",    rf"(print|write){_S}(.+)"),
    ("extern",   rf"extern{_S}({IDENT})"),
    ("include",  rf"include{_S}(.+)"),
]
STATEMENTS = [(name, re.compile(rx)) for name, rx in STATEMENTS]

COND_RE = re.compile(
    rf"({OPD}){_S}is{_S}(?:(not|less{_S}than|greater{_S}than|at{_S}least|at{_S}most){_S})?({OPD})")


def match_statement(text):
    for name, rx in STATEMENTS:
        m = rx.fullmatch(text)
        if m:
            return name, m
    return None, None


def parse_print_items(rest, node):
    """Parse the comma separated items of print/write: "text", char X, number, variable."""
    items, pos, n = [], 0, len(rest)
    while True:
        while pos < n and rest[pos] == ' ':
            pos += 1
        if pos >= n:
            raise ZoomyError("missing item after ','", node.file, node.line)
        if rest[pos] == '"':
            pos += 1
            buf = bytearray()
            while True:
                if pos >= n:
                    raise ZoomyError("unterminated string", node.file, node.line)
                c = rest[pos]
                if c == '"':
                    pos += 1
                    break
                if c == '\\':
                    pos += 1
                    if pos >= n or rest[pos] not in _ESC:
                        raise ZoomyError("bad escape in string (use \\n \\t \\\\ \\\" or \\0)", node.file, node.line)
                    buf.append(_ESC[rest[pos]])
                    pos += 1
                else:
                    buf += c.encode("utf-8")
                    pos += 1
            items.append(("str", bytes(buf)))
        else:
            m = re.compile(rf"char{_S}({OPD})").match(rest, pos)
            if m:
                items.append(("char", m.group(1)))
                pos = m.end()
            else:
                m = _OPD_RE.match(rest, pos)
                if not m:
                    raise ZoomyError(f"cannot understand '{rest[pos:].strip()}' in print", node.file, node.line)
                items.append(("num", m.group(0)))
                pos = m.end()
        while pos < n and rest[pos] == ' ':
            pos += 1
        if pos >= n:
            return items
        if rest[pos] != ',':
            raise ZoomyError("expected ',' between print items", node.file, node.line)
        pos += 1


# =============================================================================
# Library (include) resolution
# =============================================================================
def resolve_lib(search_dirs, rel):
    """Find <rel>.zmy (or .zmy.txt), ignoring letter case of folder and file names."""
    for base in search_dirs:
        for ext in (".zmy", ".zmy.txt"):
            cur, ok = base, True
            for part in (rel + ext).split('/'):
                direct = os.path.join(cur, part)
                if os.path.exists(direct):
                    cur = direct
                    continue
                try:
                    names = os.listdir(cur)
                except OSError:
                    ok = False
                    break
                hits = [nm for nm in names if nm.lower() == part.lower()]
                if not hits:
                    ok = False
                    break
                cur = os.path.join(cur, hits[0])
            if ok and os.path.isfile(cur):
                return cur
    return None


# =============================================================================
# The assembler: every method appends machine code AND the same instruction as
# assembly text, so the default build and gcc mode can never disagree.
# =============================================================================
JCC = {"jmp": None, "ja": 0x87, "jne": 0x85, "je": 0x84, "jp": 0x8A, "jbe": 0x86, "jb": 0x82, "jae": 0x83,
       "jl": 0x8C, "jle": 0x8E, "jg": 0x8F, "jge": 0x8D, "js": 0x88, "jns": 0x89, "jo": 0x80}
RT_PRINT, RT_READ, RT_READCHAR, RT_INDEX_ERR, RT_POW = 0, 5, 10, 15, 20      # runtime jump-table offsets
RT_ERR_STEP, RT_ERR_LONG, RT_ERR_COUNT, RT_ERR_DEEP = 25, 30, 35, 40
RT_PRINT_I, RT_READ_I, RT_ERR_DIV0, RT_POW_I, RT_ISQRT, RT_ERR_BIT, RT_READ_BYTE, RT_CLOCK, RT_PRINT_U, RT_ISQRT_U, RT_CORES = 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95      # integer mode (5.5)
RT_OPENARR = 100


class SharedOff(int):
    """the displacement of an array that lives in the memory shared between workers (addressed from r15)"""


def _d32(v):
    return struct.pack('<i', v)


def _mem(d):
    return f"[rbp{d:+d}]".replace("+-", "-")


CALLEEREGS = bool(os.environ.get("ZOOMY_CALLEEREGS"))                    # off by default: it did not pay for itself on the chess engine
CALLEE_MIN = int(os.environ.get("ZOOMY_CALLEE_MIN", "16"))
LEAFREGS = not os.environ.get("ZOOMY_NO_LEAFREGS")                       # scratch registers for the variables of leaf functions
REGS = bool(os.environ.get("ZOOMY_REGS"))     # --regs: keep the most used variables in rbx, r12, r13, r14
UNROLL = 0          # --unroll[=N]: write loops with a few fixed repeats out as straight-line code


REG_NAMES = {0: "rax", 1: "rcx", 2: "rdx", 3: "rbx", 6: "rsi", 7: "rdi", 8: "r8", 9: "r9", 10: "r10", 11: "r11", 12: "r12", 13: "r13", 14: "r14"}
REG32 = {0: "eax", 1: "ecx", 2: "edx", 3: "ebx", 6: "esi", 7: "edi", 8: "r8d", 9: "r9d", 10: "r10d", 11: "r11d", 12: "r12d", 13: "r13d", 14: "r14d"}
ALU_RM = {"add": 0x03, "or": 0x0B, "and": 0x23, "sub": 0x2B, "xor": 0x33, "cmp": 0x3B}      # op reg, r/m
ALU_MR = {"add": 0x01, "or": 0x09, "and": 0x21, "sub": 0x29, "xor": 0x31, "cmp": 0x39}      # op r/m, reg
ALU_EXT = {"add": 0, "or": 1, "and": 4, "sub": 5, "xor": 6, "cmp": 7}                      # op r/m, imm
SHIFT_EXT = {"shl": 4, "shr": 5, "sar": 7}


def _rex(reg, rm):
    return 0x48 | ((reg >> 3) << 2) | (rm >> 3)


class Asm:
    def __init__(self):
        self.regmap = {}             # --regs: slot offset -> register number holding that variable
        self.counts = None           # --regs, first pass: slot offset -> weighted number of uses
        self.scope = None            # the function being compiled (None: the main program)
        self.callee_ok = {}          # first pass: function -> True when it may keep variables in rbx, r12-r14 (saved by its entry stub)
        self.leaf_ok = {}            # first pass: function -> True when its body makes no calls and uses no scratch registers
        self.slot_scopes = {}        # first pass: slot -> the set of scopes that use it
        self.fn_counts = {}          # first pass: function -> {slot: weighted uses}
        self.pinned = set()          # slots whose address is taken (they must stay in memory)
        self.weight_fn = lambda: 1
        self.code = bytearray()
        self.text = []
        self.labels = {}
        self.fixups = []             # (position of rel32, label, addend)
        self.strings = []            # (label, bytes)
        self.uses_rt = False
        self.label_count = 0

    # -- plumbing ------------------------------------------------------------
    def _emit(self, raw, text):
        self.code += raw
        self.text.append("    " + text)

    def new_label(self, prefix="L"):
        self.label_count += 1
        return f".{prefix}{self.label_count}"

    def label(self, name):
        self.labels[name] = len(self.code)
        self.text.append(f"{name}:")

    def _rel32(self, label, addend=0):
        self.fixups.append((len(self.code), label, addend))
        self.code += b'\0\0\0\0'

    @staticmethod
    def _target(label):
        return label

    # -- data movement --------------------------------------------------------
    def mov_rax_imm64(self, bits):
        self._emit(b'\x48\xb8' + struct.pack('<Q', bits), f"mov rax, {bits}")

    # -- variables kept in registers (--regs) ---------------------------------------
    def _use(self, d):
        """the register that holds slot d, or None.  In the counting pass this also counts the use."""
        if self.counts is not None:
            w = self.weight_fn()
            self.counts[d] = self.counts.get(d, 0) + w
            self.slot_scopes.setdefault(d, set()).add(self.scope)
            fc = self.fn_counts.setdefault(self.scope, {})
            fc[d] = fc.get(d, 0) + w
        return self.regmap.get(d)

    def _mov_rr(self, dst, src):                    # mov dst, src  (64-bit registers)
        self._emit(bytes([_rex(src, dst), 0x89, 0xc0 | (src & 7) << 3 | (dst & 7)]), f"mov {REG_NAMES[dst]}, {REG_NAMES[src]}")

    def load_rax(self, d):
        r = self._use(d)
        if r is not None:
            return self._mov_rr(0, r)
        self._emit(b'\x48\x8b\x85' + _d32(d), f"mov rax, qword ptr {_mem(d)}")

    def store_rax(self, d):
        r = self._use(d)
        if r is not None:
            return self._mov_rr(r, 0)
        self._emit(b'\x48\x89\x85' + _d32(d), f"mov qword ptr {_mem(d)}, rax")

    def store_imm_qword(self, d, imm):
        r = self._use(d)
        if r is not None:
            return self._emit(bytes([_rex(0, r), 0xc7, 0xc0 | (r & 7)]) + _d32(imm), f"mov {REG_NAMES[r]}, {imm}")
        self._emit(b'\x48\xc7\x85' + _d32(d) + _d32(imm), f"mov qword ptr {_mem(d)}, {imm}")

    def load_x(self, n, d):
        r = self._use(d)
        if r is not None:
            return self._emit(b'\x66' + bytes([_rex(n, r), 0x0f, 0x6e, 0xc0 | (n & 7) << 3 | (r & 7)]), f"movq xmm{n}, {REG_NAMES[r]}")
        self._emit(b'\xf2\x0f\x10' + bytes([0x85 | n << 3]) + _d32(d), f"movsd xmm{n}, qword ptr {_mem(d)}")

    def store_x(self, d, n):
        r = self._use(d)
        if r is not None:
            return self._emit(b'\x66' + bytes([_rex(n, r), 0x0f, 0x7e, 0xc0 | (n & 7) << 3 | (r & 7)]), f"movq {REG_NAMES[r]}, xmm{n}")
        self._emit(b'\xf2\x0f\x11' + bytes([0x85 | n << 3]) + _d32(d), f"movsd qword ptr {_mem(d)}, xmm{n}")

    def load_x_idx(self, n, d):                     # movsd xmm<n>, [rbp + rax*8 + d]   ([r15 + ...] for shared arrays)
        if isinstance(d, SharedOff):
            return self._emit(b'\xf2\x41\x0f\x10' + bytes([0x84 | n << 3, 0xc7]) + _d32(d),
                              f"movsd xmm{n}, qword ptr [r15+rax*8{int(d):+d}]")
        self._emit(b'\xf2\x0f\x10' + bytes([0x84 | n << 3, 0xc5]) + _d32(d),
                   f"movsd xmm{n}, qword ptr [rbp+rax*8{d:+d}]")

    def store_x_idx(self, d, n):
        if isinstance(d, SharedOff):
            return self._emit(b'\xf2\x41\x0f\x11' + bytes([0x84 | n << 3, 0xc7]) + _d32(d),
                              f"movsd qword ptr [r15+rax*8{int(d):+d}], xmm{n}")
        self._emit(b'\xf2\x0f\x11' + bytes([0x84 | n << 3, 0xc5]) + _d32(d),
                   f"movsd qword ptr [rbp+rax*8{d:+d}], xmm{n}")

    def movq_x_rax(self, n):
        self._emit(b'\x66\x48\x0f\x6e' + bytes([0xc0 | n << 3]), f"movq xmm{n}, rax")

    def movq_rax_x0(self):
        if self.text and self.text[-1] == "    movq xmm0, rax":          # rax already holds it
            return
        self._emit(b'\x66\x48\x0f\x7e\xc0', "movq rax, xmm0")

    def movapd_x2_x0(self):
        self._emit(b'\x66\x0f\x28\xd0', "movapd xmm2, xmm0")

    def movapd(self, dst, src):
        self._emit(b'\x66\x0f\x28' + bytes([0xc0 | dst << 3 | src]), f"movapd xmm{dst}, xmm{src}")

    def push_x0(self):
        self._emit(b'\x48\x83\xec\x08', "sub rsp, 8")
        self._emit(b'\xf2\x0f\x11\x04\x24', "movsd qword ptr [rsp], xmm0")

    def pop_x(self, n):
        self._emit(b'\xf2\x0f\x10' + bytes([0x04 | n << 3, 0x24]), f"movsd xmm{n}, qword ptr [rsp]")
        self._emit(b'\x48\x83\xc4\x08', "add rsp, 8")

    def load_x_rsp(self, n, off):                   # movsd xmm<n>, [rsp + off]
        self._emit(b'\xf2\x0f\x10' + bytes([0x84 | n << 3, 0x24]) + _d32(off), f"movsd xmm{n}, qword ptr [rsp+{off}]")

    def push_mem(self, d):
        r = self._use(d)
        if r is not None:
            return self._emit((b'\x41' if r > 7 else b'') + bytes([0x50 | (r & 7)]), f"push {REG_NAMES[r]}")
        self._emit(b'\xff\xb5' + _d32(d), f"push qword ptr {_mem(d)}")

    def pop_mem(self, d):
        r = self._use(d)
        if r is not None:
            return self._emit((b'\x41' if r > 7 else b'') + bytes([0x58 | (r & 7)]), f"pop {REG_NAMES[r]}")
        self._emit(b'\x8f\x85' + _d32(d), f"pop qword ptr {_mem(d)}")

    def add_rax_imm(self, n):
        self._emit(b'\x48\x05' + _d32(n), f"add rax, {n}")

    def btc_rax_63(self):
        self._emit(b'\x48\x0f\xba\xf8\x3f', "btc rax, 63")

    def sub_rax_imm(self, n):
        self._emit(b'\x48\x2d' + _d32(n), f"sub rax, {n}")

    # -- arithmetic -------------------------------------------------------------
    def alu(self, op, dst=0, src=1):                # addsd/subsd/mulsd/divsd xmm<dst>, xmm<src>
        code = {"addsd": 0x58, "subsd": 0x5c, "mulsd": 0x59, "divsd": 0x5e}[op]
        self._emit(b'\xf2\x0f' + bytes([code, 0xc0 | dst << 3 | src]), f"{op} xmm{dst}, xmm{src}")

    def alu_mem(self, op, d):                       # addsd/subsd/mulsd/divsd xmm0, qword ptr [variable d]
        code = {"addsd": 0x58, "subsd": 0x5c, "mulsd": 0x59, "divsd": 0x5e}[op]
        self._emit(b'\xf2\x0f' + bytes([code, 0x85]) + _d32(d), f"{op} xmm0, qword ptr {_mem(d)}")

    def sqrtsd(self):
        self._emit(b'\xf2\x0f\x51\xc0', "sqrtsd xmm0, xmm0")

    def roundsd(self, n, mode):                     # mode: 9 floor, 10 ceiling, 11 truncate
        self._emit(b'\x66\x0f\x3a\x0b' + bytes([0xc0 | n << 3 | n, mode]), f"roundsd xmm{n}, xmm{n}, {mode}")

    def btr_rax_63(self):
        self._emit(b'\x48\x0f\xba\xf0\x3f', "btr rax, 63")

    def ucomisd(self, a, b):                        # ucomisd xmm<a>, xmm<b>
        self._emit(b'\x66\x0f\x2e' + bytes([0xc0 | a << 3 | b]), f"ucomisd xmm{a}, xmm{b}")

    def cvttsd2si_rax_x0(self):
        self._emit(b'\xf2\x48\x0f\x2c\xc0', "cvttsd2si rax, xmm0")

    def cvttsd2si_rdi_x0(self):
        self._emit(b'\xf2\x48\x0f\x2c\xf8', "cvttsd2si rdi, xmm0")

    def cvtsi2sd_x0_rax(self):
        self._emit(b'\xf2\x48\x0f\x2a\xc0', "cvtsi2sd xmm0, rax")

    def cmp_rax_imm(self, n):
        self._emit(b'\x48\x3d' + _d32(n), f"cmp rax, {n}")


    # -- general 64-bit integer instructions (Zoomy 6.3): registers are numbers (REG_NAMES), a memory operand is a variable
    #    slot d (rbp-relative) or a SharedOff (r15-relative), a source is ('imm', v) | ('reg', r) | ('mem', d)
    @staticmethod
    def _ms(d):
        return f"[r15+{int(d)}]" if isinstance(d, SharedOff) else _mem(d)

    @staticmethod
    def _mm(reg, d, rex_w=True):
        """(rex, modrm+disp32) of  [rbp+d]  /  [r15+d]  with `reg` in the modrm reg field"""
        if isinstance(d, SharedOff):
            return (0x48 if rex_w else 0x40) | (reg >> 3) << 2 | 1, bytes([0x80 | (reg & 7) << 3 | 7]) + _d32(int(d))
        return (0x48 if rex_w else 0x40) | (reg >> 3) << 2, bytes([0x80 | (reg & 7) << 3 | 5]) + _d32(d)

    def src(self, d):
        """a variable slot as a source operand (a register when --regs put it in one); counts the use"""
        r = self._use(d)
        return ("reg", r) if r is not None else ("mem", d)

    def get(self, reg, d):
        """reg = variable slot d"""
        r = self._use(d)
        if r is not None:
            if r != reg:
                self._mov_rr(reg, r)
            return
        lp = getattr(self, "last_put", None)
        if lp and lp[0] == len(self.text) and lp[1] == d:      # the variable was stored a moment ago: reuse the register
            if lp[2] != reg:
                self._mov_rr(reg, lp[2])
            return
        rex, m = self._mm(reg, d)
        self._emit(bytes([rex, 0x8b]) + m, f"mov {REG_NAMES[reg]}, qword ptr {self._ms(d)}")

    def put(self, d, reg):
        """variable slot d = reg"""
        r = self._use(d)
        if r is not None:
            if r != reg:
                self._mov_rr(r, reg)
            return
        rex, m = self._mm(reg, d)
        self._emit(bytes([rex, 0x89]) + m, f"mov qword ptr {self._ms(d)}, {REG_NAMES[reg]}")
        self.last_put = (len(self.text), d, reg)

    def mov_var(self, dst, srcd):
        """variable slot dst = variable slot srcd"""
        rs, rd = self._use(srcd), self._use(dst)
        if rd is not None and rs is not None:
            if rd != rs:
                self._mov_rr(rd, rs)
        elif rd is not None:
            rex, m = self._mm(rd, srcd)
            self._emit(bytes([rex, 0x8b]) + m, f"mov {REG_NAMES[rd]}, qword ptr {self._ms(srcd)}")
        elif rs is not None:
            rex, m = self._mm(rs, dst)
            self._emit(bytes([rex, 0x89]) + m, f"mov qword ptr {self._ms(dst)}, {REG_NAMES[rs]}")
        else:
            self.get(0, srcd)
            self.put(dst, 0)

    def mov_ri(self, reg, v):
        """reg = constant (xor for 0: clobbers the flags)"""
        v &= (1 << 64) - 1
        if v == 0:
            self._emit((b'\x45' if reg > 7 else b'') + bytes([0x31, 0xc0 | (reg & 7) << 3 | (reg & 7)]), f"xor {REG32[reg]}, {REG32[reg]}")
        elif v < (1 << 32):
            self._emit((b'\x41' if reg > 7 else b'') + bytes([0xb8 | (reg & 7)]) + struct.pack('<I', v), f"mov {REG32[reg]}, {v}")
        elif v >= (1 << 64) - (1 << 31):
            sv = v - (1 << 64)
            self._emit(bytes([_rex(0, reg), 0xc7, 0xc0 | (reg & 7)]) + _d32(sv), f"mov {REG_NAMES[reg]}, {sv}")
        else:
            self._emit(bytes([_rex(0, reg), 0xb8 | (reg & 7)]) + struct.pack('<Q', v), f"mov {REG_NAMES[reg]}, {v}")

    def ialu(self, op, dst, src):
        """op dst, src   (add sub and or xor cmp)"""
        kind, v = src
        D = REG_NAMES[dst]
        if kind == "imm":
            if -128 <= v < 128:
                self._emit(bytes([_rex(0, dst), 0x83, 0xc0 | ALU_EXT[op] << 3 | (dst & 7), v & 0xff]), f"{op} {D}, {v}")
            else:
                self._emit(bytes([_rex(0, dst), 0x81, 0xc0 | ALU_EXT[op] << 3 | (dst & 7)]) + _d32(v), f"{op} {D}, {v}")
        elif kind == "reg":
            self._emit(bytes([_rex(dst, v), ALU_RM[op], 0xc0 | (dst & 7) << 3 | (v & 7)]), f"{op} {D}, {REG_NAMES[v]}")
        else:
            rex, m = self._mm(dst, v)
            self._emit(bytes([rex, ALU_RM[op]]) + m, f"{op} {D}, qword ptr {self._ms(v)}")

    def ialu_mem(self, op, d, src):
        """op qword ptr [d], src   with src ('imm', v) or ('reg', r)"""
        kind, v = src
        if kind == "imm":
            rex, m = self._mm(ALU_EXT[op], d)
            if -128 <= v < 128:
                self._emit(bytes([rex, 0x83]) + m + bytes([v & 0xff]), f"{op} qword ptr {self._ms(d)}, {v}")
            else:
                self._emit(bytes([rex, 0x81]) + m + _d32(v), f"{op} qword ptr {self._ms(d)}, {v}")
        else:
            rex, m = self._mm(v, d)
            self._emit(bytes([rex, ALU_MR[op]]) + m, f"{op} qword ptr {self._ms(d)}, {REG_NAMES[v]}")

    def ivar(self, op, d, src):
        """op <variable d>, src   (the variable may live in a register); src is ('imm', v) | ('reg', r) | ('mem', d2)"""
        r = self._use(d)
        if r is not None:
            return self.ialu(op, r, src)
        if src[0] == "mem":
            self.get(0, src[1])
            src = ("reg", 0)
        self.ialu_mem(op, d, src)

    def imul(self, dst, src):
        kind, v = src
        D = REG_NAMES[dst]
        if kind == "imm":
            if -128 <= v < 128:
                self._emit(bytes([_rex(dst, dst), 0x6b, 0xc0 | (dst & 7) << 3 | (dst & 7), v & 0xff]), f"imul {D}, {D}, {v}")
            else:
                self._emit(bytes([_rex(dst, dst), 0x69, 0xc0 | (dst & 7) << 3 | (dst & 7)]) + _d32(v), f"imul {D}, {D}, {v}")
        elif kind == "reg":
            self._emit(bytes([_rex(dst, v), 0x0f, 0xaf, 0xc0 | (dst & 7) << 3 | (v & 7)]), f"imul {D}, {REG_NAMES[v]}")
        else:
            rex, m = self._mm(dst, v)
            self._emit(bytes([rex, 0x0f, 0xaf]) + m, f"imul {D}, qword ptr {self._ms(v)}")

    def shift_ri(self, op, reg, n):
        self._emit(bytes([_rex(0, reg), 0xc1, 0xc0 | SHIFT_EXT[op] << 3 | (reg & 7), n]), f"{op} {REG_NAMES[reg]}, {n}")

    def neg_r(self, reg):
        self._emit(bytes([_rex(0, reg), 0xf7, 0xd8 | (reg & 7)]), f"neg {REG_NAMES[reg]}")

    def mem_store_imm(self, d, v):
        rex, m = self._mm(0, d)
        self._emit(bytes([rex, 0xc7]) + m + _d32(v), f"mov qword ptr {self._ms(d)}, {v}")

    def mem_load(self, reg, d):
        rex, m = self._mm(reg, d)
        self._emit(bytes([rex, 0x8b]) + m, f"mov {REG_NAMES[reg]}, qword ptr {self._ms(d)}")

    def mem_store(self, d, reg):
        rex, m = self._mm(reg, d)
        self._emit(bytes([rex, 0x89]) + m, f"mov qword ptr {self._ms(d)}, {REG_NAMES[reg]}")

    @staticmethod
    def _ix(reg, d):
        """(rex, modrm+sib+disp32) of  [base + rax*8 + d]"""
        if isinstance(d, SharedOff):
            return 0x48 | (reg >> 3) << 2 | 1, bytes([0x84 | (reg & 7) << 3, 0xc7]) + _d32(int(d))
        return 0x48 | (reg >> 3) << 2, bytes([0x84 | (reg & 7) << 3, 0xc5]) + _d32(d)

    @staticmethod
    def _ixs(d):
        return f"[r15+rax*8+{int(d)}]" if isinstance(d, SharedOff) else f"[rbp+rax*8{d:+d}]"

    def idx_load(self, reg, d):                    # reg = array element at index rax
        rex, m = self._ix(reg, d)
        self._emit(bytes([rex, 0x8b]) + m, f"mov {REG_NAMES[reg]}, qword ptr {self._ixs(d)}")

    def idx_store(self, d, reg):                   # array element at index rax = reg
        rex, m = self._ix(reg, d)
        self._emit(bytes([rex, 0x89]) + m, f"mov qword ptr {self._ixs(d)}, {REG_NAMES[reg]}")

    def idx_store_imm(self, d, v):
        rex, m = self._ix(0, d)
        self._emit(bytes([rex, 0xc7]) + m + _d32(v), f"mov qword ptr {self._ixs(d)}, {v}")

    def idx_alu(self, op, d, src):                 # op [array element at index rax], src   (src: imm or reg)
        kind, v = src
        if kind == "imm":
            rex, m = self._ix(ALU_EXT[op], d)
            if -128 <= v < 128:
                self._emit(bytes([rex, 0x83]) + m + bytes([v & 0xff]), f"{op} qword ptr {self._ixs(d)}, {v}")
            else:
                self._emit(bytes([rex, 0x81]) + m + _d32(v), f"{op} qword ptr {self._ixs(d)}, {v}")
        else:
            rex, m = self._ix(v, d)
            self._emit(bytes([rex, ALU_MR[op]]) + m, f"{op} qword ptr {self._ixs(d)}, {REG_NAMES[v]}")

    def push_r(self, reg):
        self._emit((b'\x41' if reg > 7 else b'') + bytes([0x50 | (reg & 7)]), f"push {REG_NAMES[reg]}")

    def pop_r(self, reg):
        self._emit((b'\x41' if reg > 7 else b'') + bytes([0x58 | (reg & 7)]), f"pop {REG_NAMES[reg]}")

    def load_rsp(self, reg, off):                  # reg = [rsp + off]
        self._emit(bytes([_rex(reg, 0), 0x8b, 0x84 | (reg & 7) << 3, 0x24]) + _d32(off), f"mov {REG_NAMES[reg]}, qword ptr [rsp+{off}]")

    def test_rr(self, r):
        self._emit(bytes([_rex(r, r), 0x85, 0xc0 | (r & 7) << 3 | (r & 7)]), f"test {REG_NAMES[r]}, {REG_NAMES[r]}")

    # -- workers (Zoomy 5.5): shared memory and processes ----------------------------------
    W_OPS = {
        "xor edi, edi": b'\x31\xff', "mov edx, 3": b'\xba\x03\x00\x00\x00', "mov r10d, 33": b'\x41\xba\x21\x00\x00\x00',
        "mov r8, -1": b'\x49\xc7\xc0\xff\xff\xff\xff', "xor r9d, r9d": b'\x45\x31\xc9', "mov r15, rax": b'\x49\x89\xc7',
        "mov esi, 9": b'\xbe\x09\x00\x00\x00', "mov rdi, -1": b'\x48\xc7\xc7\xff\xff\xff\xff',
        "mov rdi, rax": b'\x48\x89\xc7', "mov rsi, rax": b'\x48\x89\xc6', "xor esi, esi": b'\x31\xf6', "xor edx, edx": b'\x31\xd2', "xor r10d, r10d": b'\x45\x31\xd2',
    }

    def w(self, text):
        self._emit(self.W_OPS[text], text)

    def shared_prologue(self):
        """mmap(0, @SHARED@, READ|WRITE, SHARED|ANONYMOUS, -1, 0) -> r15 (every forked worker sees the same pages)"""
        self.w("xor edi, edi")
        self.code += b'\xbe'
        self.shared_patch = len(self.code)
        self.code += b'\0\0\0\0'
        self.text.append("    mov esi, @SHARED@")
        self.w("mov edx, 3")
        self.w("mov r10d, 33")
        self.w("mov r8, -1")
        self.w("xor r9d, r9d")
        self.mov_eax(9)
        self.syscall()
        self.w("mov r15, rax")

    def patch_shared(self, nbytes):
        if getattr(self, "shared_patch", None) is not None:
            self.code[self.shared_patch:self.shared_patch + 4] = struct.pack('<I', nbytes)
            self.text = [ln.replace("@SHARED@", str(nbytes)) for ln in self.text]

    def mov_esi(self, v):
        self._emit(b'\xbe' + struct.pack('<I', v), f"mov esi, {v}")

    # -- integer mode (Zoomy 6.1): values travel as raw 64-bit patterns in xmm0/xmm1 and are worked out in rax/rcx --------
    I_OPS = {
        "movq rcx, xmm1": b'\x66\x48\x0f\x7e\xc9', "movq rdi, xmm0": b'\x66\x48\x0f\x7e\xc7',
        "add rax, rcx": b'\x48\x01\xc8', "sub rax, rcx": b'\x48\x29\xc8', "imul rax, rcx": b'\x48\x0f\xaf\xc1',
        "cqo": b'\x48\x99', "div rcx": b'\x48\xf7\xf1', "xor edx, edx": b'\x31\xd2', "idiv rcx": b'\x48\xf7\xf9', "neg rax": b'\x48\xf7\xd8', "not rax": b'\x48\xf7\xd0',
        "and rax, rcx": b'\x48\x21\xc8', "or rax, rcx": b'\x48\x09\xc8', "xor rax, rcx": b'\x48\x31\xc8',
        "shl rax, cl": b'\x48\xd3\xe0', "shr rax, cl": b'\x48\xd3\xe8', "sar rax, cl": b'\x48\xd3\xf8',
        "rol rax, cl": b'\x48\xd3\xc0', "ror rax, cl": b'\x48\xd3\xc8',
        "popcnt rax, rax": b'\xf3\x48\x0f\xb8\xc0', "tzcnt rax, rax": b'\xf3\x48\x0f\xbc\xc0',
        "lzcnt rax, rax": b'\xf3\x48\x0f\xbd\xc0', "pext rax, rax, rcx": b'\xc4\xe2\xfa\xf5\xc1', "pdep rax, rax, rcx": b'\xc4\xe2\xfb\xf5\xc1', "bswap rax": b'\x48\x0f\xc8',
        "mov rdx, rax": b'\x48\x89\xc2', "mov rax, rdx": b'\x48\x89\xd0', "mov rcx, rax": b'\x48\x89\xc1',
        "cmp rax, rcx": b'\x48\x39\xc8', "test rax, rax": b'\x48\x85\xc0', "test rcx, rcx": b'\x48\x85\xc9',
        "test rdx, rdx": b'\x48\x85\xd2', "not rcx": b'\x48\xf7\xd1', "neg rdx": b'\x48\xf7\xda',
        "mov edx, 1": b'\xba\x01\x00\x00\x00', "shl rdx, cl": b'\x48\xd3\xe2', "or rax, rdx": b'\x48\x09\xd0',
        "not rdx": b'\x48\xf7\xd2', "and rax, rdx": b'\x48\x21\xd0', "xor rax, rdx": b'\x48\x31\xd0',
        "lea rdx, [rax-1]": b'\x48\x8d\x50\xff', "add rdx, rcx": b'\x48\x01\xca', "add rax, rdx": b'\x48\x01\xd0',
        "xor rax, rcx": b'\x48\x31\xc8', "cmp rcx, -1": b'\x48\x83\xf9\xff', "cmp rcx, 63": b'\x48\x83\xf9\x3f',
        "xor eax, eax": b'\x31\xc0',
    }

    def i(self, text):
        """one fixed integer instruction (see I_OPS)"""
        self._emit(self.I_OPS[text], text)

    def load_rcx(self, d):
        r = self._use(d)
        if r is not None:
            return self._mov_rr(1, r)
        self._emit(b'\x48\x8b\x8d' + _d32(d), f"mov rcx, qword ptr {_mem(d)}")

    def load_rdi(self, d):
        r = self._use(d)
        if r is not None:
            return self._mov_rr(7, r)
        self._emit(b'\x48\x8b\xbd' + _d32(d), f"mov rdi, qword ptr {_mem(d)}")

    def load_rdx(self, d):
        r = self._use(d)
        if r is not None:
            return self._mov_rr(2, r)
        self._emit(b'\x48\x8b\x95' + _d32(d), f"mov rdx, qword ptr {_mem(d)}")

    def store_rdx(self, d):
        r = self._use(d)
        if r is not None:
            return self._mov_rr(r, 2)
        self._emit(b'\x48\x89\x95' + _d32(d), f"mov qword ptr {_mem(d)}, rdx")

    # -- control flow -------------------------------------------------------------
    def jump(self, kind, label, addend=0):
        if JCC[kind] is None:
            self._emit_jump(b'\xe9', f"jmp {self._lbl(label, addend)}", label, addend)
        else:
            self._emit_jump(b'\x0f' + bytes([JCC[kind]]), f"{kind} {self._lbl(label, addend)}", label, addend)

    def call(self, label, addend=0):
        self._emit_jump(b'\xe8', f"call {self._lbl(label, addend)}", label, addend)

    @staticmethod
    def _lbl(label, addend):
        return label if not addend else f"{label}+{addend}"

    def _emit_jump(self, opcode, text, label, addend):
        self.code += opcode
        self._rel32(label, addend)
        self.text.append("    " + text)

    def ret(self):
        self._emit(b'\xc3', "ret")

    def ret_imm(self, n):                           # ret n : also drops n bytes of arguments
        self._emit(b'\xc2' + struct.pack('<H', n), f"ret {n}")

    def call_rt(self, entry):
        self.uses_rt = True
        self.call("rt", entry)

    def jump_rt(self, kind, entry):
        self.uses_rt = True
        self.jump(kind, "rt", entry)

    # -- system calls / addresses ---------------------------------------------------
    def syscall(self):
        self._emit(b'\x0f\x05', "syscall")

    def mov_eax(self, v):
        self._emit(b'\xb8' + struct.pack('<I', v), f"mov eax, {v}")

    def mov_edi(self, v):
        self._emit(b'\xbf' + struct.pack('<I', v), f"mov edi, {v}")

    def mov_edx(self, v):
        self._emit(b'\xba' + struct.pack('<I', v), f"mov edx, {v}")

    def xor_edi(self):
        self._emit(b'\x31\xff', "xor edi, edi")

    def lea_rdi_var(self, d):
        self.pinned.add(d)
        self._emit(b'\x48\x8d\xbd' + _d32(d), f"lea rdi, {_mem(d)}")

    def lea_rsi_var(self, d):
        self.pinned.add(d)
        self._emit(b'\x48\x8d\xb5' + _d32(d), f"lea rsi, {_mem(d)}")

    def lea_rdi_label(self, label):
        self.code += b'\x48\x8d\x3d'
        self._rel32(label)
        self.text.append(f"    lea rdi, [rip+{label}]")

    def lea_rsi_label(self, label):
        self.code += b'\x48\x8d\x35'
        self._rel32(label)
        self.text.append(f"    lea rsi, [rip+{label}]")

    def string(self, data):
        label = f".S{len(self.strings)}"
        self.strings.append((label, data))
        return label

    def align_call_extern(self, name):               # gcc mode only: keep the C stack 16-byte aligned
        self.text.append("    mov r12, rsp")
        self.text.append("    and rsp, -16")
        self.text.append(f"    call {name}")
        self.text.append("    mov rsp, r12")

    # -- prologue (patched once the frame size is known) ----------------------------
    def prologue(self):
        self._emit(b'\x55', "push rbp")
        self._emit(b'\x48\x89\xe5', "mov rbp, rsp")
        self.code += b'\x48\x81\xec'
        self.frame_patch_1 = len(self.code)
        self.code += b'\0\0\0\0'
        self.text.append("    sub rsp, @FRAME@")
        self._emit(b'\x48\x89\xe7', "mov rdi, rsp")
        self._emit(b'\x31\xc0', "xor eax, eax")
        self.code += b'\xb9'
        self.frame_patch_2 = len(self.code)
        self.code += b'\0\0\0\0'
        self.text.append("    mov ecx, @QWORDS@")
        self._emit(b'\xf3\x48\xab', "rep stosq")

    def patch_frame(self, frame):
        self.code[self.frame_patch_1:self.frame_patch_1 + 4] = struct.pack('<I', frame)
        self.code[self.frame_patch_2:self.frame_patch_2 + 4] = struct.pack('<I', frame // 8)
        self.text = [ln.replace("@FRAME@", str(frame)).replace("@QWORDS@", str(frame // 8)) for ln in self.text]


# =============================================================================
# The runtime blob (see runtime/zoomy_rt.asm; regenerate with tools/build_runtime.py)
# =============================================================================
# --- BEGIN RUNTIME BLOB ---
RT_BLOB_HEX = (
    "e964000000e93d030000e902030000e942040000e990040000e94c050000e999050000e9de050000e91b060000e97f06"
    "0000e940070000e9dc070000e90f080000e956080000e966090000e98c080000e924090000e9a9060000e9e0060000e9"
    "8e080000e9d6080000534154415541564883ec504c8d6c2450488d3c24660f2ec00f8a8901000066480f7ec04889c148"
    "c1e93f480fbaf03f66480f6ec048ba000000000000f07f4839d00f846c0100004885c00f847a01000048ba00003426f5"
    "6b0c434839d0737248ba8dedb5a0f7c6b03e4839d072634885c97406c6072d48ffc7f2480f2cc0f2480f2ac8660f28d0"
    "f20f5cd148ba0000000080842e4166480f6edaf20f59d3f2480f2dd24881fa40420f00720a48ffc04881ea40420f0049"
    "89d6e8340100004d85f60f8409010000e853010000e9ff0000004885c97406c6072d48ffc74531e448ba000000000000"
    "244066480f6eda48ba000000000000f03f66480f6ee2660f2ec37209f20f5ec349ffc4ebf1660f2ec47309f20f59c349"
    "ffccebf1f2480f2cc0f2480f2ac8660f28d0f20f5cd148ba0000000080842e4166480f6eeaf20f59d5f2480f2dd24881"
    "fa40420f00720a48ffc04881ea40420f004883f80a7208b80100000049ffc44989d6e8840000004d85f67405e8a70000"
    "00c6076548ffc74d85e47805c6072beb06c6072d49f7dc48ffc74c89e04883f80a7306c6073048ffc7e84d000000eb29"
    "c7076e616e004883c703eb1d4885c97406c6072d48ffc7c707696e66004883c703eb06c6073048ffc7498d75b04889fa"
    "4829f2b801000000bf010000000f054883c450415e415d415c5bc34d89e841b90a00000031d249f7f180c23049ffc841"
    "88104885c075ed418a00880749ffc048ffc74d39e872f0c3c6072e48ffc74c89f041b9a086010041ba0600000031d249"
    "f7f10430880748ffc74889d14c89c831d241bb0a00000049f7f34989c14889c841ffca75d8807fff30750548ffcfebf5"
    "c3488b074883f8ff740848c707ffffffffc3574883ec1031c0488b7ff0488d3424ba010000000f054883f80175060fb6"
    "0424eb0748c7c0ffffffff4883c4105fc3534889fb4889dfe8b4ffffff4883f8ff741c4883f82074ec488d48f74883f9"
    "0476e2f2480f2ac0b8010000005bc3660f57c031c05bc35341544155415641574889fb4889dfe876ffffff4883f8ff0f"
    "84e10000004883f82074e8488d48f74883f90476de4531e44883f82d750841bc01000000eb064883f82b75084889dfe8"
    "3dffffff660f57c048ba000000000000244066480f6eca4531ed4531f64531ff4883f8ff74454889c14883e9304883f9"
    "097722f20f59c1f2480f2ad1f20f58c249ffc54d85ff740349ffc64889dfe8eefeffffebcb4883f82e750d4d85ff7508"
    "41bf01000000ebe34889034d85ed743f48ba000000000000f03f66480f6eda4c89f14885c97409f20f59d948ffc9ebf2"
    "f20f5ec34d85e4740f66480f7ec0480fbaf83f66480f6ec0b801000000eb0d48c703ffffffff660f57c031c0415f415e"
    "415d415c5bc3b801000000bf02000000488d3513000000ba2f0000000f05bfff000000b83c0000000f057a6f6f6d793a"
    "2072756e74696d65206572726f723a20617272617920696e646578206f7574206f662072616e67650a660f2ec90f8a82"
    "000000660f28d148b8ffffffffffffff7f66480f7ed14821c148ba000000000000e0434839d1735d66480f6ed1f2480f"
    "2cc2f2480f2ad8660f2eda754848ba000000000000f03f66480f6ed24885c07411a8017404f20f59d0f20f59c048d1e8"
    "ebea66480f7ec94885c9791448ba000000000000f03f66480f6ec2f20f5ec2c3660f28c2c34883ec10f20f110c24dd04"
    "24f20f110424dd0424d9f1d9c0d9fcdce9d9c9d9f0d9e8dec1d9fdddd9dd1c24f20f1004244883c410c3488d350a0000"
    "00ba41000000e9850400007a6f6f6d793a2072756e74696d65206572726f723a20612027666f7227206c6f6f70206e65"
    "656473206120737465702074686174206973206e6f74207a65726f0a488d350a000000ba39000000e9330400007a6f6f"
    "6d793a2072756e74696d65206572726f723a20746869732027666f7227206c6f6f7020776f756c642072756e20746f6f"
    "206c6f6e670a488d350a000000ba31000000e9e90300007a6f6f6d793a2072756e74696d65206572726f723a20612063"
    "6f756e742063616e6e6f74206265206e656761746976650a488d350a000000ba58000000e9a70300007a6f6f6d793a20"
    "72756e74696d65206572726f723a20746f6f206d616e79206e65737465642063616c6c732028612066756e6374696f6e"
    "2063616c6c7320697473656c6620776974686f75742073746f7070696e673f290a534883ec20488d7424204889c34885"
    "c0790348f7d841b80a00000031d249f7f080c23048ffce88164885c075ee4885db790648ffcec6062d488d5424204829"
    "f2b801000000bf010000000f054883c4205bc3534883ec20488d74242041b80a00000031d249f7f080c23048ffce8816"
    "4885c075ee488d5424204829f2b801000000bf010000000f054883c4205bc34989c031c0b90100000048c1e13e4c39c1"
    "760748c1e90275f5c3488d14084939d0720b4929d048d1e84801c8eb0348d1e848c1e90275e3c3534154415541564889"
    "fb4889dfe848fbffff4883f8ff747d4883f82074ec488d48f74883f90476e24531e44883f82d750841bc01000000eb06"
    "4883f82b75084889dfe813fbffff4531ed4531f64883f8ff74244889c14883e9304883f90977144d6bf60a4901ce49ff"
    "c54889dfe8e8faffffebd94889034d85ed74124d85e4740349f7de4c89f0ba01000000eb0b48c703ffffffff31c031d2"
    "415e415d415c5bc3488d350a000000ba27000000e9d70100007a6f6f6d793a2072756e74696d65206572726f723a2064"
    "69766973696f6e206279207a65726f0a4885c97820ba010000004885c97412f6c1017404480fafd0480fafc048d1e9eb"
    "e94889d0c34883f801741b4883f8ff750df6c101741048c7c0ffffffffc34885c0748531c0c3b801000000c34885c07e"
    "384989c0f2480f2ac0f20f51c0f2480f2cc84889c8480fafc04c39c0760548ffc9ebef488d4101480fafc04c39c07705"
    "48ffc1ebee4889c8c331c0c3e8f0f9ffff4883f8ff7406ba01000000c331c031d2c34881ec88000000b8cc00000031ff"
    "be800000004889e20f0531c94885c07e1948c1e80331d24839c27d0ef3480fb834d44801f148ffc2ebed4889c84885c0"
    "7505b8010000004881c488000000c34881ec080100004889e731c9488b04ce88040f84c0741048ffc14881f9ff000000"
    "72e9c6040f0031f631d2b8020000000f054881c408010000c34883ec10b8e4000000bf010000004889e60f05488b4424"
    "0831d2b940420f0048f7f14889c1488b04244869c0e80300004801c84883c410c3488d3507000000ba41000000eb417a"
    "6f6f6d793a2072756e74696d65206572726f723a2061207368696674206f7220626974206e756d626572206d75737420"
    "62652066726f6d203020746f2036330ab801000000bf020000000f05bfff000000b83c0000000f05"
)
# --- END RUNTIME BLOB ---


def runtime_blob():
    if not RT_BLOB_HEX:
        raise ZoomyError("this copy of zoomy.py has no embedded runtime; run tools/build_runtime.py")
    return bytes.fromhex(RT_BLOB_HEX)


# =============================================================================
# The compiler
# =============================================================================
MAX_FRAME_BYTES = 4 * 1024 * 1024
PB_SLOT = 0          # slot 0 holds the stdin push-back byte for the runtime
CH_SLOT = 1          # slot 1 is scratch for `print char`
FD_SLOT = 2          # slot 2 holds the file that `read` takes input from (0 = standard input); rt_getc reads [pushback - 16]


class Compiler:
    def __init__(self, main_file):
        self.asm = Asm()
        self.main_dir = os.path.dirname(os.path.abspath(main_file))
        self.included = set()
        self.routines = {}           # name -> Node
        self.externs = set()
        self.actions = []
        self.vars = {}               # name -> displacement
        self.arrays = {}             # name -> (base displacement, size)
        self.slots = 3               # slots 0, 1 and 2 are hidden
        self.sh_slots = 0            # slots of the memory shared between workers
        self.compiled = set()
        self.pending = []
        self.reads = {}              # name -> (file, line) of first read
        self.writes = {"input_ok"}
        self.warnings = []
        self.check_only = False

    # -- program structure --------------------------------------------------------
    def load(self, nodes, file_dir):
        """Collect routines / actions / externs from a top-level node list (resolving includes)."""
        for node in nodes:
            if node.kind == "routine":
                name = node.text.split(None, 1)[1].rstrip(':').strip() if ' ' in node.text else ""
                if not _IDENT_RE.fullmatch(name):
                    raise ZoomyError("routine needs a name, e.g. 'routine double_it:'", node.file, node.line)
                if name in self.routines:
                    prev = self.routines[name]
                    raise ZoomyError(f"routine '{name}' is already defined at {prev.file}:{prev.line}", node.file, node.line)
                self.routines[name] = node
            elif node.kind == "action":
                self.actions.append(node)
            elif node.kind == "simple":
                name, m = match_statement(node.text)
                if name == "extern":
                    self.externs.add(m.group(1))
                elif name == "include":
                    self._include(m.group(1).strip(), node, file_dir)
                else:
                    raise ZoomyError("statements must be inside an 'action' or 'routine' block", node.file, node.line)
            else:
                raise ZoomyError("'if' / 'while' must be inside an 'action' or 'routine' block", node.file, node.line)

    def _include(self, spec, node, file_dir):
        m = re.fullmatch(rf"({IDENT})'s{_S}({IDENT})", spec)
        if m:
            rel = f"{m.group(1)}/{m.group(2)}"
        else:
            m = re.fullmatch(r"([\w./]+)", spec)
            if not m:
                raise ZoomyError(f"cannot understand include '{spec}'", node.file, node.line)
            rel = m.group(1).replace('.', '/')
        path = resolve_lib([file_dir, self.main_dir, os.path.dirname(os.path.abspath(__file__))], rel)
        if path is None:
            raise ZoomyError(f"cannot find library '{rel}' (looked for {rel}.zmy and {rel}.zmy.txt next to your program)",
                             node.file, node.line)
        if path in self.included:
            return
        self.included.add(path)
        with open(path, encoding="utf-8") as f:
            nodes = parse_source(f.read(), path)
        self.load(nodes, os.path.dirname(path))

    # -- variables ------------------------------------------------------------------
    def _check_name(self, name, node):
        if name.startswith("__"):
            raise ZoomyError(f"names starting with '__' are reserved ('{name}')", node.file, node.line)

    def var(self, name, node, write=False):
        self._check_name(name, node)
        if name in self.arrays:
            raise ZoomyError(f"'{name}' is an array; use 'load from' / 'store ... in' to access it", node.file, node.line)
        if name not in self.vars:
            self.vars[name] = -8 * (self.slots + 1)
            self.slots += 1
            self._check_frame(node)
        if write:
            self.writes.add(name)
        else:
            self.reads.setdefault(name, (node.file, node.line))
        return self.vars[name]

    def array(self, name, node):
        if name not in self.arrays:
            raise ZoomyError(f"array '{name}' is used before 'allocate array {name} with N slots'", node.file, node.line)
        return self.arrays[name]

    def allocate(self, name, size, node, shared=False):
        self._check_name(name, node)
        if size < 1:
            raise ZoomyError("an array needs at least 1 slot", node.file, node.line)
        if name in self.vars:
            raise ZoomyError(f"'{name}' is already used as a plain variable", node.file, node.line)
        if name in self.arrays:
            if self.arrays[name][1] != size:
                raise ZoomyError(f"array '{name}' was already allocated with {self.arrays[name][1]} slots", node.file, node.line)
            return
        if shared:
            self.arrays[name] = (SharedOff(8 * self.sh_slots), size)
            self.sh_slots += size
            if self.sh_slots * 8 > (2 << 30):
                raise ZoomyError("the shared arrays need more than 2 GB", node.file, node.line)
            return
        self.slots += size
        self.arrays[name] = (-8 * self.slots, size)
        self._check_frame(node)

    def _check_frame(self, node):
        if self.slots * 8 > MAX_FRAME_BYTES:
            raise ZoomyError("the program's variables and arrays need more than 4 MB of stack", node.file, node.line)

    def hidden(self, slot):
        return -8 * (slot + 1)

    # -- operands ---------------------------------------------------------------------
    def load_operand(self, reg, opd, node):
        """xmm<reg> = literal or variable (may use rax as scratch)."""
        if is_literal(opd):
            self.asm.mov_rax_imm64(f64_bits(literal_value(opd)))
            self.asm.movq_x_rax(reg)
        else:
            self.asm.load_x(reg, self.var(opd, node))

    # -- statements ------------------------------------------------------------------
    def statement(self, node):
        a = self.asm
        name, m = match_statement(node.text)
        if name is None:
            raise ZoomyError(f"cannot understand: {node.text}", node.file, node.line)
        g = m.groups()

        if name == "alloc":
            self.allocate(g[0], int(g[1]), node)
        elif name == "store":
            val, arr, idx = g
            base, size = self.array(arr, node)
            self.load_operand(1, val, node)
            self._index(idx, size, node)
            a.store_x_idx(base, 1)
        elif name == "load":
            arr, idx, dst = g
            base, size = self.array(arr, node)
            self._index(idx, size, node)
            a.load_x_idx(0, base)
            a.store_x(self.var(dst, node, write=True), 0)
        elif name == "set":
            dst, src = g
            if is_literal(src):
                a.mov_rax_imm64(f64_bits(literal_value(src)))
                a.store_rax(self.var(dst, node, write=True))
            else:
                a.load_rax(self.var(src, node))
                a.store_rax(self.var(dst, node, write=True))
        elif name in ("mul", "div", "add", "sub"):
            if name in ("mul", "div"):
                dst, src = g
            else:
                src, dst = g
            op = {"mul": "mulsd", "div": "divsd", "add": "addsd", "sub": "subsd"}[name]
            self.load_operand(1, src, node)
            d = self.var(dst, node)
            self.writes.add(dst)
            a.load_x(0, d)
            a.alu(op)
            a.store_x(d, 0)
        elif name == "rem":
            x, y, dst = g
            self.load_operand(0, x, node)
            self.load_operand(1, y, node)
            a.movapd_x2_x0()
            a.alu("divsd", 2, 1)
            a.roundsd(2, 11)
            a.alu("mulsd", 2, 1)
            a.alu("subsd", 0, 2)
            a.store_x(self.var(dst, node, write=True), 0)
        elif name == "unary":
            kind, src, dst = g
            kind = re.sub(r"\s+", " ", kind)
            self.load_operand(0, src, node)
            if kind == "square root":
                a.sqrtsd()
            elif kind == "absolute value":
                a.movq_rax_x0()
                a.btr_rax_63()
                a.movq_x_rax(0)
            else:
                a.roundsd(0, 9 if kind == "floor" else 10)
            a.store_x(self.var(dst, node, write=True), 0)
        elif name in ("read", "readchar"):
            dst = g[0]
            a.lea_rdi_var(self.hidden(PB_SLOT))
            a.call_rt(RT_READ if name == "read" else RT_READCHAR)
            a.store_x(self.var(dst, node, write=True), 0)
            a.cvtsi2sd_x0_rax()                       # eax = 1 (ok) or 0 (end of input / not a number)
            a.store_x(self.var("input_ok", node, write=True), 0)
        elif name == "print":
            self._print(g[0], g[1], node)
        elif name == "finish":
            if g[0] is None:
                a.xor_edi()
            else:
                self.load_operand(0, g[0], node)
                a.cvttsd2si_rdi_x0()
            a.mov_eax(60)
            a.syscall()
        elif name == "run":
            rname = g[0]
            if rname not in self.routines:
                hint = " (it is an extern function: write 'run %s with <variable>')" % rname if rname in self.externs else ""
                raise ZoomyError(f"unknown routine '{rname}'{hint}", node.file, node.line)
            if rname not in self.compiled and rname not in self.pending:
                self.pending.append(rname)
            a.call(f"R_{rname}")
        elif name == "runwith":
            fname, arg = g
            if fname not in self.externs:
                raise ZoomyError(f"'{fname}' is not a declared extern (add 'extern {fname}' at the top)", node.file, node.line)
            self.load_operand(0, arg, node)
            if not self.check_only:
                a.align_call_extern(fname)
            a.store_x(self.var(f"{fname}_result", node, write=True), 0)
        elif name in ("extern", "include"):
            raise ZoomyError(f"'{name}' belongs at the top level, outside action/routine blocks", node.file, node.line)

    def _index(self, idx, size, node):
        """rax = bounds-checked integer index (jumps to the runtime error handler when out of range)."""
        a = self.asm
        self.load_operand(0, idx, node)
        a.cvttsd2si_rax_x0()
        a.cmp_rax_imm(size)
        a.jump_rt("jae", RT_INDEX_ERR)

    def _print(self, kind, rest, node):
        a = self.asm
        items = parse_print_items(rest, node)
        if kind == "print":
            items.append(("str", b"\n"))
        for what, val in items:
            if what == "str":
                if val:
                    label = a.string(val)
                    a.mov_eax(1)
                    a.mov_edi(1)
                    a.lea_rsi_label(label)
                    a.mov_edx(len(val))
                    a.syscall()
            elif what == "num":
                self.load_operand(0, val, node)
                a.call_rt(RT_PRINT)
            else:                                   # char
                self.load_operand(0, val, node)
                a.cvttsd2si_rax_x0()
                a.store_rax(self.hidden(CH_SLOT))
                a.mov_eax(1)
                a.mov_edi(1)
                a.lea_rsi_var(self.hidden(CH_SLOT))
                a.mov_edx(1)
                a.syscall()

    # -- control flow ------------------------------------------------------------------
    def _condition(self, node):
        m = COND_RE.fullmatch(re.sub(r"^(if|while)\s+", "", node.text))
        if not m:
            raise ZoomyError(f"cannot understand condition: {node.text}  "
                             "(use: <a> is [not | less than | greater than | at least | at most] <b>)", node.file, node.line)
        left, op, right = m.group(1), m.group(2), m.group(3)
        return left, (re.sub(r"\s+", " ", op) if op else None), right

    def _jump_unless(self, left, op, right, false_label, node):
        """Compare and jump to false_label unless the condition holds. NaN makes every comparison false
        (except 'is not', which is true), like in other languages."""
        a = self.asm
        self.load_operand(0, left, node)
        self.load_operand(1, right, node)
        if op is None:                       # ==
            a.ucomisd(0, 1)
            a.jump("jne", false_label)
            a.jump("jp", false_label)
        elif op == "not":                    # !=
            ok = a.new_label("ok")
            a.ucomisd(0, 1)
            a.jump("jp", ok)
            a.jump("je", false_label)
            a.label(ok)
        elif op == "less than":
            a.ucomisd(1, 0)
            a.jump("jbe", false_label)
        elif op == "greater than":
            a.ucomisd(0, 1)
            a.jump("jbe", false_label)
        elif op == "at least":
            a.ucomisd(0, 1)
            a.jump("jb", false_label)
        else:                                # at most
            a.ucomisd(1, 0)
            a.jump("jb", false_label)

    def block(self, nodes):
        a = self.asm
        for node in nodes:
            if node.kind == "simple":
                self.statement(node)
            elif node.kind == "if":
                left, op, right = self._condition(node)
                end = a.new_label("endif")
                if node.else_children is None:
                    self._jump_unless(left, op, right, end, node)
                    self.block(node.children)
                else:
                    els = a.new_label("else")
                    self._jump_unless(left, op, right, els, node)
                    self.block(node.children)
                    a.jump("jmp", end)
                    a.label(els)
                    self.block(node.else_children)
                a.label(end)
            elif node.kind == "while":
                left, op, right = self._condition(node)
                top, end = a.new_label("loop"), a.new_label("endloop")
                a.label(top)
                self._jump_unless(left, op, right, end, node)
                self.block(node.children)
                a.jump("jmp", top)
                a.label(end)
            else:
                raise ZoomyError(f"'{node.kind}' blocks cannot be nested here", node.file, node.line)

    # -- syntax-only validation of routines nobody calls ----------------------------------
    def validate(self, nodes):
        for node in nodes:
            if node.kind == "simple":
                name, m = match_statement(node.text)
                if name is None:
                    raise ZoomyError(f"cannot understand: {node.text}", node.file, node.line)
                if name == "print":
                    parse_print_items(m.group(2), node)
                if name in ("extern", "include"):
                    raise ZoomyError(f"'{name}' belongs at the top level", node.file, node.line)
            elif node.kind in ("if", "while"):
                self._condition(node)
                self.validate(node.children)
                if node.else_children:
                    self.validate(node.else_children)
            else:
                raise ZoomyError(f"'{node.kind}' blocks cannot be nested here", node.file, node.line)

    # -- whole program ------------------------------------------------------------------
    def compile(self):
        a = self.asm
        if not self.actions:
            raise ZoomyError("no 'action' block found (a program needs 'action start:')")
        if len(self.actions) > 1:
            second = self.actions[1]
            raise ZoomyError(f"only one 'action' block is allowed (the first is at {self.actions[0].file}:{self.actions[0].line})",
                             second.file, second.line)
        a.prologue()
        for r in sorted(set(a.regmap.values())):         # --regs: the variables kept in registers start at 0
            a._emit(bytes([_rex(r, r), 0x31, 0xc0 | (r & 7) << 3 | (r & 7)]), f"xor {REG_NAMES[r]}, {REG_NAMES[r]}")
        a.store_imm_qword(self.hidden(PB_SLOT), -1)
        self.block(self.actions[0].children)
        a.xor_edi()                                   # falling off the end exits with code 0
        a.mov_eax(60)
        a.syscall()
        while self.pending:
            name = self.pending.pop(0)
            self.compiled.add(name)
            a.label(f"R_{name}")
            self.block(self.routines[name].children)
            a.ret()
        for name, node in self.routines.items():
            if name not in self.compiled:
                self.validate(node.children)
        a.patch_frame(max(16, (self.slots * 8 + 15) // 16 * 16))
        for name, (file, line) in sorted(self.reads.items(), key=lambda kv: kv[1]):
            if name not in self.writes and not name.endswith("_result"):
                self.warnings.append(f"{file}:{line}: warning: variable '{name}' is read but never set (it is always 0)")
        return a


# =============================================================================
# Native compiler for the full-language front end (zoomy_py): expressions, pipelines, Structurally blocks, ...
# =============================================================================
class _At:
    def __init__(self, file, line):
        self.file, self.line = file, line


class AstCompiler(Compiler):
    """Compiles the statement tree produced by zoomy_py (only the number-only subset) to machine code."""
    CMP = {"eq": None, "ne": "not", "lt": "less than", "gt": "greater than", "ge": "at least", "le": "at most"}

    def __init__(self, prog):
        self.leaf_map = {}
        super().__init__(prog.file)
        self.prog = prog
        self.loops = []
        self.in_routine = False
        self.char_vars = {s[4][1] for s in _zpy().all_stmts(prog.stmts) if s[0] == "convert" and s[2] == "number"}
        self.assigned = set()
        zp = _zpy()
        for st in zp.all_stmts(prog.stmts):
            self.assigned.update(zp.assigned_names(st))
        self.node = _At(prog.file, 0)
        self.pre_count, self.flag_temps = 0, set()
        self.fdefs = {}                                  # name -> define statement (functions with values)
        self.cur_fn, self.cur_temps = None, None
        self.recursive = set()
        self.depth_slot = None
        self.ints = getattr(prog, "ints", False)
        self.uns = self.ints and getattr(prog, "uns", False)       # unsigned 64-bit integers (--unsigned)

    UNS_JUMP = {"jl": "jb", "jle": "jbe", "jg": "ja", "jge": "jae"}

    def cc(self, kind):
        """the conditional jump for comparing numbers: signed normally, the unsigned twin in unsigned mode"""
        return self.UNS_JUMP.get(kind, kind) if self.uns else kind

    def temp(self):
        """a hidden 8-byte slot (loop counters and bounds); inside a function it belongs to that function"""
        self.slots += 1
        self._check_frame(self.node)
        d = -8 * self.slots
        if self.cur_temps is not None:
            self.cur_temps.append(d)
        return d

    def zero_x(self, n):
        self.asm.mov_rax_imm64(0)
        self.asm.movq_x_rax(n)

    def is_flag(self, e):
        return e[0] in ("bool", "cmp", "and", "or", "not") or (e[0] == "var" and (e[1] in self.prog.n_flags or e[1] in self.flag_temps))

    def find_recursion(self, funcs):
        """names of functions that can reach themselves (their variables must be saved around a call)"""
        calls = {}
        for name, f in funcs.items():
            body = f[3] if f[0] == "routine" else f[4]
            c = set()
            for st in _zpy().all_stmts(body):
                if st[0] == "run":
                    c.add(st[2])
                for e in _zpy().stmt_exprs(st):
                    _zpy().walk(e, lambda x: c.add(x[1][1]) if x[0] == "call" and x[1][0] == "var" else None)
            calls[name] = c & set(funcs)
        out = set()
        for name in funcs:
            seen, todo = set(), list(calls[name])
            while todo:
                n = todo.pop()
                if n == name:
                    out.add(name)
                    break
                if n not in seen:
                    seen.add(n)
                    todo += list(calls[n])
        return out

    def locals_of(self, f):
        zp = _zpy()
        names, glob = set(f[3]), set()
        for st in zp.all_stmts(f[4]):
            names.update(zp.assigned_names(st))
            if st[0] == "global":
                glob.update(st[2])
        return (names - glob) - {"input_ok"}

    # -- helpers
    def at(self, st):
        self.node = _At(self.prog.file, st[1])

    def load_simple(self, reg, e):
        a = self.asm
        if self.ints and e[0] == "num":
            a.mov_rax_imm64(int(e[1]) & 0xFFFFFFFFFFFFFFFF)
            a.movq_x_rax(reg)
        elif self.ints and e[0] == "var" and e[1] == "pi" and "pi" not in self.assigned:
            a.mov_rax_imm64(3)
            a.movq_x_rax(reg)
        elif e[0] == "num":
            a.mov_rax_imm64(f64_bits(e[1]))
            a.movq_x_rax(reg)
        elif e[0] == "var" and e[1] == "pi" and "pi" not in self.assigned:
            a.mov_rax_imm64(f64_bits(3.141592653589793))
            a.movq_x_rax(reg)
        else:
            a.load_x(reg, self.var(e[1], self.node))

    @staticmethod
    def simple(e):
        return e[0] in ("num", "var")

    def ex(self, e):
        """xmm0 = value of the expression (clobbers xmm1, xmm2, rax)."""
        if self.ints:
            return self.ex_int(e)
        a, k = self.asm, e[0]
        if self.simple(e):
            self.load_simple(0, e)
        elif k == "neg":
            self.ex(e[1])
            a.movq_rax_x0()
            a.btc_rax_63()
            a.movq_x_rax(0)
        elif k == "bin" and e[1] in ("plus", "minus", "times", "divide") and e[3][0] == "var" and e[3][1] != "pi" and \
                a._use(self.var(e[3][1], self.node)) is None:
            self.ex(e[2])                                       # the right operand is a variable in memory: use it in place
            a.alu_mem({"plus": "addsd", "minus": "subsd", "times": "mulsd", "divide": "divsd"}[e[1]], self.var(e[3][1], self.node))
        elif k == "bin":
            self.two(e[2], e[3])
            op = e[1]
            if op in ("plus", "minus", "times", "divide"):
                a.alu({"plus": "addsd", "minus": "subsd", "times": "mulsd", "divide": "divsd"}[op])
            elif op == "mod":
                a.movapd(2, 0)
                a.alu("divsd", 2, 1)
                a.roundsd(2, 9)
                a.alu("mulsd", 2, 1)
                a.alu("subsd", 0, 2)
            else:
                a.call_rt(RT_POW)
        elif k == "bool":
            a.mov_rax_imm64(f64_bits(1.0 if e[1] else 0.0))
            a.movq_x_rax(0)
        elif k in ("cmp", "and", "or", "not"):
            no, end = a.new_label("no"), a.new_label("endv")
            self.jump_unless(e, no)
            a.mov_rax_imm64(f64_bits(1.0))
            a.movq_x_rax(0)
            a.jump("jmp", end)
            a.label(no)
            self.zero_x(0)
            a.label(end)
        elif k == "index":
            base, size = self.array(e[1][1], self.node)
            self.index(e[2], size)
            a.load_x_idx(0, base)
        elif k == "call":
            self.call_function(e)
        elif k == "fn" and e[1] in ("len", "first", "last"):
            base, size = self.array(e[2][0][1], self.node)
            if e[1] == "len":
                a.mov_rax_imm64(f64_bits(float(size)))
                a.movq_x_rax(0)
            else:
                a.mov_rax_imm64(0 if e[1] == "first" else size - 1)
                a.load_x_idx(0, base)
        elif k == "fn":
            if e[1] == "rem":
                self.two(e[2][0], e[2][1])
                a.movapd(2, 0)
                a.alu("divsd", 2, 1)
                a.roundsd(2, 11)
                a.alu("mulsd", 2, 1)
                a.alu("subsd", 0, 2)
            else:
                self.ex(e[2][0])
                if e[1] == "sqrt":
                    a.sqrtsd()
                elif e[1] == "abs":
                    a.movq_rax_x0()
                    a.btr_rax_63()
                    a.movq_x_rax(0)
                else:
                    a.roundsd(0, 9 if e[1] == "floor" else 10)
        else:
            raise ZoomyError(f"internal error: cannot compile {k} natively", self.node.file, self.node.line)

    # -- integer mode (Zoomy 6.1) ---------------------------------------------------------------
    def x0_to_rax(self):
        if self.ints:
            self.asm.movq_rax_x0()
        else:
            self.asm.cvttsd2si_rax_x0()

    def x0_to_rdi(self):
        if self.ints:
            self.asm.i("movq rdi, xmm0")
        else:
            self.asm.cvttsd2si_rdi_x0()

    def rax_to_x0(self):
        if self.ints:
            self.asm.movq_x_rax(0)
        else:
            self.asm.cvtsi2sd_x0_rax()

    def print_num(self):
        if self.ints:
            self.asm.movq_rax_x0()
            self.asm.call_rt(RT_PRINT_U if self.uns else RT_PRINT_I)
        else:
            self.asm.call_rt(RT_PRINT)

    def arith(self, op):
        """xmm0 = xmm0 <op> xmm1  for add / sub / mul / div"""
        if self.ints:
            self.int_arith(op)
        else:
            self.asm.alu({"add": "addsd", "sub": "subsd", "mul": "mulsd", "div": "divsd"}[op])

    def int_arith(self, op):
        """integers: xmm0 = xmm0 <op> xmm1"""
        a = self.asm
        a.movq_rax_x0()
        a.i("movq rcx, xmm1")
        if op in ("plus", "add"):
            a.i("add rax, rcx")
        elif op in ("minus", "sub"):
            a.i("sub rax, rcx")
        elif op in ("times", "mul"):
            a.i("imul rax, rcx")
        elif op in ("divide", "div", "mod", "rem"):
            a.i("test rcx, rcx")
            a.jump_rt("je", RT_ERR_DIV0)
            if self.uns:                                        # unsigned: plain div, the remainder is never negative
                a.i("xor edx, edx")
                a.i("div rcx")
                if op not in ("divide", "div"):
                    a.i("mov rax, rdx")
                a.movq_x_rax(0)
                return
            general, done = a.new_label("idiv"), a.new_label("idone")
            a.i("cmp rcx, -1")                                  # x / -1 would trap for the smallest integer
            a.jump("jne", general)
            if op in ("divide", "div"):
                a.i("neg rax")
            else:
                a.i("xor eax, eax")
            a.jump("jmp", done)
            a.label(general)
            a.i("cqo")
            a.i("idiv rcx")
            if op not in ("divide", "div"):
                if op == "mod":                                 # the result takes the sign of the divisor (floor)
                    z = a.new_label("modz")
                    a.i("test rdx, rdx")
                    a.jump("je", z)
                    a.i("mov rax, rdx")
                    a.i("xor rax, rcx")
                    a.jump("jns", z)
                    a.i("add rdx, rcx")
                    a.label(z)
                a.i("mov rax, rdx")
            a.label(done)
        else:
            a.call_rt(RT_POW_I)
        a.movq_x_rax(0)

    def bit_op(self, op, b):
        """rax = rax <op> rcx (or a one-operand operation)"""
        a = self.asm
        if op in ("and", "or", "xor"):
            a.i(f"{op} rax, rcx")
        elif op == "andnot":
            a.i("not rcx")
            a.i("and rax, rcx")
        elif op in ("shl", "shr", "sar"):
            a.i("cmp rcx, 63")
            a.jump_rt("ja", RT_ERR_BIT)
            a.i(f"{op} rax, cl")
        elif op in ("rol", "ror"):
            a.i(f"{op} rax, cl")
        elif op in ("setbit", "clearbit", "flipbit"):
            a.i("cmp rcx, 63")
            a.jump_rt("ja", RT_ERR_BIT)
            a.i("mov edx, 1")
            a.i("shl rdx, cl")
            if op == "setbit":
                a.i("or rax, rdx")
            elif op == "clearbit":
                a.i("not rdx")
                a.i("and rax, rdx")
            else:
                a.i("xor rax, rdx")
        elif op == "not":
            a.i("not rax")
        elif op in ("popcnt", "tzcnt", "lzcnt"):
            a.i(f"{op} rax, rax")
        elif op in ("pext", "pdep"):
            a.i(f"{op} rax, rax, rcx")                          # BMI2 (Intel Haswell 2013 / AMD Zen and newer)
        elif op == "bswap":
            a.i("bswap rax")
        elif op == "lowbit":
            a.i("mov rdx, rax")
            a.i("neg rdx")
            a.i("and rax, rdx")
        elif op == "clearlow":
            a.i("lea rdx, [rax-1]")
            a.i("and rax, rdx")
        else:
            raise ZoomyError(f"internal error: unknown bit operation {op}", self.node.file, self.node.line)

    def ex_int(self, e):
        """integer mode: xmm0 = the raw 64-bit value of the expression (clobbers xmm1, rax, rcx, rdx)"""
        self.exr(e)
        self.asm.movq_x_rax(0)

    def ex_int_x(self, e):
        """the older xmm0-based evaluator, still used for the rare shapes exr() does not handle itself"""
        a, k = self.asm, e[0]
        if self.simple(e):
            self.load_simple(0, e)
        elif k == "neg":
            self.ex(e[1])
            a.movq_rax_x0()
            a.i("neg rax")
            a.movq_x_rax(0)
        elif k == "bin":
            self.two(e[2], e[3])
            self.int_arith(e[1])
        elif k == "bitop":
            if e[3] is not None:
                self.two(e[2], e[3])
                a.movq_rax_x0()
                a.i("movq rcx, xmm1")
            else:
                self.ex(e[2])
                a.movq_rax_x0()
            self.bit_op(e[1], e[3])
            a.movq_x_rax(0)
        elif k == "bool":
            a.mov_rax_imm64(1 if e[1] else 0)
            a.movq_x_rax(0)
        elif k in ("cmp", "and", "or", "not"):
            no, end = a.new_label("no"), a.new_label("endv")
            self.jump_unless(e, no)
            a.mov_rax_imm64(1)
            a.movq_x_rax(0)
            a.jump("jmp", end)
            a.label(no)
            self.zero_x(0)
            a.label(end)
        elif k == "index":
            base, size = self.array(e[1][1], self.node)
            self.index(e[2], size)
            a.load_x_idx(0, base)
        elif k == "call":
            self.call_function(e)
            a.movq_x_rax(0)
        elif k == "fn" and e[1] in ("len", "first", "last"):
            base, size = self.array(e[2][0][1], self.node)
            if e[1] == "len":
                a.mov_rax_imm64(size)
                a.movq_x_rax(0)
            else:
                a.mov_rax_imm64(0 if e[1] == "first" else size - 1)
                a.load_x_idx(0, base)
        elif k == "fn":
            if e[1] == "rem":
                self.two(e[2][0], e[2][1])
                self.int_arith("rem")
            else:
                self.ex(e[2][0])
                if e[1] == "sqrt":
                    a.movq_rax_x0()
                    a.call_rt(RT_ISQRT_U if self.uns else RT_ISQRT)
                    a.movq_x_rax(0)
                elif e[1] == "abs" and self.uns:
                    pass                                        # an unsigned number is its own absolute value
                elif e[1] == "abs":
                    pos = a.new_label("abs")
                    a.movq_rax_x0()
                    a.i("test rax, rax")
                    a.jump("jns", pos)
                    a.i("neg rax")
                    a.label(pos)
                    a.movq_x_rax(0)
        else:
            raise ZoomyError(f"internal error: cannot compile {k} natively", self.node.file, self.node.line)

    # -- integer mode, register code generator (Zoomy 6.3): values are worked out in rax, constants and variables are used
    #    as instruction operands, and nothing goes through xmm0 any more ---------------------------------------------------
    M64 = (1 << 64) - 1

    def opnd(self, e):
        """an operand that needs no code of its own: ('imm', v) for a constant that fits 32 bits, ('var', slot) for a variable"""
        k = e[0]
        if k == "num":
            v = int(e[1]) & self.M64
            if v >= 1 << 63:
                v -= 1 << 64
            return ("imm", v) if -(1 << 31) <= v < (1 << 31) else None
        if k == "var":
            if e[1] == "pi" and "pi" not in self.assigned:
                return ("imm", 3)
            return ("var", self.var(e[1], self.node))
        return None

    def srcop(self, o):
        return o if o[0] == "imm" else self.asm.src(o[1])

    def load_to(self, reg, o):
        if o[0] == "imm":
            self.asm.mov_ri(reg, o[1])
        else:
            self.asm.get(reg, o[1])

    def has_call(self, e):
        if isinstance(e, (list, tuple)):
            return (len(e) > 0 and e[0] == "call") or any(self.has_call(x) for x in e)
        return False

    def exr(self, e):
        """rax = the value of e  (clobbers rcx and rdx; temporaries go on the stack)"""
        a, k = self.asm, e[0]
        o = self.opnd(e)
        if o is not None:
            return self.load_to(0, o)
        if k == "num":
            a.mov_rax_imm64(int(e[1]) & self.M64)
        elif k == "neg":
            self.exr(e[1])
            a.neg_r(0)
        elif k == "bin":
            self.bin_r(e)
        elif k == "bool":
            a.mov_ri(0, 1 if e[1] else 0)
        elif k == "index":
            self.load_elem(e[1][1], e[2])
        elif k == "call":
            self.call_function(e)
        elif k == "bitop" and e[3] is not None and self.opnd(e[3]) is not None and self.opnd(e[3])[0] == "imm" and (
                (e[1] in ("and", "or", "xor")) or (e[1] in ("shl", "shr", "sar") and 0 <= self.opnd(e[3])[1] <= 63)):
            self.exr(e[2])
            v = self.opnd(e[3])[1]
            if e[1] in ("shl", "shr", "sar"):
                if v:
                    a.shift_ri(e[1], 0, v)
            else:
                a.ialu(e[1], 0, ("imm", v))
        elif k == "bitop":
            if e[3] is not None:
                self.two_r(e[2], e[3])
            else:
                self.exr(e[2])
            self.bit_op(e[1], e[3])
        elif k in ("cmp", "and", "or", "not"):
            no, end = a.new_label("no"), a.new_label("endv")
            self.jump_unless(e, no)
            a.mov_ri(0, 1)
            a.jump("jmp", end)
            a.label(no)
            a.mov_ri(0, 0)
            a.label(end)
        elif k == "fn" and e[1] in ("len", "first", "last"):
            base, size = self.array(e[2][0][1], self.node)
            if e[1] == "len":
                a.mov_ri(0, size)
            else:
                a.mem_load(0, SharedOff(int(base) + 8 * (0 if e[1] == "first" else size - 1)) if isinstance(base, SharedOff) else base + 8 * (0 if e[1] == "first" else size - 1))
        elif k == "fn" and e[1] == "rem":
            self.two_r(e[2][0], e[2][1])
            self.int_div("rem")
        elif k == "fn" and e[1] == "sqrt":
            self.exr(e[2][0])
            a.call_rt(RT_ISQRT_U if self.uns else RT_ISQRT)
        elif k == "fn" and e[1] == "abs":
            self.exr(e[2][0])
            if not self.uns:
                pos = a.new_label("abs")
                a.test_rr(0)
                a.jump("jns", pos)
                a.neg_r(0)
                a.label(pos)
        else:
            self.ex_int_x(e)
            a.movq_rax_x0()

    def two_r(self, l, r):
        """rax = l, rcx = r  (l is worked out first, like the Python backend)"""
        a = self.asm
        o = self.opnd(r)
        if o is not None:
            self.exr(l)
            self.load_to(1, o)
            return
        lo = self.opnd(l)
        if lo is not None and not self.has_call(r):          # a variable or constant has no side effects: read it last
            self.exr(r)
            a._mov_rr(1, 0)
            self.load_to(0, lo)
            return
        self.exr(l)
        a.push_r(0)
        self.exr(r)
        a._mov_rr(1, 0)
        a.pop_r(0)

    def bin_r(self, e):
        a = self.asm
        op, l, r = e[1], e[2], e[3]
        if op in ("plus", "add", "minus", "sub", "times", "mul"):
            name = {"plus": "add", "add": "add", "minus": "sub", "sub": "sub", "times": "imul", "mul": "imul"}[op]
            o = self.opnd(r)
            if o is None and name != "sub" and self.opnd(l) is not None and not self.has_call(r):
                l, r = r, l
                o = self.opnd(r)
            if o is not None:
                self.exr(l)
                src = self.srcop(o)
            else:
                self.two_r(l, r)
                src = ("reg", 1)
            if name == "imul":
                if src[0] == "imm" and src[1] > 0 and (src[1] & (src[1] - 1)) == 0:
                    if src[1] > 1:
                        a.shift_ri("shl", 0, src[1].bit_length() - 1)
                else:
                    a.imul(0, src)
            elif not (src[0] == "imm" and src[1] == 0):
                a.ialu(name, 0, src)
        elif op in ("divide", "div", "mod", "rem"):
            o = self.opnd(r)
            if o is not None and o[0] == "imm" and o[1] > 0:
                self.exr(l)
                self.div_const(op, o[1])
            else:
                self.two_r(l, r)
                self.int_div(op)
        else:
            self.two_r(l, r)
            a.call_rt(RT_POW_I)

    def div_const(self, op, c):
        """rax = rax / c, mod c or rem c for a constant 0 < c < 2^31 (no zero test needed, powers of two become shifts and masks)"""
        a = self.asm
        k = c.bit_length() - 1
        pow2 = (c & (c - 1)) == 0
        divide = op in ("divide", "div")
        if c == 1:
            if not divide:
                a.mov_ri(0, 0)
            return
        if self.uns:
            if pow2:
                if divide:
                    a.shift_ri("shr", 0, k)
                else:
                    a.ialu("and", 0, ("imm", c - 1))
                return
            a.mov_ri(1, c)
            a.mov_ri(2, 0)
            a.i("div rcx")
            if not divide:
                a.i("mov rax, rdx")
            return
        if pow2:
            if op == "mod":                                   # the result takes the sign of the divisor: a mask does it
                a.ialu("and", 0, ("imm", c - 1))
                return
            a._mov_rr(2, 0)                                   # divide and rem truncate toward zero: add c-1 to a negative number first
            a.shift_ri("sar", 2, 63)
            a.shift_ri("shr", 2, 64 - k)
            if divide:
                a.ialu("add", 0, ("reg", 2))
                a.shift_ri("sar", 0, k)
            else:
                a.ialu("add", 2, ("reg", 0))
                a.ialu("and", 2, ("imm", -c))
                a.ialu("sub", 0, ("reg", 2))
            return
        a.mov_ri(1, c)
        a.i("cqo")
        a.i("idiv rcx")
        if divide:
            return
        if op == "mod":                                       # rdx + (c if rdx < 0)
            a.i("mov rax, rdx")
            a.shift_ri("sar", 0, 63)
            a.ialu("and", 0, ("reg", 1))
            a.ialu("add", 0, ("reg", 2))
        else:
            a.i("mov rax, rdx")

    def int_div(self, op):
        """rax = rax <op> rcx for divide, div, mod, rem (zero and -1 are checked at run time)"""
        a = self.asm
        a.test_rr(1)
        a.jump_rt("je", RT_ERR_DIV0)
        if self.uns:
            a.i("xor edx, edx")
            a.i("div rcx")
            if op not in ("divide", "div"):
                a.i("mov rax, rdx")
            return
        general, done = a.new_label("idiv"), a.new_label("idone")
        a.ialu("cmp", 1, ("imm", -1))                      # x / -1 would trap for the smallest integer
        a.jump("jne", general)
        if op in ("divide", "div"):
            a.neg_r(0)
        else:
            a.mov_ri(0, 0)
        a.jump("jmp", done)
        a.label(general)
        a.i("cqo")
        a.i("idiv rcx")
        if op not in ("divide", "div"):
            if op == "mod":                                   # the result takes the sign of the divisor (floor)
                z = a.new_label("modz")
                a.test_rr(2)
                a.jump("je", z)
                a.i("mov rax, rdx")
                a.i("xor rax, rcx")
                a.jump("jns", z)
                a.ialu("add", 2, ("reg", 1))
                a.label(z)
            a.i("mov rax, rdx")
        a.label(done)

    def key_to_rax(self, key, size):
        """rax = a checked array index"""
        a = self.asm
        self.exr(key)
        a.cmp_rax_imm(size)
        a.jump_rt("jae", RT_INDEX_ERR)

    def const_slot(self, key, base, size):
        """the address of element `key` when the index is a constant inside the array, else None"""
        if key[0] == "num":
            v = int(key[1])
            if 0 <= v < size:
                return SharedOff(int(base) + 8 * v) if isinstance(base, SharedOff) else base + 8 * v
        return None

    def load_elem(self, name, key):
        """rax = name[key]"""
        a = self.asm
        base, size = self.array(name, self.node)
        d = self.const_slot(key, base, size)
        if d is not None:
            return a.mem_load(0, d)
        self.key_to_rax(key, size)
        a.idx_load(0, base)

    def store_elem_r(self, name, key, value, n):
        a = self.asm
        base, size = self.array(name, n)
        vo = self.opnd(value)
        d = self.const_slot(key, base, size)
        if d is not None:
            if vo is not None and vo[0] == "imm":
                return a.mem_store_imm(d, vo[1])
            if vo is not None:
                s = self.srcop(vo)
                if s[0] == "reg":
                    return a.mem_store(d, s[1])
            self.exr(value)
            return a.mem_store(d, 0)
        if vo is not None:                                    # a constant or a variable: read it after the index, as before
            self.key_to_rax(key, size)
            if vo[0] == "imm":
                return a.idx_store_imm(base, vo[1])
            s = self.srcop(vo)
            if s[0] == "reg":
                return a.idx_store(base, s[1])
            self.load_to(1, vo)
            return a.idx_store(base, 1)
        if self.opnd(key) is not None:                        # a plain index has no side effects: value first, then the index
            self.exr(value)
            a._mov_rr(1, 0)
            self.key_to_rax(key, size)
        else:
            self.exr(key)
            a.push_r(0)
            self.exr(value)
            a._mov_rr(1, 0)
            a.pop_r(0)
            a.cmp_rax_imm(size)
            a.jump_rt("jae", RT_INDEX_ERR)
        a.idx_store(base, 1)

    def aug_r(self, st, n):
        """add / subtract / multiply / divide  VALUE  to / from / by  a variable or an array item  (integer mode)"""
        a = self.asm
        op, val, tgt = st[2], st[3], st[4]
        name = {"add": "add", "sub": "sub", "mul": "imul", "div": "div"}[op]
        if tgt[0] == "index":
            if name not in ("add", "sub"):
                return False
            base, size = self.array(tgt[1][1], n)
            vo = self.opnd(val)
            if vo is not None:
                d = self.const_slot(tgt[2], base, size)
                s = self.srcop(vo)
                if d is not None:
                    if s[0] == "mem":
                        a.get(0, s[1])
                        s = ("reg", 0)
                    a.ialu_mem(name, d, s)
                    return True
                self.key_to_rax(tgt[2], size)
                if s[0] == "mem":
                    a.get(1, s[1])
                    s = ("reg", 1)
                a.idx_alu(name, base, s)
                return True
            self.exr(val)
            a.push_r(0)
            self.key_to_rax(tgt[2], size)
            a.pop_r(1)
            a.idx_alu(name, base, ("reg", 1))
            return True
        d = self.var(tgt[1], n)
        self.writes.add(tgt[1])
        vo = self.opnd(val)
        if name in ("add", "sub"):
            if vo is not None:
                a.ivar(name, d, self.srcop(vo))
            else:
                self.exr(val)
                a.ivar(name, d, ("reg", 0))
        elif name == "imul":
            if vo is not None:
                s = self.srcop(vo)
            else:
                self.exr(val)
                s = ("reg", 0)
            r = a._use(d)
            if r is not None:
                a.imul(r, s)
            else:
                if s[0] == "imm":
                    a.get(0, d)
                    a.imul(0, s)
                else:
                    if s != ("reg", 0):
                        self.load_to(0, vo)
                    a.imul(0, ("mem", d))
                a.put(d, 0)
        else:
            if vo is not None and vo[0] == "imm" and vo[1] > 0:
                a.get(0, d)
                self.div_const("div", vo[1])
            else:
                self.exr(val)
                a._mov_rr(1, 0)
                a.get(0, d)
                self.int_div("div")
            a.put(d, 0)
        return True

    def set_r(self, st, n):
        """set VARIABLE to EXPRESSION  (integer mode)"""
        a = self.asm
        e, name = st[3], st[2][1]
        o = self.opnd(e)
        if o is not None:
            d = self.var(name, n, write=True)
            if o[0] == "imm":
                return a.store_imm_qword(d, o[1])
            return a.mov_var(d, o[1])
        if e[0] == "bin" and e[1] in ("plus", "add", "minus", "sub"):
            l, r = e[2], e[3]
            if l[0] == "var" and l[1] == name and self.opnd(r) is not None:
                d = self.var(name, n, write=True)
                return a.ivar("add" if e[1] in ("plus", "add") else "sub", d, self.srcop(self.opnd(r)))
        self.exr(e)
        a.put(self.var(name, n, write=True), 0)

    def cmp_r(self, l, r):
        """set the flags as  cmp l, r"""
        a = self.asm
        o, lo = self.opnd(r), self.opnd(l)
        if o is not None:
            if lo is not None and lo[0] == "var":
                s, so = a.src(lo[1]), self.srcop(o)
                if s[0] == "reg":
                    return a.ialu("cmp", s[1], so)
                if so[0] != "mem":
                    return a.ialu_mem("cmp", s[1], so)
                a.get(0, s[1])
                return a.ialu("cmp", 0, so)
            self.exr(l)
            return a.ialu("cmp", 0, self.srcop(o))
        self.two_r(l, r)
        a.ialu("cmp", 0, ("reg", 1))

    def jf(self, op):
        """the jump that is taken when the comparison `op` is false"""
        return {None: "jne", "not": "je", "less than": self.cc("jge"), "greater than": self.cc("jle"),
                "at least": self.cc("jl"), "at most": self.cc("jg")}[op]

    def jt(self, op):
        """the jump that is taken when the comparison `op` is true"""
        return {None: "je", "not": "jne", "less than": self.cc("jl"), "greater than": self.cc("jg"),
                "at least": self.cc("jge"), "at most": self.cc("jle")}[op]

    def start_workers(self, st, n):
        """fork N-1 children; each gets its number (1..N-1) in the variable, the parent keeps 0"""
        a = self.asm
        tn, tk = self.temp(), self.temp()
        var = self.var(st[3][1], n, write=True)
        self.ex(st[2])
        self.x0_to_rax()
        a.cmp_rax_imm(1)
        ok1 = a.new_label("w1")
        a.jump(self.cc("jge"), ok1)
        a.mov_eax(1)
        a.label(ok1)
        a.cmp_rax_imm(1024)
        ok2 = a.new_label("w2")
        a.jump(self.cc("jle"), ok2)
        a.mov_eax(1024)
        a.label(ok2)
        a.store_rax(tn)
        a.mov_rax_imm64(0)
        a.store_rax(var)
        a.mov_rax_imm64(1)
        a.store_rax(tk)
        top, parent, end, child_done = (a.new_label(x) for x in ("wtop", "wpar", "wend", "wchild"))
        a.label(top)
        a.load_rax(tk)
        a.load_rcx(tn)
        a.i("cmp rax, rcx")
        a.jump("jge", end)
        a.mov_eax(57)                                   # fork
        a.syscall()
        a.i("test rax, rax")
        a.jump("jne", parent)
        a.mov_eax(157)                                  # prctl(PR_SET_PDEATHSIG, SIGKILL): die with the parent
        a.mov_edi(1)
        a.mov_esi(9)
        a.syscall()
        a.load_rax(tk)
        self.rax_to_x0()
        a.store_x(var, 0)
        a.jump("jmp", child_done)
        a.label(parent)
        a.load_rax(tk)
        a.add_rax_imm(1)
        a.store_rax(tk)
        a.jump("jmp", top)
        a.label(end)
        a.label(child_done)

    def for_loop_int(self, st, n):
        """for i from A to B [by S]  with integers.  A constant step (the usual case) gets a loop that tests at the bottom."""
        a = self.asm
        so = ("imm", 1) if st[5] is None else self.opnd(st[5])
        if so is None or so[0] != "imm" or so[1] == 0:
            return self.for_loop_int_general(st, n)
        sv, up = so[1], so[1] > 0
        ta = self.temp()
        self.exr(st[3])
        a.put(ta, 0)                                        # the counter: the loop variable itself may be changed by the body
        bo = self.opnd(st[4])
        if bo is not None and bo[0] == "imm":
            bound = bo
        else:
            tb = self.temp()
            self.exr(st[4])
            a.put(tb, 0)
            bound = ("var", tb)
        top, step, end = a.new_label("ifor"), a.new_label("istep"), a.new_label("iend")
        self.cmp_vs(ta, bound)
        a.jump(self.cc("jg") if up else self.cc("jl"), end)
        a.label(top)
        a.mov_var(self.var(st[2], n, write=True), ta)
        self.loops.append((step, end))
        self.blk(st[6])
        self.loops.pop()
        a.label(step)
        a.ivar("add", ta, ("imm", sv))
        if self.uns:                                        # leave the loop when the counter wraps around past 0 or 2^64
            a.jump("jb" if up else "jae", end)
        else:
            a.jump("jo", end)
        self.cmp_vs(ta, bound)
        a.jump(self.cc("jle") if up else self.cc("jge"), top)
        a.label(end)

    def cmp_vs(self, d, bound):
        """flags as  cmp <variable d>, bound"""
        a = self.asm
        s, so = a.src(d), self.srcop(bound)
        if s[0] == "reg":
            return a.ialu("cmp", s[1], so)
        if so[0] != "mem":
            return a.ialu_mem("cmp", s[1], so)
        a.get(0, s[1])
        a.ialu("cmp", 0, so)

    def for_loop_int_general(self, st, n):
        """the same for a step that is worked out at run time: the bounds and the step are worked out once"""
        a = self.asm
        ta, tb, ts = (self.temp() for _ in range(3))
        self.ex(st[3])
        a.store_x(ta, 0)
        self.ex(st[4])
        a.store_x(tb, 0)
        if st[5] is None:
            a.mov_rax_imm64(1)
            a.movq_x_rax(0)
        else:
            self.ex(st[5])
        a.store_x(ts, 0)
        a.load_rax(ts)
        a.i("test rax, rax")
        a.jump_rt("je", RT_ERR_STEP)
        top, neg, body, step, end = (a.new_label(x) for x in ("ifor", "ineg", "ibody", "istep", "iend"))
        a.label(top)
        a.load_rax(ta)
        a.load_rcx(tb)
        a.load_rdx(ts)
        a.i("test rdx, rdx")
        a.jump("js", neg)
        a.i("cmp rax, rcx")
        a.jump(self.cc("jg"), end)
        a.jump("jmp", body)
        a.label(neg)
        a.i("cmp rax, rcx")
        a.jump(self.cc("jl"), end)
        a.label(body)
        a.store_rax(self.var(st[2], n, write=True))
        self.loops.append((step, end))
        self.blk(st[6])
        self.loops.pop()
        a.label(step)
        a.load_rax(ta)
        a.load_rdx(ts)
        if self.uns:                                    # leave the loop when the counter would wrap around past 0 or 2^64
            store, down = a.new_label("ustore"), a.new_label("udown")
            a.i("test rdx, rdx")
            a.jump("js", down)
            a.i("add rax, rdx")
            a.jump("jb", end)
            a.jump("jmp", store)
            a.label(down)
            a.i("add rax, rdx")
            a.jump("jae", end)
            a.label(store)
        else:
            a.i("add rax, rdx")
        a.store_rax(ta)
        a.jump("jmp", top)
        a.label(end)

    def foreach_int(self, st, n, base, size, tk):
        a = self.asm
        a.store_imm_qword(tk, 0)
        top, step, end = a.new_label("each"), a.new_label("eachstep"), a.new_label("endeach")
        a.label(top)
        a.get(0, tk)
        a.cmp_rax_imm(size)
        a.jump("jae", end)
        a.idx_load(0, base)
        a.put(self.var(st[2], n, write=True), 0)
        self.loops.append((step, end))
        self.blk(st[4])
        self.loops.pop()
        a.label(step)
        a.ivar("add", tk, ("imm", 1))
        a.jump("jmp", top)
        a.label(end)

    def two(self, left, right):
        """xmm0 = left, xmm1 = right."""
        a = self.asm
        if self.simple(right):
            self.ex(left)
            self.load_simple(1, right)
        elif self.simple(left) and not self.has_call(right):     # a variable or constant is read last: no need for the stack
            self.ex(right)
            a.movapd(1, 0)
            self.load_simple(0, left)
        else:
            self.ex(left)
            a.push_x0()
            self.ex(right)
            a.movapd(1, 0)
            a.pop_x(0)

    def index(self, key, size):
        a = self.asm
        self.ex(key)
        self.x0_to_rax()
        a.cmp_rax_imm(size)
        a.jump_rt("jae", RT_INDEX_ERR)

    # -- conditions
    def jump_unless(self, c, fl):
        a, k = self.asm, c[0]
        if self.ints and k == "cmp":
            self.cmp_r(c[2], c[3])
            a.jump(self.jf(self.CMP[c[1]]), fl)
        elif self.ints and k == "var":
            a.ivar("cmp", self.var(c[1], self.node), ("imm", 0))
            a.jump("je", fl)
        elif k == "cmp":
            self.two(c[2], c[3])
            self._cmp_jump(self.CMP[c[1]], fl)
        elif k == "and":
            self.jump_unless(c[1], fl)
            self.jump_unless(c[2], fl)
        elif k == "or":
            t = a.new_label("or")
            self.jump_if(c[1], t)
            self.jump_unless(c[2], fl)
            a.label(t)
        elif k == "not":
            self.jump_if(c[1], fl)
        elif k == "bool":
            if not c[1]:
                a.jump("jmp", fl)
        elif k == "var" and self.ints:
            a.load_rax(self.var(c[1], self.node))
            a.i("test rax, rax")
            a.jump("je", fl)
        elif k == "var":                                # a yes/no variable
            a.load_x(0, self.var(c[1], self.node))
            self.zero_x(1)
            a.ucomisd(0, 1)
            a.jump("je", fl)

    def jump_if(self, c, tl):
        a = self.asm
        if self.ints and c[0] == "cmp":
            self.cmp_r(c[2], c[3])
            a.jump(self.jt(self.CMP[c[1]]), tl)
            return
        if self.ints and c[0] == "or":
            self.jump_if(c[1], tl)
            self.jump_if(c[2], tl)
            return
        if self.ints and c[0] == "and":
            skip = a.new_label("skip")
            self.jump_unless(c[1], skip)
            self.jump_if(c[2], tl)
            a.label(skip)
            return
        if self.ints and c[0] == "not":
            self.jump_unless(c[1], tl)
            return
        if c[0] == "bool":
            if c[1]:
                a.jump("jmp", tl)
            return
        skip = a.new_label("skip")
        self.jump_unless(c, skip)
        a.jump("jmp", tl)
        a.label(skip)

    def _cmp_jump(self, op, fl):
        a = self.asm
        if self.ints:
            a.movq_rax_x0()
            a.i("movq rcx, xmm1")
            a.i("cmp rax, rcx")
            a.jump({None: "jne", "not": "je", "less than": self.cc("jge"), "greater than": self.cc("jle"),
                    "at least": self.cc("jl"), "at most": self.cc("jg")}[op], fl)
            return
        if op is None:
            a.ucomisd(0, 1)
            a.jump("jne", fl)
            a.jump("jp", fl)
        elif op == "not":
            ok = a.new_label("ok")
            a.ucomisd(0, 1)
            a.jump("jp", ok)
            a.jump("je", fl)
            a.label(ok)
        elif op == "less than":
            a.ucomisd(1, 0)
            a.jump("jbe", fl)
        elif op == "greater than":
            a.ucomisd(0, 1)
            a.jump("jbe", fl)
        elif op == "at least":
            a.ucomisd(0, 1)
            a.jump("jb", fl)
        else:
            a.ucomisd(1, 0)
            a.jump("jb", fl)

    # -- statements
    def blk(self, stmts):
        for st in stmts:
            self.stmt(st)

    def stmt(self, st):
        a, k = self.asm, st[0]
        self.at(st)
        n = self.node
        if k == "set" and st[2][0] == "index" and self.ints:
            self.store_elem_r(st[2][1][1], st[2][2], st[3], n)
        elif k == "set" and st[2][0] == "index":
            self.store_element(st[2][1][1], st[2][2], st[3], n)
        elif k == "set" and self.ints:
            self.set_r(st, n)
        elif k == "set":
            self.ex(st[3])
            a.store_x(self.var(st[2][1], n, write=True), 0)
        elif k == "aug" and self.ints and self.aug_r(st, n):
            pass
        elif k == "aug" and st[4][0] == "index":
            base, size = self.array(st[4][1][1], n)
            self.ex(st[3])
            a.push_x0()
            self.index(st[4][2], size)
            a.load_x_idx(0, base)
            a.pop_x(1)
            if self.ints:                                   # integer arithmetic uses rax and rdx: keep the index
                a._emit(b'\x50', "push rax")
            self.arith(st[2])
            if self.ints:
                a._emit(b'\x58', "pop rax")
            a.store_x_idx(base, 0)
        elif k == "aug":
            self.ex(st[3])
            a.movapd(1, 0)
            d = self.var(st[4][1], n)
            self.writes.add(st[4][1])
            a.load_x(0, d)
            self.arith(st[2])
            a.store_x(d, 0)
        elif k == "calc" and self.ints:
            self.exr(st[2])
            a.put(self.var(st[3][1], n, write=True), 0)
        elif k == "calc":
            self.ex(st[2])
            a.store_x(self.var(st[3][1], n, write=True), 0)
        elif k == "convert":
            self.ex(st[3])
            if st[2] == "number":                       # a character: keep its code, printing shows the letter
                a.store_x(self.var(st[4][1], n, write=True), 0)
                return
            bad, end = a.new_label("cvbad"), a.new_label("cvend")
            self.x0_to_rax()
            a.sub_rax_imm(48)
            a.cmp_rax_imm(9)
            a.jump("ja", bad)
            self.rax_to_x0()
            a.store_x(self.var(st[4][1], n, write=True), 0)
            a.mov_rax_imm64(1 if self.ints else f64_bits(1.0))
            a.store_rax(self.var("input_ok", n, write=True))
            a.jump("jmp", end)
            a.label(bad)
            a.mov_rax_imm64(0 if self.ints else 0x7FF8000000000000)
            a.store_rax(self.var(st[4][1], n, write=True))
            a.mov_rax_imm64(0)
            a.store_rax(self.var("input_ok", n, write=True))
            a.label(end)
        elif k == "alloc":
            self.allocate(st[2], int(st[3][1]), n, shared=len(st) > 4 and st[4] == "shared")
        elif k == "openf":
            path = st[2][1][0].encode("utf-8", "surrogateescape") + b"\0"
            a.lea_rdi_label(a.string(path))
            a.w("xor esi, esi")
            a.w("xor edx, edx")
            a.mov_eax(2)                                    # open(path, O_RDONLY)
            a.syscall()
            bad, done = a.new_label("noopen"), a.new_label("opened")
            a.i("test rax, rax")
            a.jump("js", bad)
            a.store_rax(self.hidden(FD_SLOT))
            a.store_imm_qword(self.hidden(PB_SLOT), -1)
            a.mov_rax_imm64(1 if self.ints else f64_bits(1.0))
            a.store_rax(self.var("input_ok", n, write=True))
            a.jump("jmp", done)
            a.label(bad)
            a.mov_rax_imm64(0)
            a.store_rax(self.var("input_ok", n, write=True))
            a.label(done)
        elif k == "openarr":                                # open the file named by ARR for reading (ARR = character codes, 0 at the end)
            if not self.ints:
                raise ZoomyError("'open the file named by' needs integer mode", n.file, n.line)
            base, size = self.array(st[2][1], n)
            if isinstance(base, SharedOff):
                a._emit(b'\x49\x8d\xb7' + _d32(int(base)), f"lea rsi, [r15{int(base):+d}]")
            else:
                a._emit(b'\x48\x8d\xb5' + _d32(base), f"lea rsi, [rbp{base:+d}]")
            a.call_rt(RT_OPENARR)
            bad, done = a.new_label("noopen"), a.new_label("opened")
            a.i("test rax, rax")
            a.jump("js", bad)
            a.store_rax(self.hidden(FD_SLOT))
            a.store_imm_qword(self.hidden(PB_SLOT), -1)
            a.mov_rax_imm64(1)
            a.store_rax(self.var("input_ok", n, write=True))
            a.jump("jmp", done)
            a.label(bad)
            a.mov_rax_imm64(0)
            a.store_rax(self.var("input_ok", n, write=True))
            a.label(done)
        elif k == "closef":
            skip = a.new_label("noclose")
            a.load_rax(self.hidden(FD_SLOT))
            a.i("test rax, rax")
            a.jump("je", skip)
            a.w("mov rdi, rax")
            a.mov_eax(3)
            a.syscall()
            a.label(skip)
            a.store_imm_qword(self.hidden(FD_SLOT), 0)
            a.store_imm_qword(self.hidden(PB_SLOT), -1)
        elif k == "seekf":
            self.ex(st[2])
            self.x0_to_rax()
            a.w("mov rsi, rax")
            a.w("xor edx, edx")
            a.load_rdi(self.hidden(FD_SLOT))
            a.mov_eax(8)                                    # lseek(fd, offset, SEEK_SET)
            a.syscall()
            a.store_imm_qword(self.hidden(PB_SLOT), -1)
        elif k == "fsize":
            a.w("xor esi, esi")
            a.mov_edx(2)
            a.load_rdi(self.hidden(FD_SLOT))
            a.mov_eax(8)                                    # lseek(fd, 0, SEEK_END) = the size
            a.syscall()
            a.store_imm_qword(self.hidden(PB_SLOT), -1)
            if self.ints:
                a.store_rax(self.var(st[2][1], n, write=True))
            else:
                a.cvtsi2sd_x0_rax()
                a.store_x(self.var(st[2][1], n, write=True), 0)
        elif k == "clock":
            a.call_rt(RT_CORES if len(st) > 3 else RT_CLOCK)
            if self.ints:
                a.store_rax(self.var(st[2][1], n, write=True))
            else:
                a.cvtsi2sd_x0_rax()
                a.store_x(self.var(st[2][1], n, write=True), 0)
        elif k == "syscall":                                # call the system with the phone number N using A and B ... and store the answer in x
            if not self.ints:
                raise ZoomyError("'call the system with the phone number' needs integer mode", n.file, n.line)
            self.ex(st[2])
            self.x0_to_rax()
            a._emit(b'\x50', "push rax")
            for arg in st[3]:
                self.ex(arg)
                self.x0_to_rax()
                a._emit(b'\x50', "push rax")
            regs = [b'\x5f', b'\x5e', b'\x5a', b'\x41\x5a', b'\x41\x58', b'\x41\x59']        # pop rdi, rsi, rdx, r10, r8, r9
            names = ["rdi", "rsi", "rdx", "r10", "r8", "r9"]
            for i in range(len(st[3]) - 1, -1, -1):
                a._emit(regs[i], "pop " + names[i])
            a._emit(b'\x58', "pop rax")
            a.syscall()
            if st[4] is not None:
                a.store_rax(self.var(st[4][1], n, write=True))
        elif k == "workers":
            self.start_workers(st, n)
        elif k == "waitw":
            a.w("mov rdi, -1")
            a.w("xor esi, esi")
            a.w("xor edx, edx")
            a.w("xor r10d, r10d")
            top = a.new_label("wait")
            a.label(top)
            a.mov_eax(61)
            a.syscall()
            a.i("test rax, rax")
            a.jump("jg", top)
            a.w("mov rdi, -1")
            a.w("xor esi, esi")
            a.w("xor edx, edx")
            a.w("xor r10d, r10d")
        elif k == "store" and self.ints:
            self.store_elem_r(st[2][1], st[3], st[4], n)
        elif k == "store":
            self.store_element(st[2][1], st[3], st[4], n)
        elif k == "load" and self.ints:
            self.load_elem(st[2][1], st[3])
            a.put(self.var(st[4][1], n, write=True), 0)
        elif k == "load":
            base, size = self.array(st[2][1], n)
            self.index(st[3], size)
            a.load_x_idx(0, base)
            a.store_x(self.var(st[4][1], n, write=True), 0)
        elif k == "read" and st[2] == "byte":
            a.lea_rdi_var(self.hidden(PB_SLOT))
            a.call_rt(RT_READ_BYTE)
            if self.ints:
                a.store_rax(self.var(st[3][1], n, write=True))
                a.store_rdx(self.var("input_ok", n, write=True))
            else:
                a.cvtsi2sd_x0_rax()
                a.store_x(self.var(st[3][1], n, write=True), 0)
                a.i("mov rax, rdx")
                a.cvtsi2sd_x0_rax()
                a.store_x(self.var("input_ok", n, write=True), 0)
        elif k == "read":
            a.lea_rdi_var(self.hidden(PB_SLOT))
            if self.ints:
                if st[2] == "num":
                    a.call_rt(RT_READ_I)
                else:
                    a.call_rt(RT_READCHAR)
                    a.i("mov rdx, rax")
                    a.cvttsd2si_rax_x0()          # the runtime hands the character back as a double
                a.store_rax(self.var(st[3][1], n, write=True))
                a.store_rdx(self.var("input_ok", n, write=True))
                return
            a.call_rt(RT_READ if st[2] == "num" else RT_READCHAR)
            a.store_x(self.var(st[3][1], n, write=True), 0)
            a.cvtsi2sd_x0_rax()
            a.store_x(self.var("input_ok", n, write=True), 0)
        elif k == "rterror":                                # (Big Numbers rewrite) print a runtime error and stop
            failing = len(st) > 3 and st[3] == 1            # Zoomy 8: `fail with` / `check that` - "zoomy: error:", exit code 1
            msg = (("zoomy: error: " if failing else "zoomy: runtime error: ") + st[2] + "\n").encode()
            a.lea_rsi_label(a.string(msg))
            a.mov_edx(len(msg))
            a.mov_edi(2)
            a.mov_eax(1)
            a.syscall()
            a.mov_edi(1 if failing else 255)
            a.mov_eax(60)
            a.syscall()
        elif k == "warnmsg":                                # Zoomy 8: `warn with` - one line on standard error, then carry on
            msg = ("zoomy: warning: " + st[2] + "\n").encode()
            a.lea_rsi_label(a.string(msg))
            a.mov_edx(len(msg))
            a.mov_edi(2)
            a.mov_eax(1)
            a.syscall()
        elif k == "unread":                                 # (Big Numbers rewrite) push a character back onto the input
            self.exr(st[2])
            a.store_rax(self.hidden(PB_SLOT))
        elif k == "print":
            self._aprint(st)
        elif k == "if":
            if len(st) > 5 and st[5] == "vec" and self.ints and self.try_vector(st, n):
                return
            end = a.new_label("endif")
            if st[4] is None:
                self.jump_unless(st[2], end)
                self.blk(st[3])
            else:
                els = a.new_label("else")
                self.jump_unless(st[2], els)
                self.blk(st[3])
                a.jump("jmp", end)
                a.label(els)
                self.blk(st[4])
            a.label(end)
        elif k == "while" and self.ints:
            body, test, end = a.new_label("loop"), a.new_label("looptest"), a.new_label("endloop")
            a.jump("jmp", test)
            a.label(body)
            self.loops.append((test, end))
            self.blk(st[3])
            self.loops.pop()
            a.label(test)
            self.jump_if(st[2], body)
            a.label(end)
        elif k == "while":
            top, end = a.new_label("loop"), a.new_label("endloop")
            a.label(top)
            self.jump_unless(st[2], end)
            self.loops.append((top, end))
            self.blk(st[3])
            self.loops.pop()
            a.jump("jmp", top)
            a.label(end)
        elif k == "for":
            self.for_loop(st, n)
        elif k == "foreach":
            self.foreach_loop(st, n)
        elif k == "repeat":
            self.repeat_loop(st, n)
        elif k == "return":
            self.exr(st[2]) if self.ints else self.ex(st[2])
            a.jump("jmp", f"F_{self.cur_fn}_ret")
        elif k == "exprstmt":
            self.exr(st[2]) if self.ints else self.ex(st[2])
        elif k == "callstore" and self.ints:
            self.exr(st[2])
            a.put(self.var(st[3][1], n, write=True), 0)
        elif k == "callstore":
            self.ex(st[2])
            a.store_x(self.var(st[3][1], n, write=True), 0)
        elif k in ("define", "global"):
            pass
        elif k == "stop":
            a.jump("jmp", self.loops[-1][1])
        elif k == "skip":
            a.jump("jmp", self.loops[-1][0])
        elif k == "scope":
            self.blk(st[2])
        elif k == "pass":
            pass
        elif k == "finish":
            if st[2] is None:
                a.xor_edi()
            else:
                self.ex(st[2])
                self.x0_to_rdi()
            a.mov_eax(60)
            a.syscall()
        elif k == "run":
            rname = st[2]
            if rname not in self.routines:
                raise ZoomyError(f"unknown routine '{rname}'", n.file, n.line)
            if rname not in self.compiled and rname not in self.pending:
                self.pending.append(rname)
            a.call(f"R_{rname}")
        elif k == "runwith":
            fname = st[2]
            if fname not in self.externs:
                raise ZoomyError(f"'{fname}' is not a declared extern (add 'extern {fname}' at the top)", n.file, n.line)
            self.ex(st[3])
            if not self.check_only:
                a.align_call_extern(fname)
            a.store_x(self.var(f"{fname}_result", n, write=True), 0)
        elif k in ("routine", "extern"):
            pass
        else:
            raise ZoomyError(f"internal error: cannot compile '{k}' natively", n.file, n.line)

    # -- arrays, loops and functions
    def store_element(self, name, key, value, n):
        """store VALUE in ARRAY at index KEY  (the key is worked out first, like the Python backend)"""
        a = self.asm
        base, size = self.array(name, n)
        if value[0] == "var" and not (value[1] == "pi" and "pi" not in self.assigned):
            self.index(key, size)
            self.load_simple(1, value)
        elif key[0] in ("num", "var"):
            self.ex(value)
            a.movapd(1, 0)
            self.index(key, size)
        else:
            self.ex(key)
            a.push_x0()
            self.ex(value)
            a.movapd(1, 0)
            a.pop_x(0)
            self.x0_to_rax()
            a.cmp_rax_imm(size)
            a.jump_rt("jae", RT_INDEX_ERR)
        a.store_x_idx(base, 1)

    VEX_OP = {"add": 0xD4, "subtract": 0xFB, "and": 0xDB, "or": 0xEB, "xor": 0xEF}

    def _vmov(self, store, ymm, base):
        """vmovdqu ymm, [array + rax*8]  /  vmovdqu [array + rax*8], ymm  (private arrays from rbp, shared ones from r15)"""
        a = self.asm
        op = 0x7F if store else 0x6F
        modrm = 0x84 | (ymm << 3)
        text = (f"vmovdqu ymmword ptr [r15+rax*8{int(base):+d}], ymm{ymm}" if store and isinstance(base, SharedOff) else
                f"vmovdqu ymm{ymm}, ymmword ptr [r15+rax*8{int(base):+d}]" if isinstance(base, SharedOff) else
                f"vmovdqu ymmword ptr [rbp+rax*8{base:+d}], ymm{ymm}" if store else
                f"vmovdqu ymm{ymm}, ymmword ptr [rbp+rax*8{base:+d}]")
        if isinstance(base, SharedOff):
            a._emit(b'\xc4\xc1\x7e' + bytes([op, modrm, 0xc7]) + _d32(int(base)), text)
        else:
            a._emit(b'\xc5\xfe' + bytes([op, modrm, 0xc5]) + _d32(base), text)

    def try_vector(self, st, n):
        """the 'vector ...' statements as AVX2 (four 64-bit lanes at once); False keeps the four scalar statements"""
        a = self.asm
        spec = st[6]
        op = spec[0]
        groups = spec[1:3] + (spec[3],) if op != "sum" else (spec[1],)
        info = []
        for arr, pos in groups:
            if arr[1] not in self.arrays:
                return False
            base, size = self.array(arr[1], n)
            if size < 4:
                return False
            info.append((base, size, pos))
        if op == "sum" and spec[2][0] != "var":
            return False
        for base, size, pos in info:                       # work out and check every first slot before touching a vector register
            self.index(pos, size - 3)
            a._emit(b'\x50', "push rax")
        if op == "sum":
            a._emit(b'\x58', "pop rax")
            self._vmov(False, 0, info[0][0])
            a._emit(b'\xc4\xe3\x7d\x39\xc1\x01', "vextracti128 xmm1, ymm0, 1")
            a._emit(b'\xc5\xf9\xd4\xc1', "vpaddq xmm0, xmm0, xmm1")
            a._emit(b'\xc5\xf9\x70\xc8\x4e', "vpshufd xmm1, xmm0, 78")
            a._emit(b'\xc5\xf9\xd4\xc1', "vpaddq xmm0, xmm0, xmm1")
            a._emit(b'\xc4\xe1\xf9\x7e\xc0', "vmovq rax, xmm0")
            a._emit(b'\xc5\xf8\x77', "vzeroupper")
            a.store_rax(self.var(spec[2][1], n, write=True))
            return True
        a._emit(b'\x5e', "pop rsi")
        a._emit(b'\x5a', "pop rdx")
        a._emit(b'\x59', "pop rcx")
        a._emit(b'\x48\x89\xc8', "mov rax, rcx")
        self._vmov(False, 0, info[0][0])
        a._emit(b'\x48\x89\xd0', "mov rax, rdx")
        self._vmov(False, 1, info[1][0])
        a._emit(b'\xc5\xfd' + bytes([self.VEX_OP[op], 0xc1]), f"vp{ {'add': 'addq', 'subtract': 'subq', 'and': 'and', 'or': 'or', 'xor': 'xor'}[op] } ymm0, ymm0, ymm1")
        a._emit(b'\x48\x89\xf0', "mov rax, rsi")
        self._vmov(True, 0, info[2][0])
        a._emit(b'\xc5\xf8\x77', "vzeroupper")
        return True

    LOOP_KINDS = ("for", "foreach", "repeat", "while")

    def try_unroll(self, st, n):
        """--unroll: for i from 0 to 7 with plain whole-number bounds becomes eight copies of the body, each preceded by
        'set i to <that value>' (no counter, no compare, no jump back).  Anything unusual keeps the ordinary loop."""
        lo, hi, step = st[3], st[4], st[5] if st[5] is not None else ["num", 1.0]
        if not all(isinstance(e, list) and e[0] == "num" for e in (lo, hi, step)):
            return False
        try:
            lo, hi, step = (float(e[1]) for e in (lo, hi, step))
        except (TypeError, ValueError):
            return False
        if any(v != int(v) or abs(v) > 1 << 40 for v in (lo, hi, step)) or step == 0:
            return False
        lo, hi, step = int(lo), int(hi), int(step)
        if self.uns and min(lo, hi, step) < 0:
            return False
        values = list(range(lo, hi + (1 if step > 0 else -1), step))
        if len(values) > UNROLL:
            return False

        def jumps(node):
            if isinstance(node, list):
                if node and node[0] in self.LOOP_KINDS and len(node) > 1 and isinstance(node[1], int):
                    return False
                if len(node) == 2 and node[0] in ("stop", "skip") and isinstance(node[1], int):
                    return True
                return any(jumps(x) for x in node)
            return False
        if jumps(st[6]):
            return False
        a = self.asm
        slot = self.var(st[2], n, write=True)
        for v in values:
            if self.ints:
                a.mov_rax_imm64(v & 0xFFFFFFFFFFFFFFFF)
            else:
                a.mov_rax_imm64(f64_bits(float(v)))
            a.store_rax(slot)
            self.blk(st[6])
        return True

    def for_loop(self, st, n):
        """for i from A to B [by S]:   (same count and values as the Python backend's _zfrange)"""
        a = self.asm
        if UNROLL and self.try_unroll(st, n):
            return
        if self.ints:
            return self.for_loop_int(st, n)
        ta, tb, ts, tn, tk = (self.temp() for _ in range(5))
        self.ex(st[3])
        a.store_x(ta, 0)
        self.ex(st[4])
        a.store_x(tb, 0)
        if st[5] is None:
            a.mov_rax_imm64(f64_bits(1.0))
            a.movq_x_rax(0)
        else:
            self.ex(st[5])
        a.store_x(ts, 0)
        # a step that is zero or NaN, or a NaN bound, is an error
        self.zero_x(1)
        a.load_x(0, ts)
        a.ucomisd(0, 1)
        a.jump_rt("jp", RT_ERR_STEP)
        a.jump_rt("je", RT_ERR_STEP)
        for t in (ta, tb):
            a.load_x(0, t)
            a.ucomisd(0, 0)
            a.jump_rt("jp", RT_ERR_STEP)
        # n = floor((b - a) / s * (1 + 1e-12) + 1e-12) + 1 when (b - a) / s >= 0, else 0
        a.load_x(0, tb)
        a.load_x(1, ta)
        a.alu("subsd", 0, 1)
        a.load_x(1, ts)
        a.alu("divsd", 0, 1)
        zero_n, have_n = a.new_label("fz"), a.new_label("fn")
        self.zero_x(1)
        a.ucomisd(0, 1)
        a.jump("jp", zero_n)
        a.jump("jb", zero_n)
        a.mov_rax_imm64(f64_bits(1 + 1e-12))
        a.movq_x_rax(1)
        a.alu("mulsd", 0, 1)
        a.mov_rax_imm64(f64_bits(1e-12))
        a.movq_x_rax(1)
        a.alu("addsd", 0, 1)
        a.roundsd(0, 9)
        a.mov_rax_imm64(f64_bits(1e12))
        a.movq_x_rax(1)
        a.ucomisd(0, 1)                                     # floor(...) >= 1e12  <=>  n > 1e12
        a.jump_rt("jae", RT_ERR_LONG)
        a.mov_rax_imm64(f64_bits(1.0))
        a.movq_x_rax(1)
        a.alu("addsd", 0, 1)
        a.jump("jmp", have_n)
        a.label(zero_n)
        self.zero_x(0)
        a.label(have_n)
        a.store_x(tn, 0)
        self.zero_x(0)
        a.store_x(tk, 0)
        top, step, end = a.new_label("for"), a.new_label("forstep"), a.new_label("endfor")
        a.label(top)
        a.load_x(0, tk)
        a.load_x(1, tn)
        a.ucomisd(0, 1)
        a.jump("jae", end)
        a.load_x(1, ts)
        a.alu("mulsd", 0, 1)
        a.load_x(1, ta)
        a.alu("addsd", 1, 0)
        a.store_x(self.var(st[2], n, write=True), 1)
        self.loops.append((step, end))
        self.blk(st[6])
        self.loops.pop()
        a.label(step)
        a.load_x(0, tk)
        a.mov_rax_imm64(f64_bits(1.0))
        a.movq_x_rax(1)
        a.alu("addsd", 0, 1)
        a.store_x(tk, 0)
        a.jump("jmp", top)
        a.label(end)

    def foreach_loop(self, st, n):
        """for each x in ARRAY:  walks every slot (the program never writes the array inside the loop: checked in zoomy_py)"""
        a = self.asm
        base, size = self.array(st[3][1], n)
        tk = self.temp()
        if self.ints:
            return self.foreach_int(st, n, base, size, tk)
        self.zero_x(0)
        a.store_x(tk, 0)
        top, step, end = a.new_label("each"), a.new_label("eachstep"), a.new_label("endeach")
        a.label(top)
        a.load_x(0, tk)
        self.x0_to_rax()
        a.cmp_rax_imm(size)
        a.jump("jae", end)
        a.load_x_idx(0, base)
        a.store_x(self.var(st[2], n, write=True), 0)
        self.loops.append((step, end))
        self.blk(st[4])
        self.loops.pop()
        a.label(step)
        a.load_x(0, tk)
        a.mov_rax_imm64(f64_bits(1.0))
        a.movq_x_rax(1)
        a.alu("addsd", 0, 1)
        a.store_x(tk, 0)
        a.jump("jmp", top)
        a.label(end)

    def repeat_loop(self, st, n):
        a = self.asm
        top, end = a.new_label("rep"), a.new_label("endrep")
        if st[2] is None:
            a.label(top)
            self.loops.append((top, end))
            self.blk(st[3])
            self.loops.pop()
            a.jump("jmp", top)
            a.label(end)
            return
        tc = self.temp()
        if self.ints:
            self.exr(st[2])
        else:
            self.ex(st[2])
            self.x0_to_rax()
        a.cmp_rax_imm(0)
        a.jump_rt(self.cc("jl"), RT_ERR_COUNT)
        a.store_rax(tc)
        a.label(top)
        if self.ints:
            a.ivar("cmp", tc, ("imm", 0))
            a.jump(self.cc("jle"), end)
            a.ivar("sub", tc, ("imm", 1))
        else:
            a.load_rax(tc)
            a.cmp_rax_imm(0)
            a.jump(self.cc("jle"), end)
            a.sub_rax_imm(1)
            a.store_rax(tc)
        self.loops.append((top, end))
        self.blk(st[3])
        self.loops.pop()
        a.jump("jmp", top)
        a.label(end)

    def call_function(self, e):
        """f(a, b): the arguments are pushed in order; the function's entry code takes them off the stack"""
        a = self.asm
        name = e[1][1]
        if name not in self.fdefs:
            raise ZoomyError(f"internal error: unknown function '{name}'", self.node.file, self.node.line)
        for arg in e[2]:
            if self.ints:
                o = self.opnd(arg)
                if o is not None and o[0] == "var":
                    a.push_mem(o[1])                            # push the variable itself
                else:
                    self.exr(arg)
                    a.push_r(0)
            else:
                self.ex(arg)
                a.push_x0()
        if name not in self.compiled and name not in self.pending:
            self.pending.append(name)
        a.call(f"F_{name}")                                     # integer mode: the answer comes back in rax

    def compile_function(self, name):
        """the body, then an entry stub that saves the variables of a recursive function, takes the arguments off the stack,
        runs the body and restores the variables"""
        a, f = self.asm, self.fdefs[name]
        self.cur_fn, self.cur_temps = name, []
        self.node = _At(self.prog.file, f[1])
        a.scope = name
        saved_map = a.regmap
        mine = self.leaf_map.get(name)
        if mine:                                              # a leaf function keeps its busiest variables in scratch registers
            a.regmap = {**saved_map, **mine}
        t0 = len(a.text)
        a.label(f"F_{name}_body")
        self.blk(f[4])
        a.label(f"F_{name}_ret")
        a.ret()
        if a.counts is not None:
            body = "\n".join(a.text[t0:])
            a.callee_ok[name] = name not in self.recursive and not re.search(r"\.byte|\b(rbx|r12|r13|r14|ebx|r12d|r13d|r14d)\b", body)
            a.leaf_ok[name] = not re.search(r"\bcall\b|syscall|\brep\b|\.byte|\b(rsi|rdi|esi|edi|r8|r9|r10|r11|r8d|r9d|r10d|r11d)\b", body)
        params = f[3]
        local_slots = [self.var(p, self.node, write=True) for p in params]
        saved = []
        if name in self.recursive:
            names = sorted(self.locals_of(f))
            saved = [self.vars[v] for v in names if v in self.vars] + list(self.cur_temps)
            saved = list(dict.fromkeys(saved))
        a.label(f"F_{name}")
        cregs = sorted(set(mine.values()) & {3, 12, 13, 14}) if mine else []
        for r in cregs:                                       # the callee-saved registers this function uses for its variables
            a.push_r(r)
        for d in saved:
            a.push_mem(d)
        if name in self.recursive:
            a.ivar("add", self.depth_slot, ("imm", 1))
            limit = max(50, min(100000, 3_000_000 // (8 * (len(saved) + len(params) + 4))))
            a.ivar("cmp", self.depth_slot, ("imm", limit))
            a.jump_rt("jg", RT_ERR_DEEP)
        for j, d in enumerate(local_slots):
            off = 8 * (len(saved) + len(cregs)) + 8 + 8 * (len(params) - 1 - j)
            if self.ints:
                a.load_rsp(0, off)
                a.put(d, 0)
            else:
                a.load_x_rsp(0, off)
                a.store_x(d, 0)
        a.call(f"F_{name}_body")
        if name in self.recursive:
            a.ivar("sub", self.depth_slot, ("imm", 1))
        for d in reversed(saved):
            a.pop_mem(d)
        for r in reversed(cregs):
            a.pop_r(r)
        a.ret_imm(8 * len(params))
        a.regmap = saved_map
        a.scope = None
        self.cur_fn, self.cur_temps = None, None

    def _write_bytes(self, data):
        a = self.asm
        if data:
            label = a.string(data)
            a.mov_eax(1)
            a.mov_edi(1)
            a.lea_rsi_label(label)
            a.mov_edx(len(data))
            a.syscall()

    def _write_flag(self, e):
        """a yes/no value prints as yes / no"""
        a = self.asm
        no, end = a.new_label("no"), a.new_label("endflag")
        self.jump_unless(e, no)
        self._write_bytes(b"yes")
        a.jump("jmp", end)
        a.label(no)
        self._write_bytes(b"no")
        a.label(end)

    def _write_char(self, e):
        a = self.asm
        self.ex(e)
        self.x0_to_rax()
        a.store_rax(self.hidden(CH_SLOT))
        a.mov_eax(1)
        a.mov_edi(1)
        a.lea_rsi_var(self.hidden(CH_SLOT))
        a.mov_edx(1)
        a.syscall()

    def _risky(self, e):
        """can evaluating this expression fail or print something (an array lookup or a function call)?"""
        hit = []
        _zpy().walk(e, lambda x: hit.append(1) if x[0] in ("index", "call") else None)
        return bool(hit)

    def _pre(self, e):
        """evaluate e now into a hidden slot and give back a variable node that reads it"""
        self.pre_count += 1
        name = f"pre#{self.pre_count}"
        self.vars[name] = self.temp()
        self.writes.add(name)
        self.ex(e)
        self.asm.store_x(self.vars[name], 0)
        if self.is_flag(e):
            self.flag_temps.add(name)
        return ["var", name]

    def _print_segment(self, seg, newline):
        """The Python backend works out everything one print writes before writing any of it, so an error (or a function that
        prints) inside the statement never leaves half a line behind.  Do the same: when a risky value is involved,
        evaluate every value first, in order, then write."""
        a = self.asm
        if any(self._risky(p) for e in seg for p in (e[1] if e[0] == "str" else [e]) if not isinstance(p, str)):
            new = []
            for e in seg:
                if e[0] == "str":
                    parts = []
                    for p in e[1]:
                        parts.append(p if isinstance(p, str) or (p[0] == "var" and p[1] in self.char_vars) or p[0] == "num"
                                     else self._pre(p))
                    new.append(["str", parts])
                elif (e[0] == "var" and e[1] in self.char_vars) or e[0] == "num":
                    new.append(e)
                else:
                    new.append(self._pre(e))
            seg = new
        for e in seg:
            if e[0] == "str":
                for p in e[1]:
                    if isinstance(p, str):
                        self._write_bytes(p.encode("utf-8", "surrogateescape"))
                    elif p[0] == "var" and p[1] in self.char_vars:
                        self._write_char(p)
                    elif self.is_flag(p):
                        self._write_flag(p)
                    else:
                        self.ex(p)
                        self.print_num()
            elif e[0] == "var" and e[1] in self.char_vars:
                self._write_char(e)
            elif self.is_flag(e):
                self._write_flag(e)
            else:
                self.ex(e)
                self.print_num()
        if newline:
            self._write_bytes(b"\n")

    def _aprint(self, st):
        seg = []
        for kind, e in st[3]:
            if kind == "char":
                self._print_segment(seg, False)
                seg = []
                self._write_char(e)
            else:
                seg.append(e)
        self._print_segment(seg, bool(st[2]))

    # -- whole program
    def compile(self):
        a, prog = self.asm, self.prog
        self.externs = {s[2] for s in prog.stmts if s[0] == "extern"}
        for s in prog.stmts:
            if s[0] == "routine":
                self.routines[s[2]] = s
            elif s[0] == "define":
                self.fdefs[s[2]] = s
        self.recursive = self.find_recursion({**self.routines, **self.fdefs})
        self.depth_slot = self.temp()
        main = []
        for s in prog.stmts:
            if s[0] == "action":
                main += s[2]
            elif s[0] not in ("routine", "define", "use", "usefrom", "extern"):
                main.append(s)
        a.prologue()
        for r in sorted(set(a.regmap.values())):         # --regs: the variables kept in registers start at 0
            a._emit(bytes([_rex(r, r), 0x31, 0xc0 | (r & 7) << 3 | (r & 7)]), f"xor {REG_NAMES[r]}, {REG_NAMES[r]}")
        a.store_imm_qword(self.hidden(PB_SLOT), -1)
        if any(x[0] == "alloc" and len(x) > 4 and x[4] == "shared" for x in _zpy().all_stmts(prog.stmts)):
            a.shared_prologue()
        self.blk(main)
        a.xor_edi()
        a.mov_eax(60)
        a.syscall()
        self.in_routine = True
        while self.pending:
            name = self.pending.pop(0)
            self.compiled.add(name)
            if name in self.fdefs:
                self.compile_function(name)
                continue
            a.label(f"R_{name}")
            self.blk(self.routines[name][3])
            a.ret()
        a.patch_frame(max(16, (self.slots * 8 + 15) // 16 * 16))
        a.patch_shared(max(4096, (self.sh_slots * 8 + 4095) // 4096 * 4096))
        for name, (file, line) in sorted(self.reads.items(), key=lambda kv: kv[1]):
            if name not in self.writes and not name.endswith("_result") and name != "pi":
                self.warnings.append(f"{file}:{line}: warning: variable '{name}' is read but never set (it is always 0)")
        return a


def _zpy():
    import zoomy_py
    return zoomy_py


# =============================================================================
# Output: static ELF, or assembly text for gcc
# =============================================================================
ELF_BASE = 0x400000
ELF_HEADERS = 64 + 56


def build_elf(asm):
    """Lay out [code][runtime][strings] and resolve every rel32. Returns the finished ELF image."""
    image = bytearray(asm.code)
    labels = dict(asm.labels)
    if asm.uses_rt:
        while len(image) % 16:
            image.append(0xcc)
        labels["rt"] = len(image)
        image += runtime_blob()
    for label, data in asm.strings:
        labels[label] = len(image)
        image += data
    for pos, label, addend in asm.fixups:
        if label not in labels:
            raise ZoomyError(f"internal error: undefined label {label}")
        struct.pack_into('<i', image, pos, labels[label] + addend - (pos + 4))
    size = ELF_HEADERS + len(image)
    ehdr = b'\x7fELF' + bytes([2, 1, 1, 0]) + bytes(8) + struct.pack(
        '<HHIQQQIHHHHHH', 2, 0x3e, 1, ELF_BASE + ELF_HEADERS, 64, 0, 0, 64, 56, 1, 0, 0, 0)
    phdr = struct.pack('<IIQQQQQQ', 1, 5, 0, ELF_BASE, ELF_BASE, size, size, 0x200000)
    return bytes(ehdr + phdr + image)


def build_asm_text(asm):
    lines = [".intel_syntax noprefix", ".text", ".globl main", "main:"] + asm.text
    for label, data in asm.strings:
        lines.append(f"{label}:")
        lines.extend("    .byte " + ", ".join(str(b) for b in data[i:i + 16]) for i in range(0, len(data), 16))
    if asm.uses_rt:
        blob = runtime_blob()
        lines.append("rt:")
        lines.extend("    .byte " + ", ".join(str(b) for b in blob[i:i + 16]) for i in range(0, len(blob), 16))
    lines.append('.section .note.GNU-stack,"",@progbits')
    return "\n".join(lines) + "\n"


# =============================================================================
# Command line
# =============================================================================
USAGE = """Usage: python3 zoomy.py <program.zmy> [options]      (Zoomy 8)

  -o <name>    output file (default: the program name without .zmy; a .py name forces the Python backend)
  fmt FILE     (a command of its own) put a program in one consistent style: python3 zoomy.py fmt --help
  --explain    show how every line was read: 'I read this as ...', and why (no compile)
  --trace[=N]  run the program on the Python backend, showing each line as it runs and the variables it changed (first N steps, default 200)
  --run        run the program after compiling and exit with its exit code (arguments after --)
  --native     force the native backend (refuses programs that need Python)
  --python     force the Python backend (--py prints the generated Python)
  --asm        print the generated assembly instead of building
  --gcc        force gcc mode (needed only to call libc/libm via 'extern'; auto-selected then)
  --ints       use 64-bit integers instead of floats (same as 'from now on, use integers instead of floats' at the top)
  --unroll[=N] optimization: a 'for' with whole-number bounds written out and at most N repeats (default 16) is
               compiled as straight-line copies of its body (native backend; stop/skip inside keep the loop)
  --regs       optimization: keep the four most used variables in CPU registers (rbx, r12, r13, r14) instead of memory
  --unsigned   use unsigned 64-bit integers (same as 'from now on, use unsigned integers instead of floats' at the top)
  --big        use Big Numbers: whole numbers of 1024 bits (same as 'from now on, use Big Numbers instead of floats'; all backends)
  --bigdec     use Big Decimals: binary numbers with a 1024-bit mantissa, whole and fractional (same as 'from now on, use Big Decimals instead of floats'; all backends)
  --floats     use floats (the default; overrides a file that asks for integers)
  --strict     grammar slips (a/an, is/are, ordinal nouns) stop the compile instead of warning
  --classic    compile with the old text-grammar compiler (old programs only)
  --wasm       build a WebAssembly (WASI) module instead of a Linux program: it runs on any system with a WASI runtime
               (Node.js, wasmtime, wasmer, browsers).  Number-only programs only; output name: <program>.wasm
  --wasm-html  build one web page that contains the program and runs it in the browser (<program>.html)
  --wasm-depth N   how many calls a recursive function may nest in WebAssembly before the 'too many nested calls' error
  --version    print the compiler version
"""


def default_output(path):
    base = os.path.basename(path)
    for ext in (".zmy.txt", ".zmy"):
        if base.endswith(ext):
            return base[:-len(ext)] or "zoomy_app"
    return base + ".out"


def allocate_registers(comp):
    """--regs: compile once to count how often each variable slot is used (uses inside loops and routines count more),
    then compile again with the four most used slots living in rbx, r12, r13 and r14 (the runtime keeps those intact).
    Slots whose address is taken, and the hidden slots the runtime reads, stay in memory."""
    prog = comp.prog
    comp.asm.counts = {}
    comp.asm.weight_fn = lambda: (8 ** min(len(comp.loops), 3)) * (4 if (comp.cur_fn or comp.in_routine) else 1)
    comp.compile()
    asm1 = comp.asm
    skip = set(asm1.pinned) | {comp.hidden(i) for i in range(8)}
    ranked = sorted(((n, d) for d, n in asm1.counts.items() if d not in skip), reverse=True)
    regs = (3, 12, 13, 14)
    fresh = AstCompiler(prog)
    fresh.asm.regmap = {d: regs[i] for i, (n, d) in enumerate(ranked[:4])}
    return fresh


def allocate_leaf_registers(comp):
    """Zoomy 6.3: a function that calls nothing keeps its busiest private variables in the scratch registers rsi, rdi and r8-r11.
    Compile once to find the leaf functions and count how often each variable is used, then compile again with the mapping."""
    prog = comp.prog
    comp.asm.counts = {}
    comp.asm.weight_fn = lambda: (8 ** min(len(comp.loops), 3)) * (4 if comp.in_routine else 1)
    comp.compile()
    a1 = comp.asm
    skip = set(a1.pinned) | {comp.hidden(i) for i in range(8)}
    leaf_map = {}
    for fname, cnt in a1.fn_counts.items():
        if fname is None:
            continue
        own = [(n, d) for d, n in cnt.items() if d not in skip and a1.slot_scopes.get(d) == {fname}]
        own.sort(key=lambda t: (-t[0], str(t[1])))
        if a1.leaf_ok.get(fname):
            if own:
                leaf_map[fname] = {d: r for (n, d), r in zip(own, (8, 9, 10, 11, 6, 7))}
        elif a1.callee_ok.get(fname) and CALLEEREGS:
            hot = [(n, d) for n, d in own if n >= CALLEE_MIN][:4]
            if hot:
                leaf_map[fname] = {d: r for (n, d), r in zip(hot, (3, 12, 13, 14))}
    fresh = AstCompiler(prog)
    fresh.leaf_map = leaf_map
    return fresh


def Compiler_fresh(src, nodes):
    c = Compiler(src)
    c.load(nodes, os.path.dirname(os.path.abspath(src)))
    return c


def _show_error(e, path):
    """the error line, and a whole-sentence suggestion under it when one reads"""
    print(f"[Error] {e}")
    if isinstance(path, str) and os.path.isfile(path):
        import zoomy_suggest
        h = zoomy_suggest.hint(path, e)
        if h:
            print(h)


def run_python_backend(src, backend, out_name, run, show_py, prog_args, ints=None):
    """Compile with the full-language front end when needed. Returns an exit code, or None to use the native compiler."""
    import zoomy_py
    try:
        prog = zoomy_py.load_program(src, ints)
    except zoomy_py.ZoomyError as e:
        _show_error(e, src)
        return 1
    if backend in ("auto", "native") and prog.native_ok:
        return AstCompiler(prog)
    if backend in ("auto", "native") and not (getattr(prog, "big", False) or getattr(prog, "bd", False)) and not os.environ.get("ZOOMY_NO_HEAP"):
        import zoomy_heap
        try:
            return AstCompiler(zoomy_heap.lower(prog))              # Zoomy 8: text, lists and tables natively
        except zoomy_heap.Unsupported as why:
            prog.heap_why = str(why)
    if backend == "native" and (getattr(prog, "big", False) or getattr(prog, "bd", False)):
        import zoomy_big
        if not prog.big_native_ok:
            print("[Error] this " + ("Big Decimals" if prog.bd else "Big Numbers") + " program uses things the native (machine-code) compiler cannot do yet "
                  "(text values, lists, tables, functions that give no value back, files, workers, ...); "
                  "drop --native to build it with the Python backend")
            return 1
        try:
            return AstCompiler(zoomy_big.lower(prog, zoomy_big.NATIVE_SLOTS))
        except zoomy_py.ZoomyError as e:
            print(f"[Error] {e}")
            return 1
    if backend == "native":
        why = getattr(prog, "why_not", None)
        where = ""
        if why:
            where = f" (the first line it cannot take is {os.path.basename(src)}:{why[0]}, a '{why[1]}' statement)"
        if getattr(prog, "heap_why", None):
            where += f" [text, lists and tables natively: not possible here - {prog.heap_why}]"
        print("[Error] this program uses things the native (machine-code) compiler cannot do yet "
              "(text values, lists, tables, functions, loops over lists, Python libraries, ...)" + where + "; "
              "drop --native to build it with the Python backend")
        return 1
    if prog.uses_extern:
        print("[Error] 'extern' (C libraries) needs the native compiler, which cannot run text, lists or Python libraries")
        return 1
    try:
        text, _ = zoomy_py.compile_python(prog, lambda m: print("[Warning] " + m, file=sys.stderr))
    except zoomy_py.ZoomyError as e:
        _show_error(e, src)
        return 1
    if show_py:
        sys.stdout.write(text)
        return 0
    if run and not out_name:
        sys.stdout.flush()
        g = {"__name__": "__main__"}
        saved = sys.argv
        sys.argv = [src] + prog_args
        try:
            exec(compile(text, os.path.basename(src) + ".py", "exec"), g)
        except SystemExit as e:
            return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        finally:
            sys.argv = saved
        return 0
    out_name = out_name or (default_output(src) + ".py")
    with open(out_name, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(out_name, 0o755)
    print(f"[Success] Standalone Python program created: {out_name}")
    if run:
        import subprocess as sp
        return sp.call([sys.executable, out_name] + prog_args)
    return 0


def build_wasm(src, out_name, run, ints, mode, depth):
    """--wasm / --wasm-html: the number-only subset as a WebAssembly (WASI) module"""
    import zoomy_py
    import zoomy_wasm
    try:
        prog = zoomy_py.load_program(src, ints)
        if getattr(prog, "big", False) or getattr(prog, "bd", False):
            import zoomy_big
            if not prog.big_native_ok:
                print("[Error] this " + ("Big Decimals" if prog.bd else "Big Numbers") + " program uses things the WebAssembly backend cannot do (text values, lists, "
                      "tables, Python libraries, ...): it handles the same number-only programs as the native compiler")
                return 1
            prog = zoomy_big.lower(prog, zoomy_big.WASM_SLOTS)
        if not prog.native_ok:
            print("[Error] this program uses things the WebAssembly backend cannot do (text values, lists, tables, "
                  "Python libraries, ...): it handles the same number-only programs as the native compiler")
            return 1
        wasm = zoomy_wasm.compile_program(prog, depth or zoomy_wasm.MAX_DEPTH)
    except zoomy_py.ZoomyError as e:
        _show_error(e, src)
        return 1
    base = default_output(src)
    html = mode == "--wasm-html"
    out_name = out_name or base + (".html" if html else ".wasm")
    try:
        with open(out_name, "w" if html else "wb", **({"encoding": "utf-8"} if html else {})) as f:
            f.write(zoomy_wasm.html_page(base, wasm) if html else wasm)
    except OSError as e:
        print(f"[Error] {e}")
        return 1
    print(f"[Success] WebAssembly {'web page' if html else 'module'} created: {out_name} ({os.path.getsize(out_name)} bytes)")
    if run:
        if html:
            print("[Error] --run works with --wasm (open the .html file in a browser to run it)")
            return 1
        cmd = zoomy_wasm.find_runner(out_name)
        if cmd is None:
            print("[Error] --run needs Node.js, wasmtime or wasmer to run a WebAssembly program (the module was still built)")
            return 1
        sys.stdout.flush()
        return subprocess.call(cmd)
    return 0


FMT_USAGE = """Usage: python3 zoomy.py fmt <file.zmy> [more files] [options]
  (no option)  print the formatted program
  -w, --write  rewrite the files in place (only the ones that change)
  --check      change nothing; exit 1 if a file is not formatted (for scripts and CI)
  --diff       show what would change
  --no-verify  skip the safety check (by default the formatted program must compile to the same code as the original)"""


def fmt_command(args):
    """zoomy.py fmt: one consistent style (see zoomy_fmt.py)"""
    import difflib
    import zoomy_fmt
    files = [a for a in args if not a.startswith("-")]
    flags = {a for a in args if a.startswith("-")}
    if not files or flags - {"-w", "--write", "--check", "--diff", "--no-verify", "-h", "--help"} or "-h" in flags or "--help" in flags:
        print(FMT_USAGE)
        return 0 if ("-h" in flags or "--help" in flags) else 1
    code = 0
    for path in files:
        if not os.path.isfile(path):
            print(f"[Error] no such file: {path}")
            code = 1
            continue
        old = open(path, encoding="utf-8").read()
        new, problem = zoomy_fmt.format_file(path, verify="--no-verify" not in flags)
        if problem:
            print(f"[Error] {path}: {problem}")
            code = 1
            continue
        changed = new != old
        if "--check" in flags:
            if changed:
                print(f"{path}: would be reformatted")
                code = 1
        elif "--diff" in flags:
            sys.stdout.writelines(difflib.unified_diff(old.splitlines(True), new.splitlines(True), path, path + " (formatted)"))
        elif "-w" in flags or "--write" in flags:
            if changed:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new)
                print(f"formatted {path}")
        else:
            sys.stdout.write(new)
    return code


def trace_program(src, ints, limit, prog_args):
    """--trace: run the program (on the Python backend) and show every line as it runs, with the variables it changed"""
    import zoomy_py
    try:
        prog = zoomy_py.load_program(src, ints)
        if prog.uses_extern:
            print("[Error] --trace cannot follow a program that uses 'extern' (C libraries)")
            return 1
        text, zmap = zoomy_py.compile_python(prog, lambda m: print("[Warning] " + m, file=sys.stderr))
    except zoomy_py.ZoomyError as e:
        _show_error(e, src)
        return 1
    with open(src, encoding="utf-8") as f:
        source = f.read().splitlines()
    fname = os.path.basename(src) + ".trace.py"
    g = {"__name__": "__main__"}
    state = {"steps": 0, "last": None, "stopped": False, "depth": 0}
    first_user_line = min(zmap) if zmap else 1

    def user_vars(frame):
        out = {}
        for scope in (g, frame.f_locals):
            for k, v in scope.items():
                if k.startswith("z_") and not callable(v) or (k.startswith("z_") and isinstance(v, type)):
                    name = re.sub(r"__\d+$", "", k[2:])
                    out[name] = v
        return out

    def show(v):
        try:
            t = g["_zshow"](v, True)
        except Exception:
            t = repr(v)
        t = t.replace("\n", " ")
        return t if len(t) <= 70 else t[:67] + "..."

    def report(frame, label_depth):
        """the variables that changed since the last report"""
        if state["last"] is None:
            return
        now = {k: show(v) for k, v in user_vars(frame).items()}
        before, ind = state["last"], "      " + "  " * label_depth
        for k, v in now.items():
            if before.get(k) != v:
                print(f"{ind}{k} = {v}")
        state["last"] = now

    def flush():
        if "_zflush" in g:
            g["_zflush"]()

    def tracer(frame, event, arg):
        if frame.f_code.co_filename != fname or state["stopped"]:
            return None
        if frame.f_code.co_name != "<module>" and frame.f_code.co_firstlineno < first_user_line:
            return None                                   # the runtime's own functions
        if event == "call":
            state["depth"] += 1
            return tracer
        if event == "return":
            flush()
            report(frame, state["depth"] - 1)
            state["depth"] -= 1
            return tracer
        if event != "line":
            return tracer
        sl = zmap.get(frame.f_lineno)
        if sl is None or sl == state.get("line") and state.get("frame") is frame:
            return tracer
        if 0 < sl <= len(source) and re.match(r"(?i)(define|routine|action)\b", source[sl - 1].strip()):
            return tracer                                  # only makes the function: nothing to follow yet
        flush()
        report(frame, state["depth"] - 1)
        state["line"], state["frame"] = sl, frame
        state["steps"] += 1
        if state["steps"] > limit:
            state["stopped"] = True
            print(f"[trace stopped after {limit} steps; use --trace=N to see more; the program runs on without it]")
            return None
        if state["last"] is None:
            state["last"] = {k: show(v) for k, v in user_vars(frame).items()}
        label = source[sl - 1].strip() if 0 < sl <= len(source) else ""
        print(f"[line {sl}] " + "  " * (state["depth"] - 1) + label)
        return tracer

    sys.stdout.flush()
    saved = sys.argv
    sys.argv = [src] + prog_args
    code = 0
    try:
        compiled = compile(text, fname, "exec")
        sys.settrace(tracer)
        try:
            exec(compiled, g)
        finally:
            sys.settrace(None)
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    finally:
        sys.argv = saved
    try:
        g["_zflush"]()
    except Exception:
        pass
    return code


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--version" in argv:
        print(f"Zoomy {VERSION}")
        return 0
    if argv and argv[0] == "fmt":
        return fmt_command(argv[1:])
    if not argv or "-h" in argv or "--help" in argv:
        print(USAGE)
        return 0 if argv else 1
    out_name, run, show_asm, force_gcc, src = None, False, False, False, None
    backend, show_py, prog_args, ints = "auto", False, [], None
    wasm_mode, wasm_depth = None, None
    explain, trace = False, 0
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--":
            prog_args = argv[i + 1:]
            break
        if arg == "--python":
            backend = "python"
        elif arg == "--native":
            backend = "native"
        elif arg == "--classic":
            backend = "classic"
        elif arg == "--ints":
            ints = "int"
        elif arg == "--unsigned":
            ints = "uint"
        elif arg == "--big":
            ints = "big"
        elif arg == "--bigdec":
            ints = "bigdec"
        elif arg == "--floats":
            ints = "float"
        elif arg == "--unroll" or arg.startswith("--unroll="):
            global UNROLL
            try:
                UNROLL = int(arg.split("=", 1)[1]) if "=" in arg else 16
            except ValueError:
                print(f"[Error] --unroll=N needs a whole number, like --unroll=16")
                return 1
        elif arg == "--regs":
            global REGS
            REGS = True
        elif arg == "--strict":
            _zpy().STRICT = True
        elif arg == "--py":
            show_py, backend = True, "python"
        elif arg == "-o":
            if i + 1 >= len(argv):
                print("[Error] missing file name after -o")
                return 1
            out_name = argv[i + 1]
            i += 1
        elif arg == "--run":
            run = True
        elif arg == "--explain":
            explain = True
        elif arg == "--trace" or arg.startswith("--trace="):
            try:
                trace = int(arg.split("=", 1)[1]) if "=" in arg else 200
            except ValueError:
                print("[Error] --trace=N needs a whole number (how many steps to show), like --trace=50")
                return 1
        elif arg in ("--wasm", "--wasm-html"):
            wasm_mode = arg
        elif arg == "--wasm-depth":
            if i + 1 >= len(argv) or not argv[i + 1].isdigit() or int(argv[i + 1]) < 1:
                print("[Error] --wasm-depth needs a whole number, like --wasm-depth 5000")
                return 1
            wasm_depth = int(argv[i + 1])
            i += 1
        elif arg == "--asm":
            show_asm = True
        elif arg == "--gcc":
            force_gcc = True
        elif arg.startswith("-"):
            print(f"[Error] unknown option {arg}\n{USAGE}")
            return 1
        elif src is None:
            src = arg
        else:
            print(f"[Error] unexpected argument {arg}")
            return 1
        i += 1
    if src is None:
        print(USAGE)
        return 1
    if not os.path.isfile(src):
        print(f"[Error] input file '{src}' not found")
        return 1
    if explain:
        import zoomy_py
        with open(src, encoding="utf-8") as f:
            sys.stdout.write(zoomy_py.explain(f.read(), os.path.basename(src)))
        return 0
    if trace:
        return trace_program(src, ints, trace, prog_args)
    if wasm_mode:
        return build_wasm(src, out_name, run, ints, wasm_mode, wasm_depth)
    if out_name and out_name.endswith(".py") and backend == "auto":
        backend = "python"
    comp = None
    if backend != "classic":
        r = run_python_backend(src, backend, out_name, run, show_py, prog_args, ints)
        if isinstance(r, int):
            return r
        comp = r
    out_name = out_name or default_output(src)

    try:
        if comp is None:
            with open(src, encoding="utf-8") as f:
                nodes = parse_source(f.read(), src)
            comp = Compiler(src)
            comp.load(nodes, os.path.dirname(os.path.abspath(src)))
        can_regs = isinstance(comp, AstCompiler) and not force_gcc and not any(st[0] == "extern" for st in comp.prog.stmts)
        if REGS and can_regs:
            comp = allocate_registers(comp)
        elif can_regs and LEAFREGS:
            comp = allocate_leaf_registers(comp)
        asm = comp.compile()
        for w in comp.warnings:
            print(w, file=sys.stderr)
        use_gcc = force_gcc or bool(comp.externs)
        if show_asm:
            sys.stdout.write(build_asm_text(asm))
            return 0
        if use_gcc:
            print("[Compiler] 'extern' functions in use: building with gcc..." if comp.externs
                  else "[Compiler] --gcc: building with gcc...")
            with tempfile.TemporaryDirectory() as tmp:
                s_file = os.path.join(tmp, "zoomy_build.s")
                with open(s_file, "w") as f:
                    f.write(build_asm_text(asm))
                rc = subprocess.call(["gcc", s_file, "-lm", "-no-pie", "-o", out_name])
            if rc != 0:
                print("[Error] gcc failed to assemble/link the program")
                return 1
            print(f"[Success] Dynamically-linked native executable created: {out_name}")
        else:
            image = build_elf(asm)
            with open(out_name, "wb") as f:
                f.write(image)
            os.chmod(out_name, 0o755)
            print(f"[Success] Zero-dependency static ELF created: {out_name} ({len(image)} bytes)")
    except ZoomyError as e:
        print(f"[Error] {e}")
        return 1
    except (OSError, UnicodeDecodeError) as e:
        print(f"[Error] {e}")
        return 1

    if run:
        if not (sys.platform.startswith("linux") and os.uname().machine in ("x86_64", "AMD64")):
            print("[Error] --run needs Linux on x86-64 (the program was still built)")
            return 1
        sys.stdout.flush()
        return subprocess.call([os.path.abspath(out_name)])
    return 0


if __name__ == "__main__":
    sys.exit(main())
