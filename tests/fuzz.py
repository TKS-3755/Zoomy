#!/usr/bin/env python3
"""Differential fuzzer for the Zoomy compiler.

Random programs are generated as an abstract tree, rendered to Zoomy source, compiled, and run;
the same tree is evaluated by an independent reference interpreter written here (it never looks at
the Zoomy text, so parser bugs cannot hide). Output bytes, exit code and runtime errors must match.

    python3 tests/fuzz.py [count] [--gcc N] [--seed S]
"""
import math
import os
import random
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import zoomy  # noqa: E402

INF = float("inf")
NAN = float("nan")
M64 = (1 << 64) - 1


# ----------------------------------------------------------------------------- reference semantics
def to_int64(x):
    """cvttsd2si: truncate toward zero; out of range / NaN -> 0x8000000000000000."""
    if x != x or abs(x) >= 2.0 ** 63:
        return -(1 << 63)
    return int(x)


def fdiv(a, b):
    try:
        return a / b
    except ZeroDivisionError:
        if a != a or a == 0:
            return NAN
        neg = (math.copysign(1.0, a) < 0) != (math.copysign(1.0, b) < 0)
        return -INF if neg else INF


def fsqrt(x):
    if x != x:
        return x
    if x < 0:
        return NAN
    return math.sqrt(x)


def _signed_round(x, fn):
    """Apply floor/ceil/trunc keeping IEEE signed zeros (roundsd returns -0.0 for e.g. ceil(-0.5))."""
    if x != x or x in (INF, -INF):
        return x
    r = float(fn(x))
    return math.copysign(0.0, x) if r == 0 else r


def ftrunc(x):
    return _signed_round(x, math.trunc)


def ffloor(x):
    return _signed_round(x, math.floor)


def fceil(x):
    return _signed_round(x, math.ceil)


def frem(a, b):
    q = ftrunc(fdiv(a, b))
    return a - b * q


def frac_digits(fd):
    return b"." + f"{fd:06d}".rstrip("0").encode()


def fmt(x):
    """Reference for rt_print_f64."""
    if x != x:
        return b"nan"
    bits = struct.unpack('<Q', struct.pack('<d', x))[0]
    sign = bits >> 63
    bits &= ~(1 << 63)
    a = struct.unpack('<d', struct.pack('<Q', bits))[0]
    if bits == 0x7FF0000000000000:
        return b"-inf" if sign else b"inf"
    if bits == 0:
        return b"0"
    out = b"-" if sign else b""
    if 0x3EB0C6F7A0B5ED8D <= bits < 0x430C6BF526340000:
        ip = int(a)
        fd = round((a - float(ip)) * 1e6)
        if fd >= 1000000:
            ip += 1
            fd -= 1000000
        out += str(ip).encode()
        if fd:
            out += frac_digits(fd)
        return out
    e, m = 0, a
    while m >= 10.0:
        m /= 10.0
        e += 1
    while m < 1.0:
        m *= 10.0
        e -= 1
    ip = int(m)
    fd = round((m - float(ip)) * 1e6)
    if fd >= 1000000:
        ip += 1
        fd -= 1000000
    if ip >= 10:
        ip, e = 1, e + 1
    out += str(ip).encode()
    if fd:
        out += frac_digits(fd)
    return out + b"e" + (b"-" if e < 0 else b"+") + (b"0" if abs(e) < 10 else b"") + str(abs(e)).encode()


class Stdin:
    def __init__(self, data):
        self.data, self.pos, self.pb = data, 0, -1

    def getc(self):
        if self.pb != -1:
            c, self.pb = self.pb, -1
            return c
        if self.pos >= len(self.data):
            return -1
        c = self.data[self.pos]
        self.pos += 1
        return c

    @staticmethod
    def ws(c):
        return c == 32 or 9 <= c <= 13

    def read_f64(self):
        while True:
            c = self.getc()
            if c == -1:
                return 0.0, 0
            if not self.ws(c):
                break
        neg = False
        if c == ord('-'):
            neg, c = True, self.getc()
        elif c == ord('+'):
            c = self.getc()
        m, digits, frac, dot = 0.0, 0, 0, False
        while c != -1:
            if 48 <= c <= 57:
                m = m * 10.0 + float(c - 48)
                digits += 1
                if dot:
                    frac += 1
                c = self.getc()
            elif c == ord('.') and not dot:
                dot = True
                c = self.getc()
            else:
                self.pb = c
                break
        if digits == 0:
            self.pb = -1
            return 0.0, 0
        p = 1.0
        for _ in range(frac):
            p *= 10.0
        m = m / p
        return (-m if neg else m), 1

    def read_char(self):
        while True:
            c = self.getc()
            if c == -1:
                return 0.0, 0
            if not self.ws(c):
                return float(c), 1


def arith(op, a, b):
    if op == "plus":
        return a + b
    if op == "minus":
        return a - b
    if op == "times":
        return a * b
    if op == "divide":
        return fdiv(a, b)
    if op == "mod":
        return a - b * ffloor(fdiv(a, b))
    n, r, x = int(abs(b)), 1.0, a              # pow: whole exponents only in the fuzzer
    while n:
        if n & 1:
            r *= x
        x *= x
        n >>= 1
    return fdiv(1.0, r) if math.copysign(1.0, b) < 0 else r


class Halt(Exception):
    def __init__(self, code, stderr=b""):
        self.code, self.stderr = code, stderr


class Stop(Exception):
    pass


class Skip(Exception):
    pass


class Ret(Exception):
    def __init__(self, value):
        self.value = value


def frange(a, b, s):
    """the values of `for x from a to b by s` (same rule as the runtime's _zfrange)"""
    if s == 0 or s != s or a != a or b != b:
        raise Halt(255, b"zoomy: runtime error: a 'for' loop needs a step that is not zero\n")
    q = (b - a) / s
    n = 0
    if q >= 0:
        t = q * (1 + 1e-12) + 1e-12
        if t >= 1e12:
            raise Halt(255, b"zoomy: runtime error: this 'for' loop would run too long\n")
        n = math.floor(t) + 1
    for i in range(n):
        yield a + i * s


