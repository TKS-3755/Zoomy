#!/usr/bin/env python3
"""Zoomy 7: Big Numbers (1024-bit integers) for the machine-code and WebAssembly backends.

Those two compilers only know 64-bit numbers.  Instead of teaching either of them 1024-bit arithmetic, this module rewrites a
Big Numbers program into an ordinary unsigned-64-bit program that they already compile:

  * every Big Number is 32 limbs of 32 bits, kept in one big global array (`zbn_mem`), one limb per slot;
  * a variable (or array item) is not a name any more but the slot number where its 32 limbs start;
  * every operation becomes a call of the arithmetic library in `zoomy_bignum.zmy`, which is written in Zoomy itself;
  * function arguments, locals and temporaries live in frames on a stack inside the same array (`zbn_fp` is the frame pointer);
  * yes/no variables, loop counters, indexes and the like stay ordinary small numbers.

The Python backend does not use any of this: it has real integers.  Its answers are the reference these rewrites are tested against."""
import copy
import os
from fractions import Fraction

import zoomy_py
from zoomy_py import ZoomyError, all_stmts, assigned_names, nested_blocks, stmt_exprs, walk

HERE = os.path.dirname(os.path.abspath(__file__))
LIB_FILE = os.path.join(HERE, "zoomy_bignum.zmy")
BD_LIB_FILE = os.path.join(HERE, "zoomy_bigdec.zmy")
USER_BASE = 320                  # slots 0..319 belong to the library (0 = value given back by a function)
LIMBS = 32
RET = 0
BD_STRIDE = 34                   # a Big Decimal: 32 limbs, the biased exponent, the sign
BD_USER_BASE = 2000              # the Big Decimals library keeps its scratch space in slots 0..1999
BD_NAMES = {"bn_isneg": "bd_sign"}
NATIVE_SLOTS = 480000            # the machine-code compiler keeps its arrays in a 4 MB frame
WASM_SLOTS = 1500000
BIG_MESSAGES = {"count": "a count cannot be negative", "step": "a 'for' loop needs a step that is not zero",
                "index": "array index out of range", "shift": "a shift or bit number must be from 0 to 1023",
                "deep": "too many nested calls (a function calls itself without stopping?)"}
BD_NO_FN = {"rounded", "format"}
UNSUPPORTED = {"workers": "workers", "waitw": "workers", "syscall": "syscall", "extern": "extern", "runwith": "runwith",
               "openf": "files", "openarr": "files", "closef": "files", "seekf": "files", "fsize": "files",
               "clock": "'read the clock'"}


def _rn(name):
    return name if name == "input_ok" else "zbn_mem" if name == "bn" else "zb_" + name


def _rename(node):
    """give every name in the library a private spelling, so that it can never meet a name of the user's program"""
    if isinstance(node, (list, tuple)):
        if node and node[0] == "var" and len(node) > 1 and isinstance(node[1], str):
            node[1] = _rn(node[1])
            return
        if node and isinstance(node[0], str) and isinstance(node, list):
            k = node[0]
            if k == "define" and len(node) > 4:
                node[2] = _rn(node[2])
                node[3] = [_rn(p) for p in node[3]]
            elif k in ("for", "foreach") and len(node) > 2 and isinstance(node[2], str):
                node[2] = _rn(node[2])
            elif k == "alloc" and len(node) > 2 and isinstance(node[2], str):
                node[2] = _rn(node[2])
        for c in node:
            _rename(c)


def _library_stmt(s, unread="zb_bn_unread"):
    """a library statement made ready for the compilers: `fail with` becomes a runtime error; `bn_unread(c)` becomes `unread`"""
    if s[0] == "fail":
        return ["rterror", s[1], s[2][1][0]]
    if s[0] == "exprstmt" and s[2][0] == "call" and s[2][1] == ["var", unread]:
        return ["unread", s[1], s[2][2][0]]
    out = list(s)
    for i, c in enumerate(out):
        if isinstance(c, list) and c and isinstance(c[0], list):          # a block of statements
            out[i] = [_library_stmt(t, unread) for t in c]
    if s[0] == "if" and s[4]:
        out[4] = [_library_stmt(t, unread) for t in s[4]]
    return out


_LIB = {}


