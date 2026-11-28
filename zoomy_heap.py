"""Zoomy 8: text, lists and tables for the machine-code compiler.

The program is rewritten into one that only uses numbers and arrays, which the native compiler already takes:
a text, a list or a table becomes a number (a "handle": where it starts in one big shared array, `mem`), and the
work on them is done by a small library written in Zoomy (zoomy_heap.zmy).  Types are worked out from the whole
program first; anything that cannot be typed or is not supported raises Unsupported, and the program then simply
goes to the Python backend as before.  The Python backend stays the reference: tests compare the two."""
import copy
import os
import re

import zoomy_py
from zoomy_py import ZoomyError, all_stmts

HERE = os.path.dirname(os.path.abspath(__file__))
LIB_FILE = os.environ.get("ZOOMY_HEAP_LIB") or os.path.join(HERE, "zoomy_heap.zmy")
LIB_LITS = ["nan", "inf", "-inf", "0", "e", "empty table", "table with ", " and ", " as ", "yes", "no", "[", "]", ", ", "\"",
            "e-", "e+", "nothing", "\\\\", "\\\"", "\\n", "\\t", "empty list"]
LIT_TABLE = 8                       # mem slots 8.. hold the handles of the library's own texts
POOL_BASE = 64                      # the program's literal texts start here
N, T, F = "N", "T", "F"             # number, text, yes/no; lists are ("L", item type), tables ("M", value type)
FLAGS_OK_NOWHERE = "yes/no values inside lists, tables or between functions"
MESSAGES = {}


class Unsupported(Exception):
    pass


def _join(a, b):
    if a is None:
        return b
    if b is None or a == b:
        return a
    if isinstance(a, tuple) and isinstance(b, tuple) and a[0] == b[0]:
        inner = _join(a[1], b[1])
        return (a[0], inner)
    raise Unsupported("a name or place holds different kinds of values (%s and %s)" % (a, b))


def _kind(t):                       # 0 number, 1 text, 2 yes/no: how the library shows or compares an item
    return 1 if t == T else 2 if t == F else 0


def _lib_prefix(node):
    """give the library private names (zh_...)"""
    if isinstance(node, list):
        if node and node[0] == "var" and len(node) == 2 and isinstance(node[1], str):
            if node[1] != "input_ok":
                node[1] = "zh_" + node[1]
            return
        if node and isinstance(node[0], str):
            k = node[0]
            if k == "define" and len(node) > 4:
                node[2] = "zh_" + node[2]
                node[3] = ["zh_" + p for p in node[3]]
            elif k in ("for", "foreach") and len(node) > 2 and isinstance(node[2], str):
                node[2] = "zh_" + node[2]
            elif k == "alloc" and len(node) > 2 and isinstance(node[2], str):
                node[2] = "zh_" + node[2]
            elif k == "global":
                node[2] = ["zh_" + n for n in node[2]]
        for c in node:
            _lib_prefix(c)


def _lib_block(stmts):
    out = []
    for t in stmts:
        if t[0] == "scope":                       # `Structurally:` only matters while reading; the statements move up a level
            out += _lib_block(t[2])
        else:
            out.append(_lib_stmt(t))
    return out


def _lib_stmt(s):
    if s[0] == "fail":
        return ["rterror", s[1], s[2][1][0]]
    out = list(s)
    for i, c in enumerate(out):
        if isinstance(c, list) and c and isinstance(c[0], list):
            out[i] = _lib_block(c)
    if s[0] == "if" and s[4]:
        out[4] = _lib_block(s[4])
    return out


_LIB = None


def library():
    global _LIB
    if _LIB is None:
        path = LIB_FILE
        if os.environ.get("ZOOMY_GC_STRESS"):         # tests: collect at every safe point
            import tempfile
            text = open(path, encoding="utf-8").read()
            text = text.replace("if i is below 24000000:\n            set i to 24000000", "if i is below 0:\n            set i to 0")
            tmp = tempfile.NamedTemporaryFile("w", suffix=".zmy", delete=False, encoding="utf-8")
            tmp.write(text)
            tmp.close()
            path = tmp.name
        lib = zoomy_py.load_program(path)
        stmts = [copy.deepcopy(s) for s in lib.stmts]
        for s in stmts:
            _lib_prefix(s)
        _LIB = [_lib_stmt(s) for s in stmts]
    return copy.deepcopy(_LIB)


def call(name, *args):
    return ["call", ["var", "zh_" + name], list(args), []]


def num(v):
    return ["num", float(v)]


def mem(i):
    return ["index", ["var", "zh_mem"], i]


def bump(op, a, b):
    return ["bin", op, a, b]