class Ref:
    def __init__(self, prog, stdin):
        self.prog, self.out = prog, bytearray()
        self.vars = {}
        self.arrays = {name: [0.0] * size for name, size in prog["arrays"].items()}
        self.stdin = Stdin(stdin)
        self.vars["input_ok"] = 0.0
        self.flags = {}
        self.funcs = prog.get("funcs", {})

    def val(self, o):
        kind, v = o[0], o[1]
        if kind == "var":
            return self.vars.get(v, 0.0)
        if kind == "ex":
            return self.ev(o[2])
        if kind == "call":
            return self.callf(v, [self.val(a) for a in o[2]])
        if kind == "elem":
            return self.arrays[v][self.idx(v, o[2])]
        if kind == "alen":
            return float(len(self.arrays[v]))
        if kind == "aend":
            return self.arrays[v][0 if o[2] == "first" else -1]
        return v if kind == "lit" else float(ord(v))

    def callf(self, name, args):
        f = self.funcs[name]
        saved, self.vars = self.vars, {"input_ok": self.vars.get("input_ok", 0.0)}
        for p, x in zip(f["params"], args):
            self.vars[p] = x
        try:
            self.block(f["body"])
            raise AssertionError("function without give back")
        except Ret as r:
            return r.value
        finally:
            self.vars = saved

    def ev(self, n):
        k = n[0]
        if k == "n":
            return self.val(n[1])
        if k == "paren":
            return self.ev(n[1])
        if k == "neg":
            return -self.ev(n[1])
        if k == "fn":
            return {"square root": fsqrt, "absolute value": abs, "floor": ffloor, "ceiling": fceil}[n[1]](self.ev(n[2]))
        if k == "bin":
            return arith(n[1], self.ev(n[2]), self.ev(n[3]))
        acc = self.ev(n[1])                     # chain: strictly left to right
        for op, atom in n[2]:
            acc = arith(op, acc, self.ev(atom))
        return acc

    def run(self):
        try:
            self.block(self.prog["main"])
            return bytes(self.out), 0, b""
        except Halt as h:
            return bytes(self.out), h.code, h.stderr

    def cond(self, c):
        if c[0] == "flagvar":
            return self.flags.get(c[1], False)
        if c[0] == "and":
            return self.cond(c[1]) and self.cond(c[2])
        if c[0] == "or":
            return self.cond(c[1]) or self.cond(c[2])
        if c[0] == "not":
            return not self.cond(c[1])
        a, op, b = self.val(c[0]), c[1], self.val(c[2])
        return {None: a == b, "not": a != b, "less than": a < b, "greater than": a > b,
                "at least": a >= b, "at most": a <= b}[op]

    @staticmethod
    def multi_stmt(op, target, opd):
        return ("add", opd, target) if op == "add" else ("sub", opd, target) if op == "sub" else (op, target, opd)

    def idx(self, arr, o):
        i = to_int64(self.val(o))
        if not 0 <= i < len(self.arrays[arr]):
            raise Halt(255, b"zoomy: runtime error: array index out of range\n")
        return i

    def block(self, stmts):
        v = self.vars
        for s in stmts:
            k = s[0]
            if k == "let":
                v[s[1]] = 0.0
            elif k == "set":
                v[s[1]] = self.val(s[2])
            elif k == "add":
                v[s[2]] = v.get(s[2], 0.0) + self.val(s[1])
            elif k == "sub":
                v[s[2]] = v.get(s[2], 0.0) - self.val(s[1])
            elif k == "mul":
                v[s[1]] = v.get(s[1], 0.0) * self.val(s[2])
            elif k == "div":
                v[s[1]] = fdiv(v.get(s[1], 0.0), self.val(s[2]))
            elif k == "unary":
                x = self.val(s[2])
                v[s[3]] = {"square root": fsqrt, "absolute value": abs, "floor": ffloor, "ceiling": fceil}[s[1]](x)
            elif k == "rem":
                v[s[3]] = frem(self.val(s[1]), self.val(s[2]))
            elif k == "store":
                value = self.val(s[1])
                self.arrays[s[2]][self.idx(s[2], s[3])] = value
            elif k == "load":
                v[s[3]] = self.arrays[s[1]][self.idx(s[1], s[2])]
            elif k == "print":
                # like the compiled programs: everything between two `char` items is worked out before any of it is written
                seg = []

                def emit(newline):
                    vals = []
                    for what, x in seg:
                        vals.append(x if what == "str" else (b"yes" if self.cond(x) else b"no") if what == "flag"
                                    else fmt(self.val(x)))
                    for x in vals:
                        self.out += x
                    if newline:
                        self.out += b"\n"
                    seg.clear()
                for what, x in s[2]:
                    if what == "char":
                        emit(False)
                        self.out.append(to_int64(self.val(x)) & 0xFF)
                    else:
                        seg.append((what, x))
                emit(s[1] == "print")
            elif k in ("read", "readchar"):
                x, ok = self.stdin.read_f64() if k == "read" else self.stdin.read_char()
                v[s[1]] = x
                v["input_ok"] = float(ok)
            elif k == "if":
                self.block(s[2] if self.cond(s[1]) else (s[3] or []))
            elif k == "while":
                while self.cond(s[1]):
                    self.block(s[2])
            elif k == "for":
                _, c, A, B, S, body = s
                a_, b_ = self.val(A), self.val(B)
                for x in frange(a_, b_, self.val(S) if S else 1.0):
                    v[c] = x
                    try:
                        self.block(body)
                    except Skip:
                        continue
                    except Stop:
                        break
            elif k == "repeat":
                n = to_int64(self.val(s[1]))
                if n < 0:
                    raise Halt(255, b"zoomy: runtime error: a count cannot be negative\n")
                for _ in range(n):
                    try:
                        self.block(s[2])
                    except Skip:
                        continue
                    except Stop:
                        break
            elif k == "repeatf":
                while True:
                    try:
                        self.block(s[1])
                    except Skip:
                        continue
                    except Stop:
                        break
            elif k == "foreach":
                for x in list(self.arrays[s[2]]):
                    v[s[1]] = x
                    try:
                        self.block(s[3])
                    except Skip:
                        continue
                    except Stop:
                        break
            elif k == "stop":
                raise Stop()
            elif k == "skip":
                raise Skip()
            elif k == "giveback":
                raise Ret(self.val(s[1]))
            elif k == "setelem":
                key, value = self.val(s[2]), self.val(s[3])
                self.arrays[s[1]][self.idx(s[1], ("lit", key))] = value
            elif k == "augelem":
                _, op, arr, idx, val_ = s
                i = self.idx(arr, idx)
                x = self.val(val_)
                cur = self.arrays[arr][i]
                self.arrays[arr][i] = cur + x if op == "add" else cur - x if op == "sub" else cur * x if op == "mul" else fdiv(cur, x)
            elif k == "callstmt":
                r_ = self.callf(s[1], [self.val(a) for a in s[2]])
                if s[3]:
                    v[s[3]] = r_
            elif k == "fset":
                self.flags[s[1]] = self.cond(s[2])
            elif k == "scope":
                self.block(s[1])
            elif k == "pipe":
                self.block(s[1])
            elif k == "multi":
                for t in s[2]:
                    self.block([self.multi_stmt(s[1], t, s[3])])
            elif k == "convert":
                c = to_int64(self.val(s[1]))
                if 48 <= c <= 57:
                    v[s[2]], v["input_ok"] = float(c - 48), 1.0
                else:
                    v[s[2]], v["input_ok"] = NAN, 0.0
            elif k == "run":
                self.block(self.prog["routines"][s[1]])
            elif k == "finish":
                raise Halt((to_int64(self.val(s[1])) if s[1] else 0) & 0xFF)
            else:
                raise AssertionError(k)