def library(bd=False):
    """the library's functions (as statements); parsed once"""
    if bd not in _LIB:
        un = "bd_unread" if bd else "bn_unread"
        lib = zoomy_py.load_program(BD_LIB_FILE if bd else LIB_FILE, "uint")
        defs = [s for s in lib.stmts if s[0] == "define" and s[2] != un]
        for d in defs:
            _rename(d)
        _LIB[bd] = [_library_stmt(d, "zb_" + un) for d in defs]
    return copy.deepcopy(_LIB[bd])


class Ctx:
    """one function (or the main program) being rewritten: where its locals and temporaries live"""

    def __init__(self, kind, locs=None, stride=32):
        self.kind = kind                 # "main": absolute slots; "func": slots relative to the frame pointer
        self.locs = locs or {}           # local name -> slot offset inside the frame
        self.nloc = stride * len(self.locs)
        self.hidden = 0                  # persistent hidden values (loop counters), counted in values
        self.ntemp = 0
        self.maxtemp = 0
        self.patches = []                # (node, kind, index): offsets that are only known once the whole body is done
        self.fs = ["num", None]          # frame size, patched
        self.base = ["num", None]


class Lowerer:
    def __init__(self, prog, capacity, bd=False):
        self.bd = bd
        self.L = BD_STRIDE if bd else LIMBS
        self.prog = prog
        self.file = prog.file
        self.capacity = capacity
        self.flags = set(prog.n_flags)
        self.arrays = {}                 # name -> (base slot, items)
        self.gtop = BD_USER_BASE if bd else USER_BASE
        self.gvars = {}
        self.pool = {}
        self.counter = 0
        self.line = 0
        self.out = []
        self.ctx = None
        self.loop_depth = 0
        self.main = Ctx("main", None, self.L)
        self.funcs = prog.funcs
        self.fp_check = ["num", None]    # limit for the frame pointer, patched
        self.maxfs = 0
        self.main_fp = ["num", None]
        self.all_ctx = [self.main]

    # ---- little helpers ---------------------------------------------------------------------------
    def err(self, msg, line=None):
        return ZoomyError(msg, self.file, line or self.line)

    def emit(self, st):
        self.out.append(st)

    def fresh(self, tag="s"):
        self.counter += 1
        return f"zbn_{tag}{self.counter}"

    @staticmethod
    def num(v):
        return ["num", v]

    @staticmethod
    def var(n):
        return ["var", n]

    def lib(self, name):
        """the library function behind a bn_* name (the Big Decimals library has bd_* ones)"""
        if not self.bd:
            return "zb_" + name
        return "zb_" + BD_NAMES.get(name, "bd_" + name[3:])

    def call(self, name, *args):
        return ["call", ["var", self.lib(name)], list(args), []]

    def do(self, name, *args):
        self.emit(["exprstmt", self.line, self.call(name, *args)])

    def setv(self, name, e):
        self.emit(["set", self.line, ["var", name], e])

    def small(self, expr, tag="s"):
        """put a small (ordinary) value into a fresh variable"""
        n = self.fresh(tag)
        self.setv(n, expr)
        return n

    def rterror(self, kind_or_text):
        return ["rterror", self.line, BIG_MESSAGES.get(kind_or_text, kind_or_text)]

    def check(self, cond, kind):
        self.emit(["if", self.line, cond, [self.rterror(kind)], None])

    # ---- where things live ------------------------------------------------------------------------
    def rel(self, kind, k):
        """the location of frame slot (kind, k)"""
        ctx = self.ctx
        node = ["num", None]
        ctx.patches.append((node, kind, k))
        return node if ctx.kind == "main" else ["bin", "plus", ["var", "zbn_fp"], node]

    def tmp(self):
        ctx = self.ctx
        loc = self.rel("t", ctx.ntemp * self.L)
        ctx.ntemp += 1
        ctx.maxtemp = max(ctx.maxtemp, ctx.ntemp)
        return loc

    def hidden(self):
        ctx = self.ctx
        loc = self.rel("h", ctx.hidden * self.L)
        ctx.hidden += 1
        return loc

    def gslot(self, n=None):
        n = n or self.L
        off = self.gtop
        self.gtop += n
        return off

    def varloc(self, name):
        if name in self.ctx.locs:
            if self.ctx.kind == "main":
                return ["num", self.ctx.locs[name]]
            return ["bin", "plus", ["var", "zbn_fp"], ["num", self.ctx.locs[name]]]
        if name not in self.gvars:
            self.gvars[name] = self.gslot()
        return ["num", self.gvars[name]]

    def const(self, v):
        if v not in self.pool:
            self.pool[v] = self.gslot()
        return ["num", self.pool[v]]

    def is_small(self, name):
        return name in self.flags or name == "input_ok"

    # ---- expressions ------------------------------------------------------------------------------
    @staticmethod
    def has_call(e):
        hit = []
        walk(e, lambda x: hit.append(1) if x[0] == "call" else None)
        return bool(hit)

    def X(self, e, dest=None):
        """a Big Number expression: emits statements, gives back the location of the result (a slot number expression)"""
        k = e[0]
        if k == "num":
            v = Fraction(e[1]) if self.bd else int(e[1])
            loc = self.const(v)
            return self.copy_to(dest, loc)
        if k == "var":
            n = e[1]
            if n == "input_ok":
                d = dest or self.tmp()
                self.do("bn_small", d, ["var", "input_ok"])
                return d
            if n in self.arrays:
                raise self.err(f"'{n}' is an array: use an item of it")
            return self.copy_to(dest, self.varloc(n))
        if k == "index":
            return self.copy_to(dest, self.element(e[1][1], e[2]))
        if k == "neg":
            a = self.X(e[1])
            d = dest or self.tmp()
            self.do("bn_neg", d, a)
            return d
        if k == "bin":
            return self.binary(e, dest)
        if k == "bitop":
            return self.bitop(e, dest)
        if k == "fn":
            return self.function(e, dest)
        if k == "call":
            return self.user_call(e, dest)
        raise self.err("this kind of expression cannot be used with Big Numbers on the native and WebAssembly backends")

    def copy_to(self, dest, loc):
        if dest is None:
            return loc
        self.do("bn_copy", dest, loc)
        return dest

    def operands(self, x, y):
        """two operands, left to right; a variable on the left is copied first when the right side calls a function"""
        a = self.X(x)
        if self.has_call(y) and x[0] in ("var", "index"):
            t = self.tmp()
            self.do("bn_copy", t, a)
            a = t
        b = self.X(y)
        return a, b

    def binary(self, e, dest):
        op = e[1]
        name = {"plus": "bn_add", "minus": "bn_sub", "times": "bn_mul", "divide": "bn_div", "mod": "bn_mod",
                "pow": "bn_pow"}[op]
        a, b = self.operands(e[2], e[3])
        d = dest or self.tmp()
        self.do(name, d, a, b)
        return d

    def shift_count(self, loc, rotate=False):
        if rotate:
            return self.mask_1023(self.small(self.call("bn_low", loc), "n"))
        n = self.small(self.call("bn_idx", loc), "n")
        self.check(["cmp", "gt", ["var", n], ["num", 1023]], "shift")
        return n

    def mask_1023(self, n):
        self.emit(["set", self.line, ["var", n], ["bitop", "and", ["var", n], ["num", 1023]]])
        return n

    def bitop(self, e, dest):
        op = e[1]
        if self.bd:
            raise self.err("bit operations cannot be used with Big Decimals")
        if op in ("and", "or", "xor", "andnot", "pext", "pdep"):
            a, b = self.operands(e[2], e[3])
            d = dest or self.tmp()
            self.do("bn_" + op, d, a, b)
            return d
        if op in ("shl", "shr", "sar", "setbit", "clearbit", "flipbit"):
            a, b = self.operands(e[2], e[3])
            n = self.shift_count(b)
            d = dest or self.tmp()
            self.do("bn_" + op, d, a, ["var", n])
            return d
        if op in ("rol", "ror"):
            a, b = self.operands(e[2], e[3])
            n = self.shift_count(b, rotate=True)
            d = dest or self.tmp()
            self.do("bn_" + op, d, a, ["var", n])
            return d
        a = self.X(e[2])
        d = dest or self.tmp()
        if op in ("not", "bswap", "lowbit", "clearlow"):
            self.do("bn_" + op, d, a)
        elif op in ("popcnt", "tzcnt", "lzcnt"):
            c = self.small(self.call("bn_" + op, a), "c")
            self.do("bn_small", d, ["var", c])
        else:
            raise self.err(f"the bit operation '{op}' is not available with Big Numbers on the native and WebAssembly backends")
        return d

    def function(self, e, dest):
        f, args = e[1], e[2]
        if self.bd and f in BD_NO_FN:
            raise self.err(f"'{f}' is not available with Big Decimals yet (it works on floats)")
        if self.bd and f in ("floor", "ceil", "round", "trunc"):
            a = self.X(args[0])
            d = dest or self.tmp()
            self.do("bn_" + f, d, a)
            return d
        if f in ("floor", "ceil"):
            return self.X(args[0], dest)
        if f == "sqrt":
            a = self.X(args[0])
            d = dest or self.tmp()
            self.do("bn_sqrt", d, a)
            return d
        if f == "abs":
            a = self.X(args[0])
            d = dest or self.tmp()
            s = self.small(self.call("bn_isneg", a))
            self.do("bn_copy", d, a)
            self.emit(["if", self.line, ["cmp", "eq", ["var", s], ["num", 1]], [["exprstmt", self.line, self.call("bn_neg", d, d)]], None])
            return d
        if f == "rem":
            a, b = self.operands(args[0], args[1])
            d = dest or self.tmp()
            self.do("bn_rem", d, a, b)
            return d
        if f in ("len", "first", "last"):
            arr = args[0][1]
            base, n = self.arrays[arr]
            if f == "len":
                return self.copy_to(dest, self.const(n))
            return self.copy_to(dest, ["num", base + (0 if f == "first" else self.L * (n - 1))])
        raise self.err(f"'{f}' is not available with Big Numbers on the native and WebAssembly backends")

    def element(self, arr, key):
        """the slot where item KEY of array ARR starts (the index is checked)"""
        base, n = self.arrays[arr]
        k = self.X(key)
        i = self.small(self.call("bn_idx", k), "i")
        self.check(["cmp", "ge", ["var", i], ["num", n]], "index")
        return ["bin", "plus", ["num", base], ["bin", "times", ["var", i], ["num", self.L]]]

    def user_call(self, e, dest=None):
        name = e[1][1]
        f = self.funcs[name]
        locs = []
        for i, a in enumerate(e[2]):
            loc = self.X(a)
            if any(self.has_call(b) for b in e[2][i + 1:]) and a[0] in ("var", "index"):
                t = self.tmp()
                self.do("bn_copy", t, loc)
                loc = t
            locs.append(loc)
        self.invoke(name, locs)
        d = dest or self.tmp()
        self.do("bn_copy", d, ["num", RET])
        return d

    def invoke(self, name, arg_locs):
        ctx = self.ctx
        for i, loc in enumerate(arg_locs):
            slot = ["bin", "plus", ["var", "zbn_fp"], ["bin", "plus", ctx.fs, ["num", self.L * i]]] if ctx.kind != "main" \
                else ["bin", "plus", ["var", "zbn_fp"], ["num", self.L * i]]
            self.do("bn_copy", slot, loc)
        if ctx.kind != "main":
            self.setv("zbn_fp", ["bin", "plus", ["var", "zbn_fp"], ctx.fs])
        self.check(["cmp", "gt", ["var", "zbn_fp"], self.fp_check], "deep")
        self.emit(["exprstmt", self.line, ["call", ["var", name], [], []]])
        if ctx.kind != "main":
            self.setv("zbn_fp", ["bin", "minus", ["var", "zbn_fp"], ctx.fs])

    # ---- conditions -------------------------------------------------------------------------------
    def flagish(self, e):
        return e[0] in ("bool", "cmp", "and", "or", "not") or (e[0] == "var" and e[1] in self.flags)

    def C(self, c):
        k = c[0]
        if k in ("bool", "var"):
            return c
        if k == "not":
            return ["not", self.C(c[1])]
        if k in ("and", "or"):
            left = self.C(c[1])
            saved, self.out = self.out, []
            right = self.C(c[2])
            pre, self.out = self.out, saved
            if not pre:
                return [k, left, right]
            t = self.fresh("f")
            self.setv(t, left)
            pre.append(["set", self.line, ["var", t], right])
            self.emit(["if", self.line, ["var", t] if k == "and" else ["not", ["var", t]], pre, None])
            return ["var", t]
        if k == "cmp":
            op, x, y = c[1], c[2], c[3]
            if self.flagish(x) or self.flagish(y):
                return ["cmp", op, self.C(x), self.C(y)]
            a, b = self.operands(x, y)
            r = self.call("bn_cmp", a, b)
            return {"eq": ["cmp", "eq", r, ["num", 1]], "ne": ["cmp", "ne", r, ["num", 1]],
                    "lt": ["cmp", "eq", r, ["num", 0]], "gt": ["cmp", "eq", r, ["num", 2]],
                    "ge": ["cmp", "ge", r, ["num", 1]], "le": ["cmp", "le", r, ["num", 1]]}[op]
        raise self.err("this kind of condition cannot be used with Big Numbers on the native and WebAssembly backends")

    # ---- statements -------------------------------------------------------------------------------
    def block(self, stmts):
        saved, self.out = self.out, []
        for s in stmts:
            self.stmt(s)
        res, self.out = self.out, saved
        return res

    def place(self, p):
        """the location of a place (variable or array item) that is written to"""
        if p[0] == "var":
            return self.varloc(p[1])
        return self.element(p[1][1], p[2])

    def stmt(self, s):
        k = s[0]
        self.line = s[1] if len(s) > 1 and isinstance(s[1], int) else self.line
        self.ctx.ntemp = 0
        if k in UNSUPPORTED:
            raise self.err(f"{UNSUPPORTED[k]} cannot be used with Big Numbers on the native and WebAssembly backends "
                           f"(build with the Python backend)")
        m = getattr(self, "s_" + k, None)
        if m is None:
            raise self.err(f"'{k}' cannot be used with Big Numbers on the native and WebAssembly backends")
        m(s)

    def s_pass(self, s):
        pass

    def s_fail(self, s):                            # Zoomy 8: `fail with "text"` - "zoomy: error:" and exit code 1
        if s[2][0] != "str" or len(s[2][1]) != 1 or not isinstance(s[2][1][0], str):
            raise self.err("'fail with' needs a fixed text with Big Numbers on the native and WebAssembly backends")
        self.emit(["rterror", s[1], s[2][1][0], 1])

    def s_global(self, s):
        names = [n for n in s[2] if self.is_small(n)]
        if names:
            self.emit(["global", s[1], names])

    def s_alloc(self, s):
        base, n = self.arrays[s[2]]
        if self.ctx.kind == "main" and not self.loop_depth:
            return                                  # the array starts out as zeros already
        z = self.fresh("z")
        self.setv(z, ["num", base])
        self.emit(["repeat", self.line, ["num", n * self.L], [
            ["set", self.line, ["index", ["var", "zbn_mem"], ["var", z]], ["num", 0]],
            ["aug", self.line, "add", ["num", 1], ["var", z]]]])

    def assign(self, target, e):
        """TARGET = the Big Number expression E (or a yes/no value)"""
        if target[0] == "var" and target[1] in self.flags:
            self.setv(target[1], self.C(e))
            return
        if target[0] == "var" and target[1] == "input_ok":
            a = self.X(e)
            self.setv("input_ok", self.call("bn_low", a))
            return
        if target[0] == "index":
            dest = self.element(target[1][1], target[2])
        else:
            dest = self.varloc(target[1])
        self.X(e, dest)

    def s_set(self, s):
        self.assign(s[2], s[3])

    def s_calc(self, s):
        self.assign(s[3], s[2])

    def s_callstore(self, s):
        self.assign(s[3], s[2])

    def s_aug(self, s):
        op, val, place = s[2], s[3], s[4]
        d = self.place(place)
        v = self.X(val)
        name = {"add": "bn_add", "sub": "bn_sub", "mul": "bn_mul", "div": "bn_div"}[op]
        self.do(name, d, d, v)

    def s_store(self, s):
        dest = self.element(s[2][1], s[3])
        self.X(s[4], dest)

    def s_load(self, s):
        src = self.element(s[2][1], s[3])
        self.do("bn_copy", self.place(s[4]), src)

    def s_exprstmt(self, s):
        self.user_call(s[2])

    def s_run(self, s):
        self.invoke(s[2], [])

    def s_convert(self, s):
        if s[2] != "character":
            raise self.err("converting a number to text is not available with Big Numbers on the native and WebAssembly backends")
        a = self.X(s[3])
        src = self.small(self.call("bn_low", a))
        out = self.fresh("v")
        self.emit(["convert", self.line, "character", ["var", src], ["var", out]])
        self.do("bn_small", self.place(s[4]), ["var", out])

    def s_read(self, s):
        kind, target = s[2], s[3]
        if kind == "num":
            self.setv("input_ok", self.call("bn_read", self.place(target)))
            return
        v = self.fresh("v")
        self.emit(["read", self.line, kind, ["var", v]])
        self.do("bn_small", self.place(target), ["var", v])

    def s_print(self, s):
        newline, items = s[2], s[3]
        parts = []
        for kind, e in items:
            if kind == "char":
                a = self.X(e)
                parts.append(("char", self.call("bn_low", a)))
            elif e[0] == "str":
                for p in e[1]:
                    if isinstance(p, str):
                        parts.append(("str", p))
                    else:
                        parts.append(self.value_part(p))
            else:
                parts.append(self.value_part(e))
        for kind, x in parts:
            if kind == "str":
                self.emit(["print", self.line, False, [["val", ["str", [x]]]]])
            elif kind == "big":
                self.do("bn_print", x)
            elif kind == "char":
                self.emit(["print", self.line, False, [["char", x]]])
            else:
                self.emit(["print", self.line, False, [["val", x]]])
        if newline:
            self.emit(["print", self.line, True, [["val", ["str", [""]]]]])

    def value_part(self, e):
        if self.flagish(e):
            return ("flag", self.C(e))
        return ("big", self.X(e))

    def s_if(self, s):
        cond = self.C(s[2])
        then = self.block(s[3])
        other = self.block(s[4]) if s[4] else None
        self.emit(["if", self.line, cond, then, other])

    def s_while(self, s):
        saved, self.out = self.out, []
        cond = self.C(s[2])
        pre, self.out = self.out, saved
        self.loop_depth += 1
        body = self.block(s[3])
        self.loop_depth -= 1
        if not pre:
            self.emit(["while", self.line, cond, body])
        else:
            self.emit(["repeat", self.line, None, pre + [["if", self.line, ["not", cond], [["stop", self.line]], None]] + body])

    def s_repeat(self, s):
        self.loop_depth += 1
        body = self.block(s[3])
        self.loop_depth -= 1
        if s[2] is None:
            self.emit(["repeat", self.line, None, body])
            return
        a = self.X(s[2])
        if self.bd:
            neg = self.small(self.call("bn_negtrunc", a))
        else:
            neg = self.small(self.call("bn_isneg", a))
        self.check(["cmp", "eq", ["var", neg], ["num", 1]], "count")
        n = self.small(self.call("bn_idx", a), "n")
        self.emit(["repeat", self.line, ["var", n], body])

    def s_for_bd(self, s):
        """a Big Decimals 'for' loop: n = floor((end - start) / step + 1e-100) + 1 rounds, the value of round k is start + k * step"""
        var, start, end, step = s[2], s[3], s[4], s[5]
        a0, stp = self.hidden(), self.hidden()
        self.X(start, a0)
        e = self.X(end)
        et = self.tmp()
        self.do("bn_copy", et, e)
        if step is None:
            self.do("bn_small", stp, ["num", 1])
        else:
            self.X(step, stp)
        self.check(["cmp", "eq", self.call("bn_iszero", stp), ["num", 1]], "step")
        n = self.fresh("n")
        self.setv(n, ["num", 0])
        q = self.tmp()
        self.do("bn_sub", q, et, a0)
        self.do("bn_div", q, q, stp)
        self.emit(["if", self.line, ["cmp", "eq", self.call("bn_sign", q), ["num", 0]], [
            ["exprstmt", self.line, self.call("bn_add", q, q, self.const(_EPS))],
            ["exprstmt", self.line, self.call("bn_floor", q, q)],
            ["set", self.line, ["var", n], ["bin", "plus", self.call("bn_idx", q), ["num", 1]]],
            ["if", self.line, ["cmp", "ge", ["var", n], ["num", 1 << 40]], [self.rterror("this 'for' loop would run too long")], None]], None])
        k, iv = self.fresh("k"), self.fresh("i")
        self.setv(k, ["num", 0])
        i = self.varloc(var)
        hv = self.tmp()
        self.loop_depth += 1
        body = self.block(s[6])
        self.loop_depth -= 1
        head = [["set", self.line, ["var", iv], ["var", k]],
                ["aug", self.line, "add", ["num", 1], ["var", k]],
                ["exprstmt", self.line, self.call("bn_small", hv, ["var", iv])],
                ["exprstmt", self.line, self.call("bn_mul", hv, hv, stp)],
                ["exprstmt", self.line, self.call("bn_add", i, a0, hv)]]
        self.emit(["repeat", self.line, ["var", n], head + body])

    def s_for(self, s):
        if self.bd:
            return self.s_for_bd(s)
        var, start, end, step = s[2], s[3], s[4], s[5]
        cnt, lim = self.hidden(), self.hidden()
        self.X(start, cnt)
        self.X(end, lim)
        if step is None:
            stp = self.const(1)
        elif step[0] == "num":
            stp = self.const(int(step[1]))
        else:
            stp = self.hidden()
            self.X(step, stp)
        self.check(["cmp", "eq", self.call("bn_iszero", stp), ["num", 1]], "step")
        dn = self.small(self.call("bn_isneg", stp), "d")
        first = self.small(["num", 1], "g")
        i = self.varloc(var)
        c = self.fresh("c")
        self.loop_depth += 1
        body = self.block(s[6])
        self.loop_depth -= 1
        head = [
            ["if", self.line, ["cmp", "eq", ["var", first], ["num", 0]],
             [["exprstmt", self.line, self.call("bn_add", cnt, cnt, stp)]], [["set", self.line, ["var", first], ["num", 0]]]],
            ["set", self.line, ["var", c], self.call("bn_cmp", cnt, lim)],
            ["if", self.line, ["cmp", "eq", ["var", dn], ["num", 0]],
             [["if", self.line, ["cmp", "eq", ["var", c], ["num", 2]], [["stop", self.line]], None]],
             [["if", self.line, ["cmp", "eq", ["var", c], ["num", 0]], [["stop", self.line]], None]]],
            ["exprstmt", self.line, self.call("bn_copy", i, cnt)],
        ]
        self.emit(["repeat", self.line, None, head + body])

    def s_foreach(self, s):
        var, arr = s[2], s[3][1]
        base, n = self.arrays[arr]
        k, km = self.fresh("k"), self.fresh("m")
        self.setv(k, ["num", 0])
        v = self.varloc(var)
        self.loop_depth += 1
        body = self.block(s[4])
        self.loop_depth -= 1
        head = [["aug", self.line, "add", ["num", 1], ["var", k]],
                ["set", self.line, ["var", km], ["bin", "minus", ["var", k], ["num", 1]]],
                ["exprstmt", self.line, self.call("bn_copy", v, ["bin", "plus", ["num", base], ["bin", "times", ["var", km], ["num", self.L]]])]]
        self.emit(["repeat", self.line, ["num", n], head + body])

    def s_stop(self, s):
        self.emit(["stop", s[1]])

    def s_skip(self, s):
        self.emit(["skip", s[1]])

    def s_return(self, s):
        a = self.X(s[2])
        self.do("bn_copy", ["num", RET], a)
        self.emit(["return", self.line, ["num", 0]])

    def s_finish(self, s):
        if s[2] is None:
            self.emit(["finish", self.line, None])
        else:
            self.emit(["finish", self.line, self.call("bn_low", self.X(s[2]))])

    def s_scope(self, s):
        for t in s[2]:
            self.stmt(t)

    def s_action(self, s):
        for t in s[2]:
            self.stmt(t)

    def s_define(self, s):
        raise AssertionError

    # ---- whole program ----------------------------------------------------------------------------
    def local_names(self, f):
        """the names that live in the frame of function F (the compiler's own rule: parameters and what it assigns)"""
        names = list(f[3])
        glob = set()
        seen = set(names)
        for st in all_stmts(f[4]):
            for n in assigned_names(st):
                if n not in seen:
                    seen.add(n)
                    names.append(n)
            if st[0] == "global":
                glob.update(st[2])
        return [n for n in names if n not in glob and n not in self.arrays and not self.is_small(n)]

    def finish_ctx(self, ctx):
        hb = ctx.nloc
        tb = hb + self.L * ctx.hidden
        for node, kind, k in ctx.patches:
            node[1] = (hb if kind == "h" else tb) + k
        ctx.fs[1] = tb + self.L * ctx.maxtemp

    def lower_function(self, f):
        name = f[2]
        body = f[3] if f[0] == "routine" else f[4]
        if f[0] == "routine":
            locs = {}
        else:
            order = self.local_names(f)
            locs = {n: self.L * i for i, n in enumerate(order)}
        ctx = Ctx("func", locs, self.L)
        self.all_ctx.append(ctx)
        self.ctx, self.out = ctx, []
        self.line = f[1]
        self.loop_depth = 0
        for st in body:
            self.stmt(st)
        out = self.out
        self.finish_ctx(ctx)
        self.maxfs = max(self.maxfs, ctx.fs[1])
        glob = ["zbn_fp"]
        if f[0] == "routine":
            glob += sorted({n for st in all_stmts(body) for n in assigned_names(st) if self.is_small(n) and n != "input_ok"})
        return ["define", f[1], name, [], [["global", f[1], glob]] + out]

    def bd_constant(self, v, off):
        """store the Big Decimal constant V (a Fraction, or an already made value) at slot OFF"""
        import zoomy_runtime as rt
        try:
            x = rt._BD(*v[1:]) if isinstance(v, tuple) else rt._bd_from_fraction(v.numerator, v.denominator)
        except rt.ZoomyRuntimeError as ex:
            raise self.err(str(ex))
        for i in range(32):
            limb = (x.m >> (32 * i)) & 0xFFFFFFFF
            if limb:
                self.emit(["set", 1, ["index", ["var", "zbn_mem"], ["num", off + i]], ["num", limb]])
        self.emit(["set", 1, ["index", ["var", "zbn_mem"], ["num", off + 32]], ["num", (x.e + (1 << 32)) if x.m else 1 << 32]])
        if x.s and x.m:
            self.emit(["set", 1, ["index", ["var", "zbn_mem"], ["num", off + 33]], ["num", 1]])

    def run(self):
        prog = self.prog
        for name, n in prog.n_arrays.items():
            self.arrays[name] = (self.gslot(self.L * n), n)
        defs, main = [], []
        flat = []
        for s in prog.stmts:
            if s[0] in ("define", "routine"):
                defs.append(s)
            elif s[0] == "action":
                flat += s[2]
            else:
                flat.append(s)
        out_defs = [self.lower_function(f) for f in defs]
        ctx = self.main
        self.ctx, self.out = ctx, []
        self.loop_depth = 0
        for st in flat:
            self.stmt(st)
        main = self.out
        ctx.nloc = self.gtop                        # the main program's hidden values and temporaries sit after everything with a fixed place
        self.finish_ctx(ctx)
        mainsz = ctx.fs[1]
        self.main_fp[1] = mainsz
        self.fp_check[1] = self.capacity - self.maxfs
        if mainsz + self.maxfs > self.capacity:
            raise ZoomyError("this program needs more memory than Big Numbers can use here "
                             "(too many Big Number variables or too large an array)", self.file)
        self.line = 1
        init = [["alloc", 1, "zbn_mem", ["num", self.capacity]], ["set", 1, ["var", "zbn_fp"], ["num", mainsz]]]
        self.ctx, self.out = self.main, init
        for v, off in sorted(self.pool.items(), key=lambda kv: kv[1]):
            if self.bd:
                self.bd_constant(v, off)
            elif 0 <= v < (1 << 63):
                self.do("bn_small", ["num", off], ["num", v])
            elif -(1 << 63) < v < 0:
                self.do("bn_small", ["num", off], ["num", -v])
                self.do("bn_neg", ["num", off], ["num", off])
            else:
                for i in range(self.L):
                    limb = ((v & ((1 << 1024) - 1)) >> (32 * i)) & 0xFFFFFFFF
                    if limb:
                        self.emit(["set", 1, ["index", ["var", "zbn_mem"], ["num", off + i]], ["num", limb]])
        return library(self.bd) + out_defs + init + main


def _eps():
    import zoomy_runtime as rt
    x = rt._BD_EPS
    return ("raw", x.s, x.m, x.e)


_EPS = None


def lower(prog, capacity):
    """the equivalent unsigned 64-bit program (a Program the native and WebAssembly compilers accept)"""
    global _EPS
    _EPS = _EPS or _eps()
    lw = Lowerer(prog, capacity, bool(getattr(prog, "bd", False)))
    stmts = lw.run()
    new = zoomy_py.Program(prog.file)
    new.stmts = stmts
    new.features = set(prog.features)
    new.ints = new.uns = True
    new.big = False
    new.bd = False
    new.funcs = {s[2]: s for s in stmts if s[0] in ("routine", "define")}
    new.uses_extern = False
    if not (new._native_analysis() and new._native_block(new.stmts) and new._char_vars_ok()):
        bad = next((s for s in stmts if not new._native_block([s])), None)
        raise ZoomyError("internal error: the Big Numbers rewrite left the native subset"
                         + (f" (near line {bad[1]})" if bad else ""), prog.file)
    new.native_ok = True
    return new
