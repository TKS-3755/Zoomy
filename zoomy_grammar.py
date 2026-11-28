#!/usr/bin/env python3
"""
Zoomy 5 grammar layer (introduced in Zoomy 4): English grammar rules with a job to do.

  a / an   Let / Create / Define introduce a NEW name (scope) and its type:  Let a number be called total
  the      refers to something that already exists:                  add 1 to the total
  plurals  a plural name holds several things (a list); pair / triple / quad are fixed groups
  's       possessives reach inside things:                           the player's score, math's sqrt(2)
  first .. tenth, last   ordinals pick items:                         the third score of the scores
  is / are, contains / contain   must agree with what the subject is

The front end (zoomy_py.Front) parses these forms into 'let' / 'decl' nodes and a few extra fields.
This module walks the finished statement tree once and
  * resolves every name with lexical scoping (a block's names end with its indentation),
  * gives every distinct variable its own unique name, so both back ends (native and Python) see plain variables,
  * checks types and agreement, with errors that say how to fix the line.
Code under 'Simply,' follows the old rules (bare names, no checks).
"""
import difflib

import zoomy_py as zp

ZoomyError = zp.ZoomyError

# ---------------------------------------------------------------------------- plurals
IRREGULAR = {"children": "child", "people": "person", "men": "man", "women": "woman", "mice": "mouse", "feet": "foot",
             "teeth": "tooth", "geese": "goose", "indices": "index", "vertices": "vertex", "matrices": "matrix",
             "axes": "axis", "criteria": "criterion", "bases": "base", "analyses": "analysis", "leaves": "leaf",
             "lives": "life", "knives": "knife", "wolves": "wolf", "halves": "half", "shelves": "shelf"}
NOT_PLURAL = {"news", "series", "species", "lens", "bias", "canvas", "atlas", "alias", "gas", "chaos", "this", "his",
              "yes", "thus", "plus", "minus", "times", "its", "process", "status", "class", "mass", "pass", "loss"}
ITEM_NOUNS = {"item", "element", "entry", "value", "member", "thing", "one", "number", "text"}


def _split(name):
    head, _, last = name.rpartition("_")
    return (head + "_" if head else ""), last


def is_plural(name):
    last = _split(name)[1].lower()
    if last in IRREGULAR:
        return True
    if len(last) < 3 or last in NOT_PLURAL:
        return False
    if last.endswith(("ss", "us", "is", "ics")):
        return False
    return last.endswith("s")


def singular(name):
    head, last = _split(name)
    low = last.lower()
    if low in IRREGULAR:
        return head + IRREGULAR[low]
    if low.endswith("ies") and len(low) > 3:
        return head + last[:-3] + "y"
    if low.endswith(("ses", "xes", "zes", "ches", "shes")):
        return head + last[:-2]
    if low.endswith("s"):
        return head + last[:-1]
    return name


# ---------------------------------------------------------------------------- types
# a type is: None (unknown / any), "number", "text", "flag", "table", "nothing", "module", ("list", elem), ("tuple", n)
SCALARS = ("number", "text", "flag")
TUPLE_NAMES = {2: "pair", 3: "triple", 4: "quad"}
ELEM_NAMES = {"number": "numbers", "text": "texts", "flag": "flags", "table": "tables", "mixed": "mixed values"}


def tname(t):
    if t is None:
        return "a value"
    if t == "number":
        return "a number"
    if t == "text":
        return "text"
    if t == "flag":
        return "a yes/no flag"
    if t == "table":
        return "a table"
    if t == "nothing":
        return "nothing"
    if t == "module":
        return "a Python library"
    if t[0] == "tuple":
        return "a " + TUPLE_NAMES[t[1]]
    if t[1] is None:
        return "a list"
    if isinstance(t[1], tuple):
        return "a list of lists"
    return "a list of " + ELEM_NAMES.get(t[1], t[1])


def is_list(t):
    return isinstance(t, tuple) and t[0] == "list"


def is_tuple(t):
    return isinstance(t, tuple) and t[0] == "tuple"


def compat(want, got):
    """can a value of type `got` be kept in a variable of type `want`?"""
    if want is None or got is None or want == got:
        return True
    if is_list(want) and is_list(got):
        return want[1] is None or got[1] is None or compat(want[1], got[1]) and got[1] != "mixed"
    return False


def unify(types):
    known = [t for t in types if t is not None]
    if not known:
        return None
    if len(known) < len(types):
        return None
    first = known[0]
    return first if all(t == first for t in known) else "mixed"


class Var:
    __slots__ = ("name", "py", "type", "line", "scope", "extra")

    def __init__(self, name, py, typ, line, scope):
        self.name, self.py, self.type, self.line, self.scope, self.extra = name, py, typ, line, scope, None