# ----------------------------------------------------------------------------- rendering
def lit_text(x):
    return repr(x)


import zlib

OPW = {"plus": ["plus", "+"], "minus": ["minus", "-"], "times": ["times", "*", "×"],
       "divide": ["divided by", "/", "÷"], "mod": ["mod", "modulo", "%"], "pow": ["^", "**", "to the power of"]}
PREC = {"plus": 1, "minus": 1, "times": 2, "divide": 2, "mod": 2, "pow": 4}


def opword(op, node):
    ws = OPW[op]
    return ws[zlib.crc32(repr(node).encode()) % len(ws)]


def leaf_text(o, paren_neg):
    t = opd_text(o)
    return f"({t})" if paren_neg and t.startswith("-") else t


def rx_lin(n, top=True):
    """text of a conversational-mode tree: chains read left to right, so no precedence is involved."""
    k = n[0]
    if k == "n":
        return leaf_text(n[1], False)
    if k == "paren":
        return "(" + rx_lin(n[1]) + ")"
    if k == "neg":
        return "-" + atom_lin(n[1])
    if k == "fn":
        return f"{n[1]} of " + atom_lin(n[2], True)
    parts = [atom_lin(n[1])]
    for op, atom in n[2]:
        parts += [opword(op, atom), atom_lin(atom)]
    return " ".join(parts)


def atom_lin(n, operand=False):
    k = n[0]
    if k == "n":
        t = opd_text(n[1])
        return f"({t})" if operand and t.startswith("-") else t
    if k == "paren":
        return "(" + rx_lin(n[1]) + ")"
    if k == "neg":
        return "(" + rx_lin(n) + ")" if operand else "-" + atom_lin(n[1], True)
    if k == "fn":
        return f"{n[1]} of " + atom_lin(n[2], True)
    return "(" + rx_lin(n) + ")"


def rx_str(n, need=0, right_of_pow=False):
    """text of a structural-mode tree with the minimum parentheses its precedence needs."""
    k = n[0]
    if k == "n":
        return leaf_text(n[1], True)
    if k == "fn":
        return f"{n[1]} of " + rx_str(n[2], 5)
    if k == "neg":
        t = "-" + rx_str(n[1], 4)
        return "(" + t + ")" if need > 3 else t
    if k == "paren":
        return "(" + rx_str(n[1]) + ")"
    op, l, r = n[1], n[2], n[3]
    p = PREC[op]
    if op == "pow":
        t = f"{rx_str(l, 5)} {opword(op, n)} {rx_str(r, 3)}"
    else:
        t = f"{rx_str(l, p)} {opword(op, n)} {rx_str(r, p + 1)}"
    return "(" + t + ")" if need > p else t


def ex_text(o):
    return rx_lin(o[2]) if o[1] == "lin" else rx_str(o[2])


def idx_text(o):
    t = opd_text(o)
    return t if o[0] == "var" else f"({t})"


def opd_text(o):
    if o[0] == "ex":
        return ex_text(o)
    kind, v = o[0], o[1]
    if kind == "call":
        return f"{v}(" + ", ".join(opd_text(a) for a in o[2]) + ")"
    if kind == "elem":
        return f"item {idx_text(o[2])} of {v}"
    if kind == "alen":
        return f"length of {v}"
    if kind == "aend":
        return f"{o[2]} of {v}" if STYLE == "simply" else f"the {o[2]} of {v}"
    if kind == "var":
        return v
    if kind == "lit":
        return lit_text(v)
    return {"\n": "'\\n'", "\t": "'\\t'", "\\": "'\\\\'", "'": "'\\''"}.get(v, f"'{v}'")


def cond_text(c, nested=False):
    if c[0] == "flagvar":
        return c[1]
    if c[0] == "and" or c[0] == "or":
        t = f"{cond_text(c[1], True)} {c[0]} {cond_text(c[2], True)}"
        return f"({t})" if nested else t
    if c[0] == "not":
        return f"not ({cond_text(c[1])})"
    op = c[1]
    t = f"{opd_text(c[0])} is {op + ' ' if op else ''}{opd_text(c[2])}"
    return f"({t})" if nested else t


def str_text(b):
    return '"' + b.decode().replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t") + '"'


def pexp(o):
    return f"({opd_text(o)})" if o[0] == "ex" else opd_text(o)