class Lower:
    def __init__(self, prog):
        self.prog = prog
        self.env = {}                  # name -> type
        self.params = {}               # function -> [types]
        self.ret = {}                  # function -> type
        self.funcs = {}
        self.arrays = set()            # the program's own number arrays
        self.lits = {}                 # text -> address
        self.pool_end = POOL_BASE
        self.ntemp = 0
        self.line = 1
        self.changed = False
        self.gc_ok = True              # false when a handle could be kept where the collector cannot see it
        self.unset = set()
        self.params_of = set()
        self.seen = set(["input_ok"])          # every name that is set, read into, looped over or taken as a parameter

    # ------------------------------------------------------------ literals
    def lit(self, text):
        for ch in text:
            pass
        if text not in self.lits:
            self.lits[text] = self.pool_end
            self.pool_end += len(text) + 1
        return num(self.lits[text])

    # ------------------------------------------------------------ types
    def setv(self, name, t):
        self.seen.add(name)
        if t is None:
            return
        if t == F and False:
            return
        old = self.env.get(name)
        new = _join(old, t)
        if new != old:
            self.env[name] = new
            self.changed = True

    def inner_ok(self, t):
        if isinstance(t, tuple) and isinstance(t[1], tuple):
            raise Unsupported("a list or table inside a list or table")
        return t

    def ty(self, e):
        k = e[0]
        if k == "num":
            return N
        if k == "bool":
            return F
        if k == "none":
            return None
        if k == "str":
            for p in e[1]:
                if not isinstance(p, str):
                    t = self.ty(p)
            return T
        if k == "var":
            n = e[1]
            if n == "input_ok":
                return N
            if n in self.arrays:
                return "A"
            if n not in self.seen and n not in self.params_of:
                self.unset.add(n)
            if n in ("pi", "e", "infinity", "nan") and n not in self.env:
                return N
            if n in self.funcs:
                raise Unsupported("a function used as a value")
            return self.env.get(n)
        if k == "list":
            it = None
            for x in e[1]:
                it = _join(it, self.inner_ok(self.ty(x)))
            if it is not None and isinstance(it, tuple):
                raise Unsupported("a list inside a list")
            return ("L", it)
        if k == "table":
            vt = None
            for a, b in e[1]:
                if self.ty(a) not in (T, None):
                    raise Unsupported("a table with keys that are not text")
                vt = _join(vt, self.inner_ok(self.ty(b)))
            return ("M", vt)
        if k == "bin":
            a, b = self.ty(e[2]), self.ty(e[3])
            if e[1] == "plus":
                if a == T and b == T:
                    return T
                if isinstance(a, tuple) and a[0] == "L" and isinstance(b, tuple) and b[0] == "L":
                    return ("L", _join(a[1], b[1]))
                if a is None or b is None:
                    return a or b
            if a not in (N, None) or b not in (N, None):
                raise Unsupported("arithmetic on something that is not a number")
            return N
        if k == "neg":
            return N
        if k == "bitop":
            raise Unsupported("bit operations")
        if k in ("not", "and", "or"):
            for x in e[1:]:
                self.ty(x)
            return F
        if k == "cmp":
            a, b = self.ty(e[2]), self.ty(e[3])
            if e[1] == "in":
                a, b = b, a
                e = ["cmp", "contains", e[2], e[3]]
            if e[1] == "contains":
                if isinstance(a, tuple) and a[0] == "M" and b not in (T, None):
                    raise Unsupported("table keys that are not text")
                if a is not None and not isinstance(a, tuple) and a != T:
                    raise Unsupported("contains on " + str(a))
                if isinstance(a, tuple) and a[0] == "L" and a[1] is None and b is not None:
                    pass
                return F
            if isinstance(a, tuple) or isinstance(b, tuple):
                raise Unsupported("comparing lists or tables")
            if F in (a, b) and e[1] not in ("eq", "ne"):
                raise Unsupported("ordering yes/no values")
            if a is not None and b is not None and a != b:
                raise Unsupported("comparing different kinds of values")
            return F
        if k == "is":
            a = self.ty(e[2])
            if e[1] != "empty":
                raise Unsupported("'is a number/list/...' checks")
            return F
        if k == "index":
            c, key = self.ty(e[1]), self.ty(e[2])
            if c == "A":
                return N
            if c == T:
                return T
            if isinstance(c, tuple):
                if c[0] == "M" and key not in (T, None):
                    raise Unsupported("table keys that are not text")
                return c[1]
            return None
        if k == "fn":
            return self.ty_fn(e)
        if k == "call":
            return self.ty_call(e)
        raise Unsupported("'%s'" % k)

    def ty_fn(self, e):
        f, args = e[1], e[2]
        ts = [self.ty(a) for a in args]
        t0 = ts[0] if ts else None
        if f in ("sqrt", "abs", "floor", "ceil", "round", "sin", "cos", "tan", "atan", "ln", "exp", "rem", "pow"):
            return N
        if f == "len":
            return N
        if f in ("upper", "lower", "trim"):
            return T
        if f == "text":
            return T
        if f == "numfrom":
            return N
        if f == "sum":
            return N
        if f in ("sorted",):
            return t0 if isinstance(t0, tuple) else None
        if f == "reversed":
            return t0
        if f in ("first", "last", "min", "max"):
            if t0 == T:
                raise Unsupported("first/last/min/max of text")
            return t0[1] if isinstance(t0, tuple) else None
        if f == "ask":
            return T
        if f == "rounded":
            return N
        if f == "keys":
            return ("L", T)
        if f == "values":
            return ("L", t0[1]) if isinstance(t0, tuple) and t0[0] == "M" else None
        if f == "split":
            return ("L", T)
        if f == "join":
            return T
        if f == "replace":
            return T
        if f == "position" or f == "count":
            return N
        if f == "code":
            return N
        if f == "chr":
            return T
        raise Unsupported("the function '%s'" % f)

    def ty_call(self, e):
        f, args, kw = e[1], e[2], e[3]
        if f[0] != "var" or f[1] not in self.funcs or kw:
            raise Unsupported("a call to something that is not a Zoomy function")
        fs = self.funcs[f[1]]
        if fs[0] != "define" or len(fs[3]) != len(args):
            raise Unsupported("a function called with the wrong number of values")
        for p, a in zip(fs[3], args):
            self.setv(p, self.inner_ok(self.ty(a)) if self.ty(a) not in (None,) else None)
        return self.ret.get(f[1])

    # ------------------------------------------------------------ type inference over statements
    def infer_stmt(self, s):
        k = s[0]
        self.line = s[1] if len(s) > 1 and isinstance(s[1], int) else self.line
        if k == "set":
            t = self.ty(s[3])
            if s[2][0] == "var":
                if s[2][1] in self.arrays:
                    raise Unsupported("an array used as a plain value")
                self.setv(s[2][1], t)
            elif s[2][0] == "index":
                self.place_store(s[2], t)
            else:
                raise Unsupported("attributes")
        elif k == "aug":
            vt = self.ty(s[3])
            p = s[4]
            if p[0] == "var":
                cur = self.env.get(p[1])
                if s[2] == "add" and (cur in (T,) or isinstance(cur, tuple)):
                    self.setv(p[1], _join(cur, vt))
                else:
                    self.setv(p[1], N)
            elif p[0] == "index":
                self.place_store(p, N if s[2] != "add" else vt)
        elif k == "calc":
            self.ty(s[2])
            self.assign_place(s[3], N)
        elif k == "load":
            self.assign_place(s[4], self.ty(["index", s[2], s[3]]))
        elif k == "store":
            self.place_store(["index", s[2], s[3]], self.ty(s[4]))
        elif k in ("append", "insert"):
            lt = self.ty(s[3])
            vt = self.inner_ok(self.ty(s[2]))
            if k == "insert":
                self.ty(s[4])
            if lt == "A" or lt == T or (isinstance(lt, tuple) and lt[0] == "M"):
                raise Unsupported("append to something that is not a list")
            if s[3][0] == "var" and vt is not None:
                self.setv(s[3][1], ("L", vt))
            elif vt is not None and isinstance(lt, tuple):
                _join(lt, ("L", vt))
        elif k in ("remove", "removeat"):
            self.ty(s[2]); self.ty(s[3])
        elif k in ("sort", "reverse", "clear"):
            self.ty(s[2])
        elif k == "read":
            t = {"num": N, "line": T, "char": N, "byte": N}[s[2]]
            self.assign_place(s[3], t)
        elif k == "convert":
            self.ty(s[3])
            self.assign_place(s[4], N if s[2] == "character" else T)
        elif k == "print":
            for kind, e in s[3]:
                self.ty(e)
        elif k in ("if",):
            self.ty(s[2])
        elif k == "while":
            self.ty(s[2])
        elif k == "repeat":
            if s[2] is not None:
                self.ty(s[2])
        elif k == "foreach":
            it = self.ty(s[3])
            if it == T:
                self.setv(s[2], T)
            elif isinstance(it, tuple):
                self.setv(s[2], T if it[0] == "M" else it[1])
            elif it is not None:
                raise Unsupported("going through something that is not a list, table or text")
        elif k == "for":
            for e in (s[3], s[4], s[5]):
                if e is not None:
                    self.ty(e)
            self.setv(s[2], N)
        elif k == "return":
            if s[2] is not None and self.cur_func:
                t = self.ty(s[2])
                if t is not None:
                    old = self.ret.get(self.cur_func)
                    new = _join(old, t)
                    if new != old:
                        self.ret[self.cur_func] = new
                        self.changed = True
        elif k == "exprstmt":
            self.ty(s[2])
        elif k == "callstore":
            self.assign_place(s[3], self.ty(s[2]))
        elif k == "check":
            self.ty(s[2])
        elif k in ("fail", "warn"):
            pass
        elif k in ("run", "global", "stop", "skip", "finish", "pass", "alloc", "routine", "define", "action", "scope"):
            pass
        else:
            raise Unsupported("the statement '%s'" % k)

    def assign_place(self, p, t):
        if p[0] == "var":
            if p[1] in self.arrays:
                raise Unsupported("an array used as a plain value")
            self.setv(p[1], t)
        elif p[0] == "index":
            self.place_store(p, t)
        else:
            raise Unsupported("attributes")

    def place_store(self, p, t):
        ct = self.ty(p[1])
        self.ty(p[2])
        if ct == "A":
            return
        if ct == T:
            raise Unsupported("changing text letter by letter")
        if t is not None:
            self.inner_ok(t)
        if p[1][0] == "var" and t is not None:
            nm = p[1][1]
            cur = self.env.get(nm)
            if isinstance(cur, tuple) and cur[0] == "M":
                self.setv(nm, ("M", t))
            elif isinstance(cur, tuple):
                self.setv(nm, ("L", t))
        elif isinstance(ct, tuple) and t is not None:
            _join(ct, (ct[0], t))

    def walk_infer(self, stmts):
        for s in stmts:
            if s[0] in ("define", "routine"):
                self.cur_func = s[2]
                self.walk_infer(s[4] if s[0] == "define" else s[3])
                self.cur_func = None
                continue
            if s[0] == "action":
                self.walk_infer(s[2])
                continue
            self.infer_stmt(s)
            for blk in zoomy_py.nested_blocks(s):
                self.walk_infer(blk)

    def infer(self):
        stmts = self.prog.stmts
        for s in all_stmts(stmts):
            if s[0] == "alloc":
                if len(s) > 4 and s[4] == "shared":
                    raise Unsupported("shared arrays")
                self.arrays.add(s[2])
            if s[0] in ("define", "routine"):
                self.funcs[s[2]] = s
                if s[0] == "define":
                    self.params_of.update(s[3])
            if s[0] == "global":
                self.seen.update(s[2])
        self.cur_func = None
        for _ in range(16):
            self.changed = False
            self.walk_infer(stmts)
            if not self.changed:
                break
        else:
            raise Unsupported("types did not settle")
        self.unset = {n for n in self.unset if n not in self.seen}
        if self.unset:
            raise Unsupported("a variable that is read but never set: " + sorted(self.unset)[0])
        for n, t in list(self.env.items()):
            if isinstance(t, tuple) and t[1] is None:
                self.env[n] = (t[0], N)
        for n, t in list(self.ret.items()):
            if isinstance(t, tuple) and t[1] is None:
                self.ret[n] = (t[0], N)
        # types that settled need a second look: unknown list items became numbers, so retype once more
        for _ in range(4):
            self.changed = False
            self.walk_infer(stmts)
            if not self.changed:
                break

    # ------------------------------------------------------------ rewriting
    def tmp(self):
        self.ntemp += 1
        return "zh_t%d" % self.ntemp

    def emit(self, *st):
        self.out.extend(st)

    def S(self, kind, *rest):
        return [kind, self.line] + list(rest)

    def ex_text(self, e):
        """expression e as text (handle)"""
        t = self.ty(e)
        x = self.lx(e)
        if t == T:
            return x
        if t == N:
            return call("num2text", x)
        if t == F:
            return call("show_plain", x, num(2))
        if isinstance(t, tuple):
            return self.show_container(x, t)
        raise Unsupported("showing this as text")

    def show_container(self, x, t):
        if t[0] == "L":
            return call("lshow", x, num(_kind(t[1])))
        return call("tbshow", x, num(_kind(t[1])))

    def lx(self, e):
        k = e[0]
        if k == "num":
            return e
        if k == "bool":
            return num(1 if e[1] else 0)
        if k == "none":
            return num(0)
        if k == "str":
            if all(isinstance(p, str) for p in e[1]):
                return self.lit("".join(e[1]))
            pieces = [self.lit(p) if isinstance(p, str) else self.ex_text(p) for p in e[1] if p != ""]
            x = pieces[0]
            for p in pieces[1:]:
                x = call("tcat", x, p)
            return x
        if k == "var":
            if e[1] in self.arrays:
                raise Unsupported("an array used as a value")
            if self.ty(e) is None and e[1] != "input_ok" and e[1] not in ("pi",) and e[1] in self.env:
                raise Unsupported("a variable without a known kind")
            return e
        if k == "list":
            t = self.tmp()
            self.emit(self.S("set", ["var", t], call("lnew", num(len(e[1])))))
            for it in e[1]:
                self.emit(self.S("exprstmt", call("lpush", ["var", t], self.lx(it))))
            return ["var", t]
        if k == "table":
            t = self.tmp()
            self.emit(self.S("set", ["var", t], call("tbnew")))
            for a, b in e[1]:
                self.emit(self.S("exprstmt", call("tbput", ["var", t], self.lx(a), self.lx(b))))
            return ["var", t]
        if k == "bin":
            t = self.ty(e)
            a, b = self.lx(e[2]), self.lx(e[3])
            if t == T:
                return call("tcat", a, b)
            if isinstance(t, tuple):
                return call("lconcat", a, b)
            if e[1] in ("plus", "minus", "times", "divide", "mod", "pow"):
                return ["bin", e[1], a, b]
            raise Unsupported("operator " + e[1])
        if k == "neg":
            return ["neg", self.lx(e[1])]
        if k in ("not", "and", "or", "cmp", "is"):
            return self.to_num(self.lcond(e))
        if k == "index":
            c = self.ty(e[1])
            if c == "A":
                return ["index", e[1], self.lx(e[2])]
            h, key = self.lx(e[1]), self.lx(e[2])
            if c == T:
                return call("tat", h, key)
            if c[0] == "L":
                return call("lget", h, key)
            return call("tbget", h, key)
        if k == "fn":
            return self.lx_fn(e)
        if k == "call":
            f, args = e[1], e[2]
            return ["call", f, [self.lx(a) for a in args], []]
        raise Unsupported(k)

    def lcond(self, e):
        """e as a condition the native compiler understands"""
        k = e[0]
        if k == "bool":
            return e
        if k == "not":
            return ["not", self.lcond(e[1])]
        if k in ("and", "or"):
            return [k, self.lcond(e[1]), self.lcond(e[2])]
        if k == "cmp":
            return self.lx_cmp(e)
        if k == "is":
            t = self.ty(e[2])
            x = self.lx(e[2])
            if t is None or t == N or t == F:
                raise Unsupported("'is empty' on a number")
            c = ["cmp", "eq", call("llen", x), num(0)]
            return ["not", c] if e[3] else c
        return ["cmp", "ne", self.lx(e), num(0)]            # a yes/no kept as 0 or 1

    def to_num(self, c):
        """a condition as the number 0 or 1"""
        if c[0] == "bool":
            return num(1 if c[1] else 0)
        t = self.tmp()
        self.emit(self.S("set", ["var", t], num(0)))
        self.emit(self.S("if", c, [self.S("set", ["var", t], num(1))], None))
        return ["var", t]

    def lx_cmp(self, e):
        op = e[1]
        a, b = e[2], e[3]
        if op == "in":
            a, b = b, a
            op = "contains"
        ta, tb = self.ty(a), self.ty(b)
        if op == "contains":
            x, y = self.lx(a), self.lx(b)
            if ta == T:
                return ["cmp", "ge", call("tfind", x, y, num(0)), num(0)]
            if ta[0] == "L":
                return ["cmp", "ge", call("lindex", x, y, num(_kind(ta[1]))), num(0)]
            return ["cmp", "eq", call("tbhas", x, y), num(1)]
        if op in ("starts", "ends"):
            if ta != T or tb != T:
                raise Unsupported("starts/ends on something that is not text")
            return ["cmp", "eq", call("t" + op, self.lx(a), self.lx(b)), num(1)]
        if ta == T and tb == T:
            x, y = self.lx(a), self.lx(b)
            if op == "eq":
                return ["cmp", "eq", call("teq", x, y), num(1)]
            if op == "ne":
                return ["cmp", "eq", call("teq", x, y), num(0)]
            return ["cmp", op, call("tcmp", x, y), num(0)]
        if ta in (N, None, F) and tb in (N, None, F):
            return ["cmp", op, self.lx(a), self.lx(b)]
        raise Unsupported("this comparison")

    def lx_fn(self, e):
        f, args = e[1], e[2]
        ts = [self.ty(a) for a in args]
        xs = [self.lx(a) for a in args]
        t0 = ts[0] if ts else None
        if f in ("sqrt", "abs", "floor", "ceil", "round", "sin", "cos", "tan", "atan", "ln", "exp", "rem", "pow"):
            return ["fn", f, xs]
        if f == "len":
            if t0 == T:
                return call("tlen", xs[0])
            if isinstance(t0, tuple):
                return call("llen", xs[0])
            raise Unsupported("length of this")
        if f == "upper":
            return call("tupper", xs[0])
        if f == "lower":
            return call("tlower", xs[0])
        if f == "trim":
            return call("ttrim", xs[0])
        if f == "text":
            return self.ex_text(args[0])
        if f == "numfrom":
            if t0 != T:
                raise Unsupported("numfrom of a number")
            return call("numfrom", xs[0])
        if f == "sum":
            return call("lsum", xs[0])
        if f == "sorted":
            return call("lsorted", xs[0], num(_kind(t0[1])))
        if f == "reversed":
            return call("trev", xs[0]) if t0 == T else call("lreversed", xs[0])
        if f in ("min", "max"):
            return call("lextreme", xs[0], num(0 if f == "min" else 1), num(_kind(t0[1])))
        if f == "first":
            return call("lfirst", xs[0])
        if f == "last":
            return call("llast", xs[0])
        if f == "ask":
            self.emit(self.S("exprstmt", call("wtext", self.ex_text(args[0]))))
            t = self.tmp()
            self.emit(self.S("set", ["var", t], call("read_line")))
            self.emit(self.S("set", ["var", "input_ok"], mem(num(2))))
            return ["var", t]
        if f == "rounded":
            x, n = self.once(xs[0]), self.once(xs[1])
            p, r, a = self.tmp(), self.tmp(), self.tmp()
            self.emit(self.S("set", ["var", p], ["bin", "pow", num(10), n]))
            self.emit(self.S("set", ["var", a], ["fn", "abs", [x]]))
            self.emit(self.S("set", ["var", r], ["bin", "divide", ["fn", "floor", [["bin", "plus", ["bin", "times", ["var", a], ["var", p]], num(0.5)]]], ["var", p]]))
            self.emit(self.S("if", ["cmp", "lt", x, num(0)], [self.S("set", ["var", r], ["neg", ["var", r]])], None))
            return ["var", r]
        if f == "keys":
            return call("tbkeys", xs[0])
        if f == "values":
            return call("tbvalues", xs[0])
        if f == "split":
            return call("tsplit", xs[0], xs[1])
        if f == "join":
            return call("ljoin", xs[0], xs[1], num(_kind(t0[1])))
        if f == "replace":
            return call("treplace", xs[2], xs[0], xs[1])
        if f == "position":
            if ts[1] == T:
                return call("tfind", xs[1], xs[0], num(0))
            return call("lindex", xs[1], xs[0], num(_kind(ts[1][1])))
        if f == "count":
            return call("tcount", xs[1], xs[0])
        if f == "code":
            return call("tcode", xs[0])
        if f == "chr":
            return call("tchar", xs[0])
        raise Unsupported("the function " + f)

    # ----- statements
    def block(self, stmts):
        saved, self.out = self.out, []
        for s in stmts:
            self.stmt(s)
        res, self.out = self.out, saved
        return res

    def simple(self, x):
        return x[0] in ("num", "var")

    def once(self, x):
        """x evaluated once: itself when it is a name or number, else a temporary"""
        if self.simple(x):
            return x
        t = self.tmp()
        self.emit(self.S("set", ["var", t], x))
        return ["var", t]

    def store_to(self, place, v, vt):
        """emit: place = v"""
        if place[0] == "var":
            self.emit(self.S("set", place, v))
            return
        c = self.ty(place[1])
        if c == "A":
            if vt != N:
                self.gc_ok = False
            self.emit(self.S("set", ["index", place[1], self.lx(place[2])], v))
            return
        h, key = self.lx(place[1]), self.lx(place[2])
        if c[0] == "L":
            self.emit(self.S("exprstmt", call("lset", h, key, v)))
        else:
            self.emit(self.S("exprstmt", call("tbput", h, key, v)))

    def stmt(self, s):
        k = s[0]
        self.line = s[1] if len(s) > 1 and isinstance(s[1], int) else self.line
        m = getattr(self, "st_" + k, None)
        if m is None:
            raise Unsupported("the statement '%s'" % k)
        m(s)

    def st_set(self, s):
        v = self.lx(s[3])
        self.store_to(s[2], v, self.ty(s[3]))

    def st_calc(self, s):
        self.store_to(s[3], self.lx(s[2]), N)

    def st_load(self, s):
        self.store_to(s[4], self.lx(["index", s[2], s[3]]), self.ty(["index", s[2], s[3]]))

    def st_store(self, s):
        self.store_to(["index", s[2], s[3]], self.lx(s[4]), self.ty(s[4]))

    def st_aug(self, s):
        op, val, place = s[2], s[3], s[4]
        names = {"add": "plus", "sub": "minus", "mul": "times", "div": "divide"}
        if place[0] == "var":
            t = self.env.get(place[1])
            if t == T and op == "add":
                self.emit(self.S("set", place, call("tcat", place, self.lx(val))))
            elif isinstance(t, tuple) and op == "add":
                self.emit(self.S("set", place, call("lconcat", place, self.lx(val))))
            else:
                self.emit(self.S("aug", op, self.lx(val), place))
            return
        c = self.ty(place[1])
        if c == "A":
            self.emit(self.S("aug", op, self.lx(val), ["index", place[1], self.lx(place[2])]))
            return
        h = self.once(self.lx(place[1]))
        key = self.once(self.lx(place[2]))
        cur = call("lget", h, key) if c[0] == "L" else call("tbget", h, key)
        v = self.lx(val)
        if c[1] == T:
            new = call("tcat", cur, v)
        else:
            new = ["bin", names[op], cur, v]
        self.emit(self.S("exprstmt", call("lset", h, key, new) if c[0] == "L" else call("tbput", h, key, new)))

    def st_append(self, s):
        self.emit(self.S("exprstmt", call("lpush", self.lx(s[3]), self.lx(s[2]))))

    def st_insert(self, s):
        self.emit(self.S("exprstmt", call("linsert", self.lx(s[3]), self.lx(s[4]), self.lx(s[2]))))

    def st_remove(self, s):
        c = self.ty(s[3])
        if c[0] == "M":
            self.emit(self.S("exprstmt", call("tbdel", self.lx(s[3]), self.lx(s[2]))))
        else:
            self.emit(self.S("exprstmt", call("lremove_val", self.lx(s[3]), self.lx(s[2]), num(_kind(c[1])))))

    def st_removeat(self, s):
        c = self.ty(s[3])
        if c[0] == "M":
            self.emit(self.S("exprstmt", call("tbdel", self.lx(s[3]), self.lx(s[2]))))
        else:
            self.emit(self.S("exprstmt", call("lremove_at", self.lx(s[3]), self.lx(s[2]))))

    def st_sort(self, s):
        c = self.ty(s[2])
        if not (isinstance(c, tuple) and c[0] == "L"):
            raise Unsupported("sorting something that is not a list")
        self.emit(self.S("exprstmt", call("lsort", self.lx(s[2]), num(1 if s[3] else 0), num(_kind(c[1])))))

    def st_reverse(self, s):
        self.emit(self.S("exprstmt", call("lreverse", self.lx(s[2]))))

    def st_clear(self, s):
        c = self.ty(s[2])
        self.emit(self.S("exprstmt", call("lclear" if c[0] == "L" else "tbclear", self.lx(s[2]))))

    def st_read(self, s):
        if s[3][0] != "var":
            raise Unsupported("reading into a list or table item")
        if s[2] == "line":
            self.emit(self.S("set", s[3], call("read_line")))
            self.emit(self.S("set", ["var", "input_ok"], mem(num(2))))
        else:
            self.emit(list(s))

    def st_convert(self, s):
        t = self.ty(s[3])
        if s[2] == "character":
            x = call("tcode", self.lx(s[3])) if t == T else self.lx(s[3])
            self.emit(self.S("convert", "character", x, s[4]))
        else:
            self.store_to(s[4], call("tchar", self.lx(s[3])), T)

    def st_print(self, s):
        items, nl = s[3], s[2]
        group = []

        def flush(last):
            if group or last:
                self.emit(self.S("print", bool(last and nl), list(group)))
                group.clear()
        for kind, e in items:
            if kind == "char":
                group.append(["char", self.lx(e)])
                continue
            t = self.ty(e)
            if e[0] == "str" and all(isinstance(p, str) for p in e[1]):
                group.append(["val", e])
            elif e[0] == "str":
                for p in e[1]:
                    if isinstance(p, str):
                        if p:
                            group.append(["val", ["str", [p]]])
                    else:
                        self.print_value(p, group, flush)
            else:
                self.print_value(e, group, flush)
        flush(True)

    def print_value(self, e, group, flush):
        t = self.ty(e)
        if t == N or t is None:
            group.append(["val", self.lx(e)])
            return
        if t == T:
            x = self.lx(e)
        elif t == F:
            x = call("show_plain", self.lx(e), num(2))
        else:
            x = self.show_container(self.lx(e), t)
        flush(False)
        self.emit(self.S("exprstmt", call("wtext", x)))

    def cond(self, e, loop=False):
        saved, self.out = self.out, []
        x = self.lcond(e)
        pre, self.out = self.out, saved
        if pre and loop:
            raise Unsupported("a list or table written inside a loop condition")
        self.out.extend(pre)
        return x

    def st_if(self, s):
        c = self.cond(s[2])
        out = ["if", s[1], c, self.block(s[3]), self.block(s[4]) if s[4] is not None else None] + list(s[5:])
        self.emit(out)

    def st_while(self, s):
        self.emit(self.S("while", self.cond(s[2], True), self.block(s[3])))

    def st_repeat(self, s):
        self.emit(self.S("repeat", self.lx(s[2]) if s[2] is not None else None, self.block(s[3])))

    def mutates(self, body):
        for st in all_stmts(body):
            if st[0] in ("append", "insert", "remove", "removeat", "sort", "reverse", "clear", "store", "run", "exprstmt", "callstore"):
                return True
            if st[0] in ("set", "aug", "load", "calc") and any(p[0] == "index" for p in ([st[2]] if st[0] == "set" else [st[4]] if st[0] == "aug" else [st[3]] if st[0] == "calc" else [st[4]])):
                return True
            if st[0] in ("set", "print", "if", "while"):
                for e in _exprs(st):
                    if _has_call(e):
                        return True
        return False

    def st_foreach(self, s):
        it = self.ty(s[3])
        x = self.lx(s[3])
        h, n, i = self.tmp(), self.tmp(), self.tmp()
        if it == T:
            self.emit(self.S("set", ["var", h], x))
            self.emit(self.S("set", ["var", n], call("tlen", ["var", h])))
            elem = call("tchar", call("tget", ["var", h], ["var", i]))
        elif it[0] == "M":
            self.emit(self.S("set", ["var", h], call("tbkeys", x)))
            self.emit(self.S("set", ["var", n], call("llen", ["var", h])))
            elem = call("lget", ["var", h], ["var", i])
        else:
            copy_it = self.mutates(s[4]) or s[3][0] != "var"
            self.emit(self.S("set", ["var", h], call("lcopy", x) if self.mutates(s[4]) else x))
            self.emit(self.S("set", ["var", n], call("llen", ["var", h])))
            elem = call("lget", ["var", h], ["var", i])
        body = [self.S("set", ["var", s[2]], elem)] + self.block(s[4])
        self.emit(self.S("for", i, num(0), ["bin", "minus", ["var", n], num(1)], None, body))

    def st_for(self, s):
        self.emit(self.S("for", s[2], self.lx(s[3]), self.lx(s[4]), self.lx(s[5]) if s[5] is not None else None, self.block(s[6])))

    def st_stop(self, s):
        self.emit(list(s))

    st_skip = st_stop
    def st_finish(self, s):
        self.emit(self.S("finish", self.lx(s[2]) if s[2] is not None else None))

    st_pass = st_stop
    st_global = st_stop
    st_alloc = st_stop

    def static_message(self, e):
        if e[0] != "str" or not all(isinstance(p, str) for p in e[1]):
            raise Unsupported("a message that is built while running")
        return "".join(e[1])

    def st_fail(self, s):
        name = os.path.basename(self.prog.file)
        self.emit(["rterror", s[1], "%s (%s, line %d)" % (self.static_message(s[2]), name, s[1]), 1])

    def st_check(self, s):
        name = os.path.basename(self.prog.file)
        self.emit(self.S("if", ["not", self.cond(s[2])],
                         [["rterror", s[1], "check failed: %s (%s, line %d)" % (s[3], name, s[1]), 1]], None))

    def st_warn(self, s):
        self.emit(["warnmsg", s[1], self.static_message(s[2])])

    def st_scope(self, s):
        for t in s[2]:
            self.stmt(t)

    def st_run(self, s):
        self.emit(list(s))

    def st_return(self, s):
        self.emit(self.S("return", self.lx(s[2]) if s[2] is not None else None))

    def st_exprstmt(self, s):
        self.emit(self.S("exprstmt", self.lx(s[2])))

    def st_callstore(self, s):
        x = self.lx(s[2])
        self.store_to(s[3], x, None)

    def lower_func(self, f):
        self.cur_func = f[2]
        if f[0] == "define":
            body = self.block(f[4])
            res = ["define", f[1], f[2], f[3], body]
        else:
            res = ["routine", f[1], f[2], self.block(f[3])]
        self.cur_func = None
        return res

    # ------------------------------------------------------------ garbage collection
    def gc_names(self, stmts):
        """the names of the top level variables: where every live handle is kept while the top level code runs"""
        names = set()
        libnames = set(s[2] for s in library() if s[0] == "define")

        def walk(x):
            if isinstance(x, list):
                if len(x) == 2 and x[0] == "var" and isinstance(x[1], str):
                    names.add(x[1])
                    return
                if x and x[0] == "for" and len(x) > 2 and isinstance(x[2], str):
                    names.add(x[2])
                for c in x:
                    walk(c)
        walk(stmts)
        keep = []
        for n in sorted(names):
            if n in self.arrays or n in self.funcs or n in libnames or n in ("input_ok", "pi", "e", "infinity", "nan"):
                continue
            if n.startswith("zh_") and not re.fullmatch(r"zh_t\d+", n):
                continue
            keep.append(n)
        return keep

    def gc_instrument(self, main):
        names = self.gc_names(main)
        if len(names) > 8000:
            return main
        safepoint = [self.S("if", ["cmp", "gt", ["bin", "plus", mem(num(1)), mem(num(4))], mem(num(3))],
                            [self.S("set", ["index", ["var", "zh_gcr"], num(i)], ["var", n]) for i, n in enumerate(names)]
                            + [self.S("exprstmt", call("gc_collect", num(len(names))))], None)]

        def walk(stmts):
            out = []
            for s in stmts:
                k = s[0]
                if k == "for":
                    s = list(s)
                    s[6] = safepoint + walk(s[6])
                elif k in ("while", "repeat"):
                    s = list(s)
                    s[3] = safepoint + walk(s[3])
                elif k == "if":
                    s = list(s)
                    s[3] = walk(s[3])
                    if s[4]:
                        s[4] = walk(s[4])
                out.append(s)
            return out
        return walk(main)

    def run(self):
        self.out = []
        defs, flat = [], []
        for s in self.prog.stmts:
            if s[0] in ("define", "routine"):
                defs.append(s)
            elif s[0] == "action":
                flat += s[2]
            else:
                flat.append(s)
        out_defs = [self.lower_func(f) for f in defs]
        self.out = []
        for st in flat:
            self.stmt(st)
        main = self.out
        no_gc = not self.gc_ok or os.environ.get("ZOOMY_NO_GC") or any(
            s[0] == "workers" or (s[0] == "alloc" and len(s) > 4 and s[4] == "shared") for s in all_stmts(self.prog.stmts))
        if not no_gc:
            main = self.gc_instrument(main)
        init = [["set", 1, mem(num(1)), num(0)]]          # patched below
        for k, text in enumerate(LIB_LITS):
            self.lit(text)
        for k, text in enumerate(LIB_LITS):
            init.append(["set", 1, mem(num(LIT_TABLE + k)), num(self.lits[text])])
        for text, addr in sorted(self.lits.items(), key=lambda kv: kv[1]):
            init.append(["set", 1, mem(num(addr)), num(len(text))])
            for i, ch in enumerate(text):
                init.append(["set", 1, mem(num(addr + 1 + i)), num(ord(ch))])
        init[0] = ["set", 1, mem(num(1)), num(self.pool_end)]
        init.append(["set", 1, mem(num(6)), num(self.pool_end)])
        init.append(["set", 1, mem(num(3)), num(self.pool_end + (0 if os.environ.get("ZOOMY_GC_STRESS") else 24000000))])
        if self.pool_end > 3_000_000:
            raise Unsupported("too much literal text")
        return library() + out_defs + init + main