class Scope:
    def __init__(self, kind, parent):
        self.kind, self.parent, self.names = kind, parent, {}

    def lookup(self, name, until=None):
        s = self
        while s is not None:
            if name in s.names:
                return s.names[name]
            if s is until:
                return None
            s = s.parent
        return None

    def home(self):
        s = self
        while s.kind not in ("function", "program"):
            s = s.parent
        return s

    def visible(self):
        out, s = [], self
        while s is not None:
            out += list(s.names)
            s = s.parent
        return out


# numeric helpers: name -> (argument types, result type)
NUM_FN = {"sqrt", "abs", "floor", "ceil", "round", "sin", "cos", "tan", "atan", "ln", "exp"}
FN_RESULT = {"len": "number", "upper": "text", "lower": "text", "trim": "text", "text": "text", "numfrom": "number",
             "sum": "number", "keys": ("list", None), "values": ("list", None), "lines": ("list", "text"),
             "code": "number", "chr": "text", "rem": "number", "split": ("list", "text"), "join": "text",
             "replace": "text", "position": "number", "count": "number", "format": "text", "rounded": "number",
             "randnum": "number", "randbetween": "number", "ask": "text", "args": ("list", "text"),
             "exists": "flag", "now": "number"}


class Resolver:
    def __init__(self, file):
        self.file = file
        self.line = 0
        self.simply = False
        self.used = set()
        self.builtin = Scope("builtin", None)
        self.program = Scope("program", self.builtin)
        self.funcs = {}
        self.init = []                       # start-of-program statements for the variables made with `make ... a global ...`
        self.externs = set()
        self.closed = {}
        self.func_stack = []
        v = Var("input_ok", "input_ok", "number", 0, self.builtin)
        self.builtin.names["input_ok"] = v
        self.used.add("input_ok")
        import zoomy_consts
        for nm in zoomy_consts.NAMES:                      # pi, e, tau, c, G ...: read-only, replaced by numbers after parsing
            py = zoomy_consts.py_name(nm)
            self.builtin.names[nm] = Var(nm, py, "number", 0, self.builtin)
            self.used.add(py)

    # ------------------------------------------------------------------ errors
    def err(self, msg):
        return ZoomyError(msg, self.file, self.line)

    def terr(self, msg):
        if not self.simply:
            raise self.err(msg)

    def soft(self, msg):
        """grammar slips (is/are, ordinal nouns) are warnings; --strict makes them errors"""
        if not self.simply:
            zp.soft(self.file, self.line, msg)

    # ------------------------------------------------------------------ names
    def fresh(self, name):
        if name not in self.used:
            self.used.add(name)
            return name
        k = 2
        while f"{name}__{k}" in self.used:
            k += 1
        self.used.add(f"{name}__{k}")
        return f"{name}__{k}"

    def declare(self, sc, name, typ):
        if name in self.funcs:
            raise self.err(f"'{name}' is already the name of a function; pick another name for the variable")
        if name in sc.names:
            old = sc.names[name]
            raise self.err(f"'{name}' already exists here (made on line {old.line}); change it with 'set the {name} to ...' "
                           f"(a new variable of the same name is only allowed inside a deeper block)")
        v = Var(name, self.fresh(name), typ, self.line, sc)
        sc.names[name] = v
        return v

    def close(self, sc):
        for nm, v in sc.names.items():
            self.closed[nm] = v.line

    def undefined(self, name, sc):
        msg = f"I don't know a variable called '{name}'"
        near = difflib.get_close_matches(name, [n for n in sc.visible() if n != "input_ok" and not n.startswith("__")], n=1, cutoff=0.7)
        if name in self.closed:
            msg += (f" at this point: the '{name}' made on line {self.closed[name]} belongs to a block that has ended. "
                    f"Create it before that block (a name lives until the end of the block it was made in)")
        elif near:
            msg += f". Did you mean '{near[0]}'?"
        else:
            msg += f". Make it first with: Let a number be called {name}"
        return self.err(msg)

    def simply_var(self, name, sc, make=True):
        """Old rules: a bare name means the variable of that name in this function (or program), made if it does not exist."""
        home = sc.home()
        fn = self.func_stack[-1] if self.func_stack else None
        if fn is not None and name in fn["globals_decl"]:
            v = self.program.lookup(name, self.program)
            if v is None:
                v = Var(name, self.fresh(name), None, self.line, self.program)
                self.program.names[name] = v
            fn["globals"].add(v.py)
            return v
        v = sc.lookup(name, home)
        if v is None and fn is None:
            v = sc.lookup(name)
        if v is not None and v.scope.kind == "builtin" and v.py.startswith("__"):
            v = None                                         # old rules: a bare name that is a built-in constant makes a variable
        if v is None and make:
            if name in self.funcs:
                raise self.err(f"'{name}' is already the name of a function")
            v = Var(name, self.fresh(name), None, self.line, home)
            home.names[name] = v
        return v

    def note_write(self, v):
        fn = self.func_stack[-1] if self.func_stack else None
        if fn is not None and fn["kind"] == "define" and v.scope.kind == "program":
            fn["globals"].add(v.py)

    # ------------------------------------------------------------------ expressions
    def check_assign(self, want, got, what):
        if not compat(want, got):
            self.terr(f"{what} holds {tname(want)}, but this value is {tname(got)}")

    def expr(self, e, sc):
        k = e[0]
        if k == "num":
            return e, "number"
        if k == "str":
            parts = [p if isinstance(p, str) else self.expr(p, sc)[0] for p in e[1]]
            return ["str", parts], "text"
        if k == "bool":
            return e, "flag"
        if k == "none":
            return e, "nothing"
        if k == "var":
            return self.read(e[1], sc)
        if k in ("list", "tuple"):
            res = [self.expr(x, sc) for x in e[1]]
            items = [r[0] for r in res]
            if k == "tuple":
                return ["tuple", items], ("tuple", len(items))
            return ["list", items] + list(e[2:]), ("list", unify([r[1] for r in res]))
        if k == "table":
            return ["table", [(self.expr(a, sc)[0], self.expr(b, sc)[0]) for a, b in e[1]]], "table"
        if k == "bin":
            return self.binary(e, sc)
        if k == "neg":
            a, ta = self.expr(e[1], sc)
            if ta not in (None, "number"):
                self.terr(f"cannot negate {tname(ta)} (only numbers)")
            return ["neg", a], ("number" if ta == "number" else None)
        if k == "bitop":
            a, ta = self.expr(e[2], sc)
            b = self.expr(e[3], sc)[0] if e[3] is not None else None
            if ta not in (None, "number"):
                self.terr(f"bit operations need a number, not {tname(ta)}")
            return ["bitop", e[1], a, b], "number"
        if k == "not":
            return ["not", self.expr(e[1], sc)[0]], "flag"
        if k in ("and", "or"):
            return [k, self.expr(e[1], sc)[0], self.expr(e[2], sc)[0]], "flag"
        if k == "cmp":
            return self.compare(e, sc)
        if k == "is":
            a, ta = self.expr(e[2], sc)
            self.agree(e[2], ta, e[4] if len(e) > 4 else None)
            return ["is", e[1], a, e[3]], "flag"
        if k == "attr":
            a, ta = self.expr(e[1], sc)
            return ["attr", a, e[2]], None
        if k == "index":
            return self.index(e, sc)
        if k == "call":
            return self.call(e, sc)
        if k == "fn":
            return self.function(e, sc)
        if k in ("filter", "quant"):
            return self.element_expr(e, sc)
        raise self.err(f"internal error: unknown expression '{k}'")

    def element_expr(self, e, sc):
        """scores that are above 80   /   all of scores are above 80: a hidden loop variable lives only inside the condition"""
        lst_i, cond_i, name = (1, 2, e[3]) if e[0] == "filter" else (2, 3, e[4])
        lst, tl = self.expr(e[lst_i], sc)
        if is_list(tl):
            et = tl[1] if tl[1] != "mixed" else None
        elif tl == "text":
            et = "text"
        else:
            et = None
            if tl in ("number", "flag"):
                self.terr(f"cannot go through each item of {tname(tl)}")
        child = Scope("block", sc)
        v = Var(name, self.fresh(name), et, self.line, child)
        child.names[name] = v
        zp.ELEM_VARS.add(v.py)
        cond = self.expr(e[cond_i], child)[0]
        if e[0] == "filter":
            return ["filter", lst, cond, v.py], (tl if is_list(tl) else ("list", et))
        return ["quant", e[1], lst, cond, v.py], "flag"

    def read(self, name, sc):
        v = sc.lookup(name)
        if v is None:
            if name in self.funcs:
                return ["var", name], None
            if not self.simply and name.lower() in zp.zs.NUMBER_WORDS:        # five, twenty, hundred ... when no variable has that name
                return ["num", float(zp.zs.NUMBER_WORDS[name.lower()])], "number"
            if self.simply:
                v = self.simply_var(name, sc)
            else:
                raise self.undefined(name, sc)
        return ["var", v.py], v.type

    def binary(self, e, sc):
        op = e[1]
        a, ta = self.expr(e[2], sc)
        b, tb = self.expr(e[3], sc)
        node = ["bin", op, a, b]
        word = {"plus": "add", "minus": "subtract", "times": "multiply", "divide": "divide", "mod": "take the remainder of",
                "pow": "raise to a power"}[op]
        if op == "plus":
            if ta == tb and (ta in ("number", "text") or is_list(ta)):
                return node, ta
            if ta is None or tb is None:
                return node, None
            self.terr(f"cannot add {tname(ta)} and {tname(tb)} (to join text and numbers use \"{{...}}\" inside the text)")
            return node, None
        for t in (ta, tb):
            if t not in (None, "number"):
                self.terr(f"cannot {word} {tname(t)}: arithmetic works on numbers")
        return node, ("number" if ta == "number" and tb == "number" else None)

    def agree(self, left, ta, cop):
        """is / are, contains / contain must match a list subject (checked for a plain variable subject)."""
        if self.simply or cop is None or left[0] != "var":
            return
        name = left[1]
        if ta is None or ta == "nothing":
            return
        if cop == "are" and not is_list(ta):
            self.soft(f"'{name}' is {tname(ta)}, not a list: say 'is', not 'are'")
        elif cop == "is" and is_list(ta):
            self.soft(f"'{name}' is a list (several things): say 'are', not 'is'")
        elif cop == "contain" and not is_list(ta):
            self.soft(f"'{name}' is {tname(ta)}, not a list: say 'contains', not 'contain'")
        # 'contains' is accepted for lists too: 'x must contain y' is rewritten to it and cannot know which fits

    def compare(self, e, sc):
        op = e[1]
        a, ta = self.expr(e[2], sc)
        b, tb = self.expr(e[3], sc)
        cop = e[4] if len(e) > 4 else None
        self.agree(e[2], ta, cop)
        if op in ("lt", "gt", "le", "ge"):
            for t in (ta, tb):
                if t not in (None, "number", "text"):
                    self.terr(f"cannot order {tname(t)} (only numbers or text can be bigger or smaller)")
            if ta and tb and ta != tb:
                self.terr(f"cannot compare {tname(ta)} with {tname(tb)}")
        elif op in ("eq", "ne"):
            if ta not in (None, "nothing") and tb not in (None, "nothing") and not compat(ta, tb) and not compat(tb, ta):
                self.terr(f"comparing {tname(ta)} with {tname(tb)}: they can never be equal")
        elif op in ("starts", "ends"):
            for t in (ta, tb):
                if t not in (None, "text"):
                    self.terr(f"'{op} with' works on text, not {tname(t)}")
        return ["cmp", op, a, b], "flag"

    def index(self, e, sc):
        cont, tc = self.expr(e[1], sc)
        key, tk = self.expr(e[2], sc)
        noun = e[3] if len(e) > 3 else None
        if noun and not self.simply and e[1][0] == "var" and is_plural(e[1][1]) and noun not in ITEM_NOUNS \
                and noun != singular(e[1][1]):
            self.soft(f"'{noun}' does not fit '{e[1][1]}': say 'the ... {singular(e[1][1])} of the {e[1][1]}' (or 'item')")
        node = ["index", cont, key]
        if tc is None:
            return node, None
        if tc == "table":
            return node, None
        if is_list(tc) or is_tuple(tc) or tc == "text":
            if tk not in (None, "number"):
                self.terr(f"an item number must be a number, not {tname(tk)}")
            if is_tuple(tc) and key[0] == "num" and not 0 <= key[1] < tc[1]:
                self.terr(f"{tname(tc)} has only {tc[1]} parts (numbered 0 to {tc[1] - 1})")
            return node, ("text" if tc == "text" else tc[1] if is_list(tc) else None)
        self.terr(f"{tname(tc)} has no items to pick from")
        return node, None

    def call(self, e, sc):
        f, args, kw = e[1], e[2], e[3]
        res = [self.expr(x, sc) for x in args]
        kws = [(n, self.expr(v, sc)[0]) for n, v in kw]
        argn = [r[0] for r in res]
        if f[0] == "var" and f[1] in self.funcs and sc.lookup(f[1]) is None:
            info = self.funcs[f[1]]
            if info["kind"] == "define" and len(argn) == len(info["params"]):
                for (pn, pt), (_, at) in zip(info["params"], res):
                    if not compat(pt, at):
                        self.terr(f"'{f[1]}' wants {pn} to be {tname(pt)}, but this is {tname(at)}")
            return ["call", ["var", f[1]], argn, kws], None
        fn, _ = self.expr(f, sc)
        return ["call", fn, argn, kws], None

    def function(self, e, sc):
        op = e[1]
        res = [self.expr(x, sc) for x in e[2]]
        args = [r[0] for r in res]
        types = [r[1] for r in res]
        node = ["fn", op, args] + list(e[3:])
        t0 = types[0] if types else None
        if op in NUM_FN or op == "rem":
            for t in types:
                if t not in (None, "number"):
                    self.terr(f"this needs a number, not {tname(t)}")
            return node, "number"
        if op in ("upper", "lower", "trim"):
            if t0 not in (None, "text"):
                self.terr(f"this needs text, not {tname(t0)}")
            return node, "text"
        if op == "len" and t0 not in (None, "text", "table") and not is_list(t0) and not is_tuple(t0):
            self.terr(f"{tname(t0)} has no length")
        if op in ("sorted", "reversed", "slice"):
            return node, t0 if (is_list(t0) or t0 == "text") else None
        if op in ("first", "last", "min", "max"):
            if is_list(t0):
                return node, t0[1] if t0[1] != "mixed" else None
            return node, ("text" if (t0 == "text" and op in ("first", "last")) else None)
        if op == "sum" and t0 is not None and not is_list(t0) and not is_tuple(t0):
            self.terr(f"cannot add up {tname(t0)}")
        return node, FN_RESULT.get(op)

    # ------------------------------------------------------------------ places (things that can be written)
    def coerce(self, vnode, vt, want):
        """a list written with commas becomes a pair/triple/quad when the variable is one"""
        if is_tuple(want) and vnode[0] in ("list", "tuple") and vt != want:
            n = want[1]
            if len(vnode[1]) != n:
                self.terr(f"{tname(want)} needs exactly {n} values, but {len(vnode[1])} are given")
            else:
                return ["tuple", vnode[1]], want
        return vnode, vt

    def assign(self, place, vnode, vt, sc):
        """-> (place node, value node)"""
        k = place[0]
        if k == "decl":                          # old rules ('Simply,'): a bare name makes the variable when it is new
            v = self.simply_var(place[1], sc)
            return ["var", v.py], vnode
        if k == "var":
            v = sc.lookup(place[1])
            if v is None:
                if self.simply:
                    v = self.simply_var(place[1], sc)
                else:
                    raise self.undefined(place[1], sc)
            if v.scope.kind == "builtin" and v.py.startswith("__"):
                if self.simply:                            # Simply, c = 5 makes a variable called c
                    home = sc.home()
                    v = Var(place[1], self.fresh(place[1]), None, self.line, home)
                    home.names[place[1]] = v
                else:
                    raise self.err(f"'{v.name}' is a built-in constant and cannot be changed (make your own variable of that "
                                   f"name with 'Let a number be called {v.name}' if you need one)")
            vnode, vt = self.coerce(vnode, vt, v.type)
            self.check_assign(v.type, vt, f"'{v.name}'")
            self.note_write(v)
            return ["var", v.py], vnode
        if k == "index":
            cont, tc = self.expr(place[1], sc)
            key, tk = self.expr(place[2], sc)
            self.check_mutable(tc, "change an item of")
            if tc == "text":
                self.terr("text cannot be changed letter by letter (build new text instead)")
            elif is_list(tc):
                self.check_assign(tc[1] if tc[1] != "mixed" else None, vt, "an item of this list")
            return ["index", cont, key], vnode
        if k == "attr":
            base, tb = self.expr(place[1], sc)
            return ["attr", base, place[2]], vnode
        raise self.err("this cannot be changed")

    def check_mutable(self, t, what):
        if is_tuple(t):
            self.terr(f"{tname(t)} is a fixed group and cannot {what} it (use a list if it must change)")
        elif t in SCALARS:
            self.terr(f"cannot {what} {tname(t)}")

    # ------------------------------------------------------------------ statements
    def block(self, stmts, sc):
        out = []
        for s in stmts:
            out += self.stmt(s, sc)
        return out

    def sub(self, stmts, sc, kind="block"):
        child = Scope(kind, sc)
        try:
            return self.block(stmts, child), child
        finally:
            self.close(child)

    def stmt(self, s, sc):
        self.line = s[1] if len(s) > 1 and isinstance(s[1], int) else self.line
        m = getattr(self, "r_" + s[0], None)
        if m is None:
            return [s]
        out = m(s, sc)
        return out if isinstance(out, list) and (not out or isinstance(out[0], list)) else [out]

    @staticmethod
    def default_value(typ):
        if typ in (None, "nothing"):
            return ["none"]
        if typ == "number":
            return ["num", 0.0]
        if typ == "text":
            return ["str", [""]]
        if typ == "flag":
            return ["bool", False]
        if typ == "table":
            return ["table", []]
        if is_list(typ):
            return ["list", []]
        return ["tuple", [["num", 0.0]] * typ[1]]

    def r_let(self, s, sc):
        """Let a number be called total  ->  the variable exists (with its default value) from here to the end of the block
        make total a global number    ->  the variable exists for the whole program (it was made when the file was scanned,
                                          and is given its default value once, when the program starts)"""
        name, ty, slots = s[2], s[3], s[4]
        typ = None if ty == "value" else ty
        if len(s) > 5 and s[5] == "global":
            return []
        shared = len(s) > 5 and s[5] == "shared"
        n = None
        if slots is not None:
            n, tn = self.expr(slots, sc)
            if tn not in (None, "number"):
                self.terr(f"the number of slots must be a number, not {tname(tn)}")
        v = self.declare(sc, name, typ)
        if n is not None:
            return [["alloc", s[1], v.py, n] + (["shared"] if shared else [])]
        return [["set", s[1], ["var", v.py], self.default_value(typ)]]

    def make_globals(self, stmts):
        """`make NAME a global TYPE` anywhere in a file (even inside a function) makes NAME a variable of the whole program.
        It is made before anything else is read, so code written above the `make` line can already use it."""
        for s in stmts:
            if s[0] == "let" and len(s) > 5 and s[5] == "global":
                self.line = s[1]
                typ = None if s[3] == "value" else s[3]
                v = self.declare(self.program, s[2], typ)
                if s[4] is not None:
                    n, tn = self.expr(s[4], self.program)
                    if tn not in (None, "number"):
                        self.terr(f"the number of slots must be a number, not {tname(tn)}")
                    self.init.append(["alloc", s[1], v.py, n])
                else:
                    self.init.append(["set", s[1], ["var", v.py], self.default_value(typ)])
            for blk in zp.nested_blocks(s):
                self.make_globals(blk)

    def r_set(self, s, sc):
        val, vt = self.expr(s[3], sc)
        tgt, val = self.assign(s[2], val, vt, sc)
        return [["set", s[1], tgt, val]]

    def r_aug(self, s, sc):
        op = s[2]
        val, vt = self.expr(s[3], sc)
        tgt, ttype = self.target_read(s[4], sc)
        if op == "add" and ttype == "text":
            if vt not in (None, "text"):
                self.terr(f"cannot add {tname(vt)} to text")
        else:
            if is_list(ttype):
                self.terr("a list is not a number: to put something on a list say 'append ... to the list'")
            for t in (ttype, vt):
                if t not in (None, "number"):
                    self.terr(f"{'add' if op == 'add' else 'subtract' if op == 'sub' else 'multiply' if op == 'mul' else 'divide'} "
                              f"works on numbers, but this is {tname(t)}")
        tnode, _ = self.assign(s[4], ["num", 0.0], "number" if ttype in (None, "number") else ttype, sc)
        return [["aug", s[1], op, val, tnode]]

    def target_read(self, place, sc):
        """type of an existing place (for + - * / on it)"""
        if place[0] == "decl":
            v = self.simply_var(place[1], sc) if place[3] == "simply" else None
            if v is None:
                raise self.err(f"'{place[1]}' is new, so there is nothing to add to yet (give it a value first)")
            return None, v.type
        node, t = self.expr(place, sc)
        return node, t

    def r_calc(self, s, sc):
        val, vt = self.expr(s[2], sc)
        tgt, val = self.assign(s[3], val, vt, sc)
        return [["calc", s[1], val, tgt]]

    def r_alloc(self, s, sc):
        n, tn = self.expr(s[3], sc)
        if tn not in (None, "number"):
            self.terr("the number of slots must be a number")
        v = self.simply_var(s[2][1], sc)
        return [["alloc", s[1], v.py, n]]

    def r_store(self, s, sc):
        cont, tc = self.expr(s[2], sc)
        key, tk = self.expr(s[3], sc)
        val, vt = self.expr(s[4], sc)
        self.check_mutable(tc, "change an item of")
        if is_list(tc):
            self.check_assign(tc[1] if tc[1] != "mixed" else None, vt, "an item of this list")
        return [["store", s[1], cont, key, val] + list(s[5:])]

    def r_load(self, s, sc):
        cont, tc = self.expr(s[2], sc)
        key, tk = self.expr(s[3], sc)
        et = tc[1] if is_list(tc) and tc[1] != "mixed" else ("text" if tc == "text" else None)
        tgt, _ = self.assign(s[4], ["num", 0.0], et, sc)
        return [["load", s[1], cont, key, tgt]]

    def r_read(self, s, sc):
        et = "text" if s[2] == "line" else "number"
        tgt, _ = self.assign(s[3], ["num", 0.0], et, sc)
        return [["read", s[1], s[2], tgt]]

    def r_readfile(self, s, sc):
        path, _ = self.expr(s[2], sc)
        tgt, _ = self.assign(s[3], ["num", 0.0], "text", sc)
        return [["readfile", s[1], path, tgt]]

    def r_writefile(self, s, sc):
        return [["writefile", s[1], s[2], self.expr(s[3], sc)[0], self.expr(s[4], sc)[0]]]

    def r_print(self, s, sc):
        return [["print", s[1], s[2], [[kind, self.expr(e, sc)[0]] for kind, e in s[3]]]]

    def r_if(self, s, sc):
        cond, _ = self.expr(s[2], sc)
        body, _ = self.sub(s[3], sc)
        orelse = None
        if s[4] is not None:
            orelse, _ = self.sub(s[4], sc)
        return [["if", s[1], cond, body, orelse] + list(s[5:])]

    def r_while(self, s, sc):
        cond, _ = self.expr(s[2], sc)
        body, _ = self.sub(s[3], sc)
        return [["while", s[1], cond, body]]

    def r_repeat(self, s, sc):
        n = None
        if s[2] is not None:
            n, tn = self.expr(s[2], sc)
            if tn not in (None, "number"):
                self.terr(f"'repeat' needs a number of times, not {tname(tn)}")
        body, _ = self.sub(s[3], sc)
        return [["repeat", s[1], n, body]]

    def loop_body(self, decl, typ, stmts, sc):
        child = Scope("block", sc)
        name = decl[1]
        if name in self.funcs:
            raise self.err(f"'{name}' is already the name of a function")
        v = Var(name, self.fresh(name), typ, self.line, child)
        child.names[name] = v
        try:
            return v.py, self.block(stmts, child)
        finally:
            self.close(child)

    def r_foreach(self, s, sc):
        it, ti = self.expr(s[3], sc)
        if is_list(ti):
            et = ti[1] if ti[1] != "mixed" else None
        elif ti == "text":
            et = "text"
        else:
            et = None
            if ti in ("number", "flag"):
                self.terr(f"cannot go through each item of {tname(ti)}")
        name, body = self.loop_body(s[2], et, s[4], sc)
        return [["foreach", s[1], name, it, body]]

    def r_for(self, s, sc):
        a, ta = self.expr(s[3], sc)
        z, tz = self.expr(s[4], sc)
        st = self.expr(s[5], sc)[0] if s[5] else None
        for t in (ta, tz):
            if t not in (None, "number"):
                self.terr(f"'for ... from ... to ...' counts numbers, not {tname(t)}")
        name, body = self.loop_body(s[2], "number", s[6], sc)
        return [["for", s[1], name, a, z, st, body]]

    def r_return(self, s, sc):
        return [["return", s[1], self.expr(s[2], sc)[0] if s[2] else None]]

    def r_workers(self, s, sc):
        n, tn = self.expr(s[2], sc)
        if tn not in (None, "number"):
            self.terr("the number of workers must be a number")
        tgt, _ = self.assign(s[3], ["num", 0.0], "number", sc)
        return [["workers", s[1], n, tgt]]

    def r_fsize(self, s, sc):
        tgt, _ = self.assign(s[2], ["num", 0.0], "number", sc)
        return [["fsize", s[1], tgt]]

    def r_seekf(self, s, sc):
        pos, _ = self.expr(s[2], sc)
        return [["seekf", s[1], pos]]

    def r_syscall(self, s, sc):
        num, _ = self.expr(s[2], sc)
        args = [self.expr(a, sc)[0] for a in s[3]]
        tgt = None
        if s[4] is not None:
            tgt, _ = self.assign(s[4], ["num", 0.0], "number", sc)
        return [["syscall", s[1], num, args, tgt]]

    def r_clock(self, s, sc):
        tgt, _ = self.assign(s[2], ["num", 0.0], "number", sc)
        return [["clock", s[1], tgt] + list(s[3:])]

    def r_openf(self, s, sc):
        path, _ = self.expr(s[2], sc)
        return [["openf", s[1], path]]

    def r_openarr(self, s, sc):
        arr, _ = self.expr(s[2], sc)
        return [["openarr", s[1], arr]]

    def r_closef(self, s, sc):
        return [["closef", s[1]]]

    def r_waitw(self, s, sc):
        return [["waitw", s[1]]]

    def r_finish(self, s, sc):
        e = None
        if s[2]:
            e, te = self.expr(s[2], sc)
            if te not in (None, "number"):
                self.terr(f"'finish with' needs a number, not {tname(te)}")
        return [["finish", s[1], e]]

    def r_fail(self, s, sc):
        return [["fail", s[1], self.expr(s[2], sc)[0]]]

    def r_warn(self, s, sc):
        return [["warn", s[1], self.expr(s[2], sc)[0]]]

    def r_check(self, s, sc):
        return [["check", s[1], self.expr(s[2], sc)[0], s[3]]]

    def r_exprstmt(self, s, sc):
        return [["exprstmt", s[1], self.expr(s[2], sc)[0]]]

    def r_callstore(self, s, sc):
        val, vt = self.expr(s[2], sc)
        tgt, _ = self.assign(s[3], val, vt, sc)
        return [["callstore", s[1], val, tgt]]

    def r_runwith(self, s, sc):
        return [["runwith", s[1], s[2], self.expr(s[3], sc)[0]]]

    def r_convert(self, s, sc):
        val, tv = self.expr(s[3], sc)
        if tv not in (None, "number", "text"):
            self.terr(f"cannot convert {tname(tv)} this way")
        tgt, _ = self.assign(s[4], ["num", 0.0], "number" if s[2] == "character" else "text", sc)
        return [["convert", s[1], s[2], val, tgt]]

    def r_use(self, s, sc):
        name = s[3]
        old = sc.lookup(name, sc)
        if old is not None and old.type == "module" and old.extra == s[2]:
            return []
        v = self.declare(sc, name, "module")
        v.extra = s[2]
        return [["use", s[1], s[2], v.py]]

    def r_usefrom(self, s, sc):
        names = []
        for nm in s[3]:
            v = self.declare(sc, nm, None)
            names.append(v.py)
        return [["usefrom", s[1], s[2], names, list(s[3])]]

    def r_global(self, s, sc):
        fn = self.func_stack[-1] if self.func_stack else None
        names = []
        for nm in s[2]:
            if fn is not None:
                fn["globals_decl"].add(nm)
            v = self.program.lookup(nm, self.program)
            if v is None:
                v = Var(nm, self.fresh(nm), None, self.line, self.program)
                self.program.names[nm] = v
            if fn is not None:
                fn["globals"].add(v.py)
            names.append(v.py)
        return [["global", s[1], names]]

    def r_extern(self, s, sc):
        self.externs.add(s[2])
        return [s]

    def list_target(self, e, sc, what):
        node, t = self.expr(e, sc)
        if t not in (None,) and not is_list(t) and t != "table":
            self.terr(f"cannot {what} {tname(t)}: it is not a list")
        self.check_mutable(t, what)
        return node, t

    def r_append(self, s, sc):
        val, vt = self.expr(s[2], sc)
        tgt, tt = self.list_target(s[3], sc, "add to")
        if is_list(tt):
            self.check_assign(tt[1] if tt[1] != "mixed" else None, vt, "this list")
        return [["append", s[1], val, tgt]]

    def r_insert(self, s, sc):
        val, vt = self.expr(s[2], sc)
        tgt, tt = self.list_target(s[3], sc, "insert into")
        if is_list(tt):
            self.check_assign(tt[1] if tt[1] != "mixed" else None, vt, "this list")
        return [["insert", s[1], val, tgt, self.expr(s[4], sc)[0]]]

    def r_remove(self, s, sc):
        val, _ = self.expr(s[2], sc)
        return [["remove", s[1], val, self.list_target(s[3], sc, "remove from")[0]]]

    def r_removeat(self, s, sc):
        idx, _ = self.expr(s[2], sc)
        return [["removeat", s[1], idx, self.list_target(s[3], sc, "remove from")[0]]]

    def r_sort(self, s, sc):
        return [["sort", s[1], self.list_target(s[2], sc, "sort")[0], s[3]]]

    def r_reverse(self, s, sc):
        return [["reverse", s[1], self.list_target(s[2], sc, "reverse")[0]]]

    def r_clear(self, s, sc):
        return [["clear", s[1], self.list_target(s[2], sc, "clear")[0]]]

    def r_wait(self, s, sc):
        return [["wait", s[1], self.expr(s[2], sc)[0]]]

    def r_delete(self, s, sc):
        return [["delete", s[1], self.expr(s[2], sc)[0]]]

    def r_try(self, s, sc):
        body, _ = self.sub(s[2], sc)
        handler = None
        if s[3] is not None:
            name, hbody = s[3]
            child = Scope("block", sc)
            v = Var(name, self.fresh(name), "text", self.line, child)
            child.names[name] = v
            try:
                handler = (v.py, self.block(hbody, child))
            finally:
                self.close(child)
        always = self.sub(s[5], sc)[0] if s[5] is not None else None
        return [["try", s[1], body, handler, s[4], always]]

    def param_type(self, d):
        ty = d[2]
        if ty == "value":
            return None
        if ty is None and not self.simply and d[3] != "simply" and is_plural(d[1]):
            return ("list", None)
        return ty

    def r_routine(self, s, sc):
        child = Scope("routine", sc)
        self.func_stack.append({"kind": "routine", "globals": set(), "globals_decl": set()})
        try:
            body = self.block(s[3], child)
        finally:
            self.func_stack.pop()
            self.close(child)
        return [["routine", s[1], s[2], body]]

    def r_define(self, s, sc):
        name = s[2]
        if sc.lookup(name) is not None:
            raise self.err(f"'{name}' is already a variable name; a function needs a name of its own")
        child = Scope("function", sc)
        params = []
        for d in s[3]:
            if d[1] in self.funcs:
                raise self.err(f"'{d[1]}' is already the name of a function")
            if d[1] in child.names:
                raise self.err(f"'{d[1]}' is used twice in the list of values this function takes")
            v = Var(d[1], self.fresh(d[1]), self.param_type(d), self.line, child)
            child.names[d[1]] = v
            params.append(v.py)
        fn = {"kind": "define", "globals": set(), "globals_decl": set()}
        self.func_stack.append(fn)
        try:
            body = self.block(s[4], child)
        finally:
            self.func_stack.pop()
            self.close(child)
        if fn["globals"]:
            body = [["global", s[1], sorted(fn["globals"])]] + body
        return [["define", s[1], name, params, body]]

    def r_action(self, s, sc):
        body, _ = self.sub(s[2], sc)
        return [["action", s[1], body]]

    def r_scope(self, s, sc):
        return [["scope", s[1], self.block(s[2], sc)]]

    def r_simply(self, s, sc):
        saved, self.simply = self.simply, True
        try:
            return self.block(s[2], sc)
        finally:
            self.simply = saved

    # ------------------------------------------------------------------ whole files
    def prescan(self, stmts):
        for s in stmts:
            if s[0] in ("define", "routine"):
                params = []
                if s[0] == "define":
                    saved = self.simply
                    for d in s[3]:
                        self.simply = d[3] == "simply"
                        params.append((d[1], self.param_type(d)))
                    self.simply = saved
                self.funcs[s[2]] = {"kind": s[0], "params": params}
                self.used.add(s[2])
            elif s[0] in ("simply", "scope"):
                self.prescan(s[2])

    def enter(self, file, stmts):
        saved = (self.file, self.line)
        self.file = file
        self.prescan(stmts)
        self.make_globals(stmts)
        return saved

    def take_init(self):
        out, self.init = self.init, []
        return out

    def leave(self, saved):
        self.file, self.line = saved

    def top(self, s):
        return self.stmt(s, self.program)