def clause_text(c, subject):
    """one pipeline clause; the subject may be left out when it is the variable the previous clause changed."""
    k = c[0]
    if k == "set":
        return f"set {c[1]} to {opd_text(c[2])}", c[1]
    if k in ("add", "sub"):
        verb, joiner = ("add", "to") if k == "add" else ("subtract", "from")
        if c[2] == subject:
            return f"{verb} {opd_text(c[1])}", c[2]
        return f"{verb} {opd_text(c[1])} {joiner} {c[2]}", c[2]
    verb = "multiply" if k == "mul" else "divide"
    if c[1] == subject:
        return f"{verb} by {opd_text(c[2])}", c[1]
    return f"{verb} {c[1]} by {opd_text(c[2])}", c[1]


IN_FUNC = False
STYLE = "english"          # english | simply (the old rules under 'Simply,') | classic (old rules, no wrapper)
FILLER = "set v0 to v0"


def rng_verb(s):
    return ("Let", "Create", "Define", "make")[zlib.crc32(repr(s).encode()) % 4]


def decl_text(name, s):
    """the sentence that makes a number called NAME (one of the four spellings, picked by a hash of the statement)"""
    verb = rng_verb(s)
    if verb == "make" and IN_FUNC:                     # a function's own variables must stay its own (recursion)
        verb = "Let"
    if verb == "make":
        return f"make {name} a global number"
    return f"{verb} a number " + {"Let": "be called", "Create": "named", "Define": "as"}[verb] + f" {name}"


def render_block(stmts, ind):
    pad = "    " * ind
    lines = []
    for s in stmts:
        k = s[0]
        if k == "set":
            lines.append(f"{pad}set {s[1]} to {opd_text(s[2])}")
        elif k == "add":
            lines.append(f"{pad}add {opd_text(s[1])} to {s[2]}")
        elif k == "sub":
            lines.append(f"{pad}subtract {opd_text(s[1])} from {s[2]}")
        elif k == "mul":
            lines.append(f"{pad}multiply {s[1]} by {opd_text(s[2])}")
        elif k == "div":
            lines.append(f"{pad}divide {s[1]} by {opd_text(s[2])}")
        elif k == "unary":
            lines.append(f"{pad}calculate the {s[1]} of {pexp(s[2])} and store the result in {s[3]}")
        elif k == "rem":
            lines.append(f"{pad}calculate remainder of {pexp(s[1])} divided by {pexp(s[2])} and store the result in {s[3]}")
        elif k == "store":
            lines.append(f"{pad}store {opd_text(s[1])} in {s[2]} at index {opd_text(s[3])}")
        elif k == "load":
            lines.append(f"{pad}load from {s[1]} at index {opd_text(s[2])} into {s[3]}")
        elif k == "print":
            items = []
            for what, x in s[2]:
                items.append(str_text(x) if what == "str" else (f"char {opd_text(x)}" if what == "char" else
                                                                cond_text(x, True) if what == "flag" else opd_text(x)))
            lines.append(f"{pad}{s[1]} " + ", ".join(items))
        elif k == "scope":
            head = "Structurally," if zlib.crc32(repr(s).encode()) % 2 else "Structurally:"
            lines.append(pad + head)
            lines += render_block(s[1], ind + 1) or [f"{pad}    {FILLER}"]
        elif k == "pipe":
            texts, subject = [], None
            for c in s[1]:
                t, subject = clause_text(c, subject)
                texts.append(t)
            lines.append(pad + " and ".join(texts))
        elif k == "multi":
            names = " and ".join(s[2])
            verb = {"add": f"add {opd_text(s[3])} to {names}", "sub": f"subtract {opd_text(s[3])} from {names}",
                    "mul": f"multiply {names} by {opd_text(s[3])}", "div": f"divide {names} by {opd_text(s[3])}"}[s[1]]
            lines.append(pad + verb)
        elif k == "let":
            if STYLE != "english":
                continue
            lines.append(pad + decl_text(s[1], s))
        elif k == "convert":
            lines.append(f"{pad}convert the character {opd_text(s[1])} to a number and store the result in {s[2]}")
        elif k == "read":
            lines.append(f"{pad}read {s[1]}")
        elif k == "readchar":
            lines.append(f"{pad}read the next character into {s[1]}")
        elif k == "if":
            lines.append(f"{pad}if {cond_text(s[1])}:")
            lines += render_block(s[2], ind + 1) or [f"{pad}    {FILLER}"]
            if s[3] is not None:
                lines.append(f"{pad}else:")
                lines += render_block(s[3], ind + 1) or [f"{pad}    {FILLER}"]
        elif k == "while":
            lines.append(f"{pad}while {cond_text(s[1])}:")
            lines += render_block(s[2], ind + 1)
        elif k == "run":
            lines.append(f"{pad}run {s[1]}")
        elif k == "for":
            lines.append(f"{pad}for {s[1]} from {opd_text(s[2])} to {opd_text(s[3])}" + (f" by {opd_text(s[4])}" if s[4] else "") + ":")
            lines += render_block(s[5], ind + 1) or [f"{pad}    {FILLER}"]
        elif k == "repeat":
            lines.append(f"{pad}repeat {opd_text(s[1])} times:")
            lines += render_block(s[2], ind + 1) or [f"{pad}    {FILLER}"]
        elif k == "repeatf":
            lines.append(f"{pad}repeat forever:")
            lines += render_block(s[1], ind + 1) or [f"{pad}    {FILLER}"]
        elif k == "foreach":
            lines.append(f"{pad}for each {s[1]} in {s[2]}:")
            lines += render_block(s[3], ind + 1) or [f"{pad}    {FILLER}"]
        elif k in ("stop", "skip"):
            lines.append(pad + k)
        elif k == "giveback":
            lines.append(f"{pad}give back {opd_text(s[1])}")
        elif k == "setelem":
            lines.append(f"{pad}set item {idx_text(s[2])} of {s[1]} to {opd_text(s[3])}")
        elif k == "augelem":
            _, op, arr, idx, val_ = s
            place = f"item {idx_text(idx)} of {arr}"
            if STYLE == "simply":                      # the old grammar has no `add 1 to item 2 of list`
                sym = {"add": "+", "sub": "-", "mul": "*", "div": "/"}[op]
                lines.append(f"{pad}set {place} to {place} {sym} ({opd_text(val_)})")
                continue
            lines.append(pad + {"add": f"add {opd_text(val_)} to {place}", "sub": f"subtract {opd_text(val_)} from {place}",
                                "mul": f"multiply {place} by {opd_text(val_)}", "div": f"divide {place} by {opd_text(val_)}"}[op])
        elif k == "callstmt":
            args = " and ".join(opd_text(a) for a in s[2])
            lines.append(f"{pad}call {s[1]}" + (f" with {args}" if args else "") + (f" and store the result in {s[3]}" if s[3] else ""))
        elif k == "fset":
            lines.append(f"{pad}set {s[1]} to {cond_text(s[2])}")
        elif k == "finish":
            lines.append(f"{pad}finish" + (f" with {opd_text(s[1])}" if s[1] else ""))
    return lines