def _exprs(st):
    return zoomy_py.stmt_exprs(st)


def _has_call(e):
    found = []

    def f(x):
        if x[0] == "call":
            found.append(1)
    zoomy_py.walk(e, f)
    return bool(found)


def lower(prog):
    """the equivalent program for the native compiler, or Unsupported"""
    if getattr(prog, "ints", False) or getattr(prog, "big", False) or getattr(prog, "bd", False):
        raise Unsupported("integer mode and Big Numbers use the other rewrites")
    if getattr(prog, "uses_extern", False):
        raise Unsupported("extern")
    lw = Lower(prog)
    try:
        lw.infer()
        stmts = lw.run()
    except (Unsupported, ZoomyError):
        raise
    except Exception as why:                      # anything unexpected: the Python backend still runs the program
        raise Unsupported("internal: %s: %s" % (type(why).__name__, why))
    new = zoomy_py.Program(prog.file)
    new.stmts = stmts
    new.features = set(prog.features)
    new.ints = new.uns = False
    new.big = False
    new.bd = False
    new.funcs = {s[2]: s for s in stmts if s[0] in ("routine", "define")}
    new.uses_extern = False
    if not (new._native_analysis() and new._native_block(new.stmts) and new._char_vars_ok()):
        bad = None
        for s in stmts:
            new.why_not = None
            if not new._native_block([s]):
                bad = new.why_not
                break
        raise Unsupported("the rewritten program is outside what the native compiler takes" + (f" (a '{bad[1]}' statement near line {bad[0]})" if bad else ""))
    new.native_ok = True
    return new