def render(prog):
    lines = []
    if STYLE == "english":
        lines += [decl_text(v, ("v", v)) for v in prog["vars"]]
        arr = (("Create", "named"), ("Create", "for"), ("Define", "for"))
        lines += [" ".join(("%s an array %s %s with %d slots" % (*arr[zlib.crc32(name.encode()) % 3], name, size)).split())
                  for name, size in prog["arrays"].items()]
    if STYLE == "english":
        lines += [f"Let a flag be called {f}" for f in prog.get("flags", [])]
    for name, f in prog.get("funcs", {}).items():
        lines.append(f"define {name}" + (" with " + " and ".join(f["params"]) if f["params"] else "") + ":")
        globals()["IN_FUNC"] = True
        lines += render_block(f["body"], 1)
        globals()["IN_FUNC"] = False
    for name, body in prog["routines"].items():
        lines.append(f"routine {name}:")
        lines += render_block(body, 1) or [f"    {FILLER}"]
    if STYLE == "english":
        lines.append("action start:")
    else:
        lines.append("action start:")
        for name, size in prog["arrays"].items():
            lines.append(f"    allocate array {name} with {size} slots")
    lines += [f"    set {f} to no" for f in prog.get("flags", [])]
    lines += render_block(prog["main"], 1)
    text = "\n".join(lines) + "\n"
    if STYLE == "simply":
        text = "Simply,\n" + "".join(("    " + l if l.strip() else l) for l in text.splitlines(True))
    return text


# ----------------------------------------------------------------------------- generator
class Gen:
    LITS = [0.0, 1.0, -1.0, 2.0, 0.5, 3.0, 7.0, 10.0, -2.5, 100.0, 255.0, 256.0, 1e6, 1e15, 1e16, 123456.789,
            1e300, -1e300, 1e-7, 1e-6, 5e-324, 0.1, 0.3, 1 / 3, 2.5e-5, 99999.9999996, 9.9999996, 4503599627370496.0,
            9.2e18, 3e9, 65.0, 43.0, 3.14159265358979]
    CHARS = ["a", "Z", "+", "#", " ", "\n", "\\", "'", "0", "~"]

    def __init__(self, rng):
        self.r = rng
        self.vars = [f"v{i}" for i in range(6)]
        self.arrays = {"a0": self.r.choice([1, 3, 5]), "a1": self.r.choice([2, 4])}
        self.loop_names = iter(f"c{i}" for i in range(1000))
        self.mode = "lin"
        self.pool_extra = []                 # loop variables in scope (read and assigned like any variable)
        self.funcs, self.callable_funcs, self.rec_funcs = {}, {}, []
        self.loop_ok = [False]               # may `stop` / `skip` appear here?  False | "stop" | True (both)
        self.frozen, self.no_routine = set(), 0
        self.in_func, self.allow_calls = False, True
        self.flags = ["f0", "f1"]

    @property
    def pool(self):
        return self.vars + self.pool_extra

    def writable(self):
        return [a for a in self.arrays if a not in self.frozen]

    def lit(self):
        r = self.r
        if r.random() < 0.55:
            return r.choice(self.LITS)
        if r.random() < 0.5:
            return float(r.randint(-20, 20))
        return round(r.uniform(-50, 50), r.randint(0, 6))

    # ---- expression trees ----------------------------------------------------------------
    OPS = ["plus", "minus", "times", "divide", "mod", "pow"]

    def leaf(self):
        r = self.r
        return ("n", ("var", r.choice(self.pool)) if r.random() < 0.6 else ("lit", self.lit()))

    def atom(self, depth):
        r = self.r.random()
        if depth < 2 and r < 0.22:
            return ("paren", self.expr_tree(depth + 1))
        if r < 0.30:
            return ("neg", self.atom_leafy(depth))
        if r < 0.40:
            return ("fn", self.r.choice(["square root", "absolute value", "floor", "ceiling"]), self.atom_leafy(depth))
        return self.leaf()

    def atom_leafy(self, depth):
        if depth < 2 and self.r.random() < 0.2:
            return ("paren", self.expr_tree(depth + 1))
        return self.leaf()

    def expo(self):
        return ("n", ("lit", float(self.r.randint(-4, 9))))

    def expr_tree(self, depth=0):
        r = self.r
        if self.mode == "lin":
            steps = []
            for _ in range(r.randint(1, 3)):
                op = r.choice(self.OPS)
                steps.append((op, self.expo() if op == "pow" else self.atom(depth)))
            return ("chain", self.atom(depth), steps)
        return self.tree(depth)

    def tree(self, depth):
        r = self.r
        if depth >= 3 or r.random() < 0.3:
            return self.atom(5)                       # leaves, -x, fn of leaf (no more parens)
        op = r.choice(self.OPS)
        return ("bin", op, self.tree(depth + 1), self.expo() if op == "pow" else self.tree(depth + 1))

    def opd_plain(self):
        r = self.r
        return ("var", r.choice(self.pool)) if r.random() < 0.6 else ("lit", self.lit())

    def opd(self):
        r = self.r
        if self.allow_calls:
            if self.callable_funcs and r.random() < 0.07:
                name = r.choice(list(self.callable_funcs))
                return ("call", name, [self.opd_plain() for _ in range(self.callable_funcs[name])])
            if self.rec_funcs and r.random() < 0.05:
                name = r.choice(self.rec_funcs)
                if name == "rgcd":
                    args = [("lit", float(r.randint(1, 60))), ("lit", float(r.randint(1, 60)))]
                else:
                    args = [("lit", float(r.randint(0, 12)))]
                return ("call", name, args)
        if self.arrays and r.random() < 0.07:
            a = r.choice(list(self.arrays))
            t = r.random()
            if t < 0.5:
                return ("elem", a, self.idx(a))
            return ("alen", a) if t < 0.75 else ("aend", a, r.choice(["first", "last"]))
        if r.random() < 0.2:
            return ("ex", self.mode, self.expr_tree())
        x = r.random()
        if x < 0.55:
            return ("var", r.choice(self.pool))
        if x < 0.93:
            return ("lit", self.lit())
        return ("chr", r.choice(self.CHARS))

    def idx(self, arr):
        r = self.r
        n = self.arrays[arr]
        if r.random() < 0.04:
            return self.opd()                             # sometimes out of range on purpose
        if r.random() < 0.5:
            return ("lit", float(r.randrange(n)))
        return ("lit", float(r.randrange(n)))

    def cond(self, depth=0):
        r = self.r
        if not self.in_func and r.random() < 0.07:
            return ("flagvar", r.choice(self.flags))
        if depth < 2 and r.random() < 0.18:
            k = r.choice(["and", "or", "not"])
            if k == "not":
                return ("not", self.cond(depth + 1))
            return (k, self.cond(depth + 1), self.cond(depth + 1))
        return (self.opd(), r.choice([None, "not", "less than", "greater than", "at least", "at most"]), self.opd())

    def stmt(self, depth, callable_routines, in_routine=False):
        r = self.r
        x = r.random()
        v = lambda: r.choice(self.pool)  # noqa: E731
        arr = lambda: r.choice(list(self.arrays))  # noqa: E731
        if self.no_routine:
            callable_routines = []
        if depth < 3 and r.random() < 0.16:
            return self.newstmt(depth, callable_routines, in_routine)
        if self.loop_ok[-1] and r.random() < 0.08:
            word = r.choice(["stop", "skip"]) if self.loop_ok[-1] is True else "stop"
            return ("if", self.cond(), [(word,)], None)
        if not self.arrays and 0.43 <= x < 0.55:
            x = 0.1
        if 0.43 <= x < 0.49 and not self.writable():
            x = 0.1
        if x < 0.16:
            return ("set", v(), self.opd())
        if x < 0.34:
            return (r.choice(["add", "sub"]), self.opd(), v()) if r.random() < 0.5 else (r.choice(["mul", "div"]), v(), self.opd())
        if x < 0.40 and r.random() < 0.0:
            pass
        if x < 0.40:
            return ("unary", r.choice(["square root", "absolute value", "floor", "ceiling"]), self.opd(), v())
        if x < 0.43:
            return ("rem", self.opd(), self.opd(), v())
        if x < 0.49:
            a = arr()
            a = r.choice(self.writable())
            return ("store", self.opd(), a, self.idx(a))
        if x < 0.55:
            a = arr()
            return ("load", a, self.idx(a), v())
        if x < 0.70:
            items = []
            for _ in range(r.randint(1, 3)):
                t = r.random()
                if t < 0.25:
                    items.append(("str", r.choice([b"x = ", b"# hi ", b"a:b", b'say "q"', b"tab\there", b"back\\slash", b"", b"\n"])))
                elif t < 0.30 and not self.in_func:
                    items.append(("flag", self.cond()))
                elif t < 0.85:
                    items.append(("num", self.opd()))
                else:
                    items.append(("char", self.opd()))
            return ("print", r.choice(["print", "write"]), items)
        if x < 0.74:
            return (r.choice(["read", "readchar"]), v())
        if x < 0.84 and depth < 3:
            then = self.block(depth + 1, callable_routines, in_routine)
            els = self.block(depth + 1, callable_routines, in_routine) if r.random() < 0.5 else None
            return ("if", self.cond(), then, els)
        if x < 0.89 and depth < 3:
            c = next(self.loop_names)
            self.loop_ok.append(False)
            body = self.block(depth + 1, callable_routines, in_routine)
            self.loop_ok.pop()
            body.append(("add", ("lit", 1.0), c))
            return ("while_pair", c, r.randint(0, 5), body)
        if x < 0.915 and depth < 3:
            return self.fancy(depth, callable_routines, in_routine)
        if x < 0.96 and callable_routines:
            return ("run", r.choice(callable_routines))
        if x < 0.985 and not in_routine and r.random() < 0.3:
            return ("finish", self.opd() if r.random() < 0.85 else None)
        return ("set", v(), self.opd())

    FOR_STEPS = [1.0, 2.0, -1.0, -2.0, 0.5, 3.0, 0.1, 0.3, -0.5]

    def loop_body(self, depth, callable_routines, in_routine, c, ok):
        if c:
            self.pool_extra.append(c)
        self.loop_ok.append(ok)
        try:
            return self.block(depth + 1, callable_routines, in_routine)
        finally:
            self.loop_ok.pop()
            if c:
                self.pool_extra.pop()

    def newstmt(self, depth, callable_routines, in_routine):
        r = self.r
        t = r.random()
        v = lambda: r.choice(self.pool)  # noqa: E731
        if t < 0.30:                                     # for i from A to B [by S]
            c = next(self.loop_names)
            a = ("lit", float(r.randint(-3, 5)))
            b = ("lit", float(r.randint(-3, 8)) if r.random() < 0.9 else r.choice([2.5, 0.5, 1e300, -7.25]))
            step = None if r.random() < 0.4 else ("lit", r.choice(self.FOR_STEPS) if r.random() < 0.95 else 0.0)
            return ("for", c, a, b, step, self.loop_body(depth, callable_routines, in_routine, c, True))
        if t < 0.45:                                     # repeat N times
            n = ("lit", float(r.randint(0, 4)) if r.random() < 0.95 else -1.0)
            return ("repeat", n, self.loop_body(depth, callable_routines, in_routine, None, True))
        if t < 0.55:                                     # repeat forever, left with `stop`
            c = next(self.loop_names)
            self.loop_ok.append("stop")
            body = self.block(depth + 1, callable_routines, in_routine)
            self.loop_ok.pop()
            body.append(("add", ("lit", 1.0), c))
            body.append(("if", (("var", c), "at least", ("lit", float(r.randint(1, 4)))), [("stop",)], None))
            return ("repeatf", c, body)
        if t < 0.70 and self.arrays:                     # for each x in ARRAY: (the array is not written inside)
            a = r.choice(list(self.arrays))
            c = next(self.loop_names)
            added = a not in self.frozen
            self.frozen.add(a)
            self.no_routine += 1
            try:
                body = self.loop_body(depth, callable_routines, in_routine, c, True)
            finally:
                if added:
                    self.frozen.discard(a)
                self.no_routine -= 1
            return ("foreach", c, a, body)
        if t < 0.80 and self.writable():                 # set item I of A to V   /   add V to item I of A
            a = r.choice(self.writable())
            if r.random() < 0.5:
                return ("setelem", a, self.idx(a), self.opd())
            saved, self.allow_calls = self.allow_calls, False
            try:
                return ("augelem", r.choice(["add", "sub", "mul", "div"]), a, self.idx(a), self.opd())
            finally:
                self.allow_calls = saved
        if t < 0.92 and self.callable_funcs:             # call f with a and b [store in v]
            name = r.choice(list(self.callable_funcs))
            return ("callstmt", name, [self.opd_plain() for _ in range(self.callable_funcs[name])], v() if r.random() < 0.7 else None)
        if not self.in_func:                             # yes / no values
            return ("fset", r.choice(self.flags), self.cond())
        return ("set", v(), self.opd())

    def fancy(self, depth, callable_routines, in_routine):
        r = self.r
        t = r.random()
        v = lambda: r.choice(self.vars)  # noqa: E731
        if t < 0.30:                                   # Structurally block: formulas follow the usual order of operations
            saved, self.mode = self.mode, "str"
            body = self.block(depth + 1, callable_routines, in_routine)
            self.mode = saved
            if saved == "str":
                return ("scope", body)
            return ("scope", body)
        if t < 0.65:                                   # pipeline of several clauses
            clauses, subject = [], None
            for i in range(r.randint(2, 4)):
                kind = "set" if i == 0 else r.choice(["add", "sub", "mul", "div", "set"])
                target = subject if (subject and r.random() < 0.7 and kind != "set") else v()
                if kind == "set":
                    clauses.append(("set", target, self.opd()))
                elif kind in ("add", "sub"):
                    clauses.append((kind, self.opd(), target))
                else:
                    clauses.append((kind, target, self.opd()))
                subject = target
            return ("pipe", clauses)
        if t < 0.85:                                   # one action on several variables
            names = r.sample(self.pool, min(len(self.pool), r.randint(2, 3)))
            return ("multi", r.choice(["add", "sub", "mul", "div"]), names, self.opd())
        return ("convert", self.opd(), v())

    def block(self, depth, callable_routines, in_routine=False):
        out = []
        for _ in range(self.r.randint(1, 5 if depth else 12)):
            s = self.stmt(depth, callable_routines, in_routine)
            if s[0] == "while_pair":
                _, c, n, body = s
                out.append(("let", c))
                out.append(("set", c, ("lit", 0.0)))
                out.append(("while", (("var", c), "less than", ("lit", float(n))), body))
            elif s[0] == "repeatf":
                _, c, body = s
                out.append(("let", c))
                out.append(("set", c, ("lit", 0.0)))
                out.append(("repeatf", body))
            else:
                out.append(s)
        return out

    # ---- functions ----------------------------------------------------------------------
    @staticmethod
    def _ex(first, steps=()):
        return ("ex", "lin", ("chain", ("n", first), [(op, ("n", a)) for op, a in steps]))

    def recursive_functions(self):
        V, L, ex = (lambda n: ("var", n)), (lambda x: ("lit", float(x))), self._ex
        n1 = lambda name, arg: ("call", name, [arg])  # noqa: E731
        minus1 = ex(V("n"), [("minus", L(1))])
        return {
            "rsum": {"params": ["n"], "body": [
                ("let", "r"), ("set", "r", L(0)),
                ("if", (V("n"), "at most", L(0)), [("giveback", L(0))], None),
                ("set", "r", ex(V("n"), [("plus", n1("rsum", minus1))])),
                ("giveback", V("r"))]},
            "rfib": {"params": ["n"], "body": [
                ("let", "u"), ("set", "u", L(0)), ("let", "w"), ("set", "w", L(0)),
                ("if", (V("n"), "less than", L(2)), [("giveback", V("n"))], None),
                ("set", "u", n1("rfib", minus1)),
                ("set", "w", n1("rfib", ex(V("n"), [("minus", L(2))]))),
                ("giveback", ex(V("u"), [("plus", V("w"))]))]},
            "rgcd": {"params": ["m", "k"], "body": [
                ("if", (V("k"), None, L(0)), [("giveback", V("m"))], None),
                ("giveback", ("call", "rgcd", [V("k"), ex(V("m"), [("mod", V("k"))])]))]},
            "risev": {"params": ["n"], "body": [
                ("if", (V("n"), "at most", L(0)), [("giveback", L(1))], None),
                ("giveback", n1("risod", minus1))]},
            "risod": {"params": ["n"], "body": [
                ("if", (V("n"), "at most", L(0)), [("giveback", L(0))], None),
                ("giveback", n1("risev", minus1))]},
        }

    def make_funcs(self):
        r = self.r
        if r.random() < 0.5:
            rec = self.recursive_functions()
            for name in r.sample(["rsum", "rfib", "rgcd", "risev"], r.randint(1, 2)):
                self.funcs[name] = rec[name]
                self.rec_funcs.append(name)
                if name == "risev":
                    self.funcs["risod"] = rec["risod"]
        for i in range(r.randint(0, 3)):
            name = f"fn{i}"
            params = [f"p{i}{j}" for j in range(r.randint(0, 3))]
            locs = [f"q{i}{j}" for j in range(r.randint(1, 2))]
            saved = (self.vars, self.arrays, self.pool_extra, self.loop_ok, self.in_func)
            self.vars, self.arrays, self.pool_extra, self.loop_ok, self.in_func = params + locs, {}, [], [False], True
            try:
                body = []
                for q in locs:
                    body += [("let", q), ("set", q, ("lit", 0.0))]
                body += self.block(1, [], in_routine=True)
                body.append(("giveback", self.opd()))
            finally:
                self.vars, self.arrays, self.pool_extra, self.loop_ok, self.in_func = saved
            self.funcs[name] = {"params": params, "body": body}
            self.callable_funcs[name] = len(params)

    def program(self):
        self.make_funcs()
        routines = {}
        names = []
        for i in range(self.r.randint(0, 3)):
            name = f"r{i}"
            routines[name] = self.block(1, list(names), in_routine=True)
            names.append(name)
        main = self.block(0, names)
        if self.r.random() < 0.7:
            main.append(("finish", self.opd()))
        return {"routines": routines, "arrays": self.arrays, "main": main, "vars": self.vars,
                "funcs": self.funcs, "flags": self.flags}


def gen_stdin(rng):
    parts = [rng.choice(["12", "-3.5", "+7", "0.25", " ", "\n", "abc", "x", ".5", "5.", "1e3", "-", "+", "3.14.15", "99999999999",
                         "+-4", "007", "\t", "0", "-0", "1.2345678901234567"]) for _ in range(rng.randint(0, 14))]
    return (rng.choice([" ", "\n", ""]).join(parts)).encode()


# ----------------------------------------------------------------------------- compile & run
CLASSIC = False


def build_pure(text, path):
    if CLASSIC:
        nodes = zoomy.parse_source(text, "fuzz.zmy")
        comp = zoomy.Compiler("fuzz.zmy")
        comp.load(nodes, ".")
    else:
        import zoomy_py
        prog = zoomy_py.Program("fuzz.zmy").load_text(text)
        assert prog.native_ok, "fuzz program should compile natively"
        comp = zoomy.AstCompiler(prog)
    asm = comp.compile()
    with open(path, "wb") as f:
        f.write(zoomy.build_elf(asm))
    os.chmod(path, 0o755)
    return asm


def build_gcc(asm, path, tmp):
    s = os.path.join(tmp, "p.s")
    with open(s, "w") as f:
        f.write(zoomy.build_asm_text(asm))
    subprocess.run(["gcc", s, "-no-pie", "-o", path], check=True, capture_output=True)


def build_py(text, path):
    import zoomy_py
    prog = zoomy_py.Program("fuzz.zmy").load_text(text)
    assert prog.native_ok, "fuzz program should be in the native subset"
    src, _ = zoomy_py.compile_python(prog)
    with open(path, "w") as f:
        f.write(src)


def build_wasm(text, path):
    import zoomy_py, zoomy_wasm
    prog = zoomy_py.Program("fuzz.zmy").load_text(text)
    assert prog.native_ok, "fuzz program should be in the native subset"
    with open(path, "wb") as f:
        f.write(zoomy_wasm.compile_program(prog))


def run_wasm(path, stdin):
    p = subprocess.run(["node", os.path.join(os.path.dirname(HERE), "zoomy_wasm_host.js"), path], input=stdin,
                       capture_output=True, timeout=30)
    return p.stdout, p.returncode, p.stderr


def run_py(path, stdin):
    p = subprocess.run([sys.executable, path], input=stdin, capture_output=True, timeout=20)
    return p.stdout, p.returncode, p.stderr


def run_bin(path, stdin):
    p = subprocess.run([path], input=stdin, capture_output=True, timeout=10)
    return p.stdout, p.returncode, p.stderr


def main():
    args = sys.argv[1:]
    count = int(args[0]) if args and args[0].isdigit() else 300
    gcc_n = int(args[args.index("--gcc") + 1]) if "--gcc" in args else 0
    seed0 = int(args[args.index("--seed") + 1]) if "--seed" in args else 1
    py_n = int(args[args.index("--py") + 1]) if "--py" in args else 0
    wasm_n = int(args[args.index("--wasm") + 1]) if "--wasm" in args else 0
    bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        exe = os.path.join(tmp, "p")
        exe_gcc = os.path.join(tmp, "pg")
        for n in range(count):
            seed = seed0 * 100000 + n
            rng = random.Random(seed)
            prog = Gen(rng).program()
            stdin = gen_stdin(rng)
            globals()["STYLE"] = ("simply", "english", "english", "english", "classic" if CLASSIC else "english")[n % 5]
            text = render(prog)
            want = Ref(prog, stdin).run()
            try:
                asm = build_pure(text, exe)
                got = run_bin(exe, stdin)
                results = [("pure", got)]
                if n < gcc_n:
                    build_gcc(asm, exe_gcc, tmp)
                    results.append(("gcc", run_bin(exe_gcc, stdin)))
                if n < py_n:
                    pyf = os.path.join(tmp, "p.py")
                    build_py(text, pyf)
                    results.append(("python", run_py(pyf, stdin)))
                if n < wasm_n:
                    wf = os.path.join(tmp, "p.wasm")
                    build_wasm(text, wf)
                    results.append(("wasm", run_wasm(wf, stdin)))
            except Exception as e:                      # noqa: BLE001
                print(f"seed {seed}: COMPILE/RUN FAILURE {type(e).__name__}: {e}\n{text}")
                bad += 1
                continue
            for mode, (out, rc, err) in results:
                ok = (out == want[0] and rc == want[1] and (want[2] == b"" or err.startswith(want[2].rstrip(b"\n"))))
                if not ok:
                    bad += 1
                    print(f"seed {seed} [{mode}]: MISMATCH")
                    print(f"  want rc={want[1]} out={want[0][:300]!r}")
                    print(f"  got  rc={rc} out={out[:300]!r} err={err[:80]!r}")
                    with open(os.path.join(HERE, f"fail_{seed}.zmy"), "w") as f:
                        f.write(text)
                    with open(os.path.join(HERE, f"fail_{seed}.in"), "wb") as f:
                        f.write(stdin)
                    break
    print(f"{count} programs ({gcc_n} also in gcc mode, {py_n} also through the Python backend, {wasm_n} also as WebAssembly): {bad} failures")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
