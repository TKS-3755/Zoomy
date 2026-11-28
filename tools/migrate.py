#!/usr/bin/env python3
"""
Convert an old-style Zoomy program (bare names: `set x to 5`) to the English grammar, where a variable is made by its own
statement first (`Let a number be called x`) and then used (`set x to 5`).

    python3 tools/migrate.py old.zmy                 (prints the converted program)
    python3 tools/migrate.py old.zmy -o new.zmy
    python3 tools/migrate.py old.zmy --inplace
    python3 tools/migrate.py old.zmy --numbers       (shared names nothing else sets are numbers, not "any value")
    python3 tools/migrate.py new.zmy --wording-only  (only the 6.2 wording below, for a program that already uses the new grammar)

What it does
  * the first assignment of a name gets a line before it that makes the variable (`Let a number be called total`);
  * a name that must outlive the block it was first set in is made before that block;
  * names shared between routines/functions and the main program become declarations at the top of the file
    (the old language shared them implicitly);  `global` lines are dropped (not needed any more);
  * names that are articles (a, an, the) get a trailing underscore;
  * `allocate array a with 5 slots` becomes `Create an array named a with 5 slots`.
  * the wording of Zoomy 6.2 (the old phrasing keeps compiling; this makes a program read the way the manual does):
      calculate absolute value of x store in y      ->  calculate the absolute value of x and store the result in y
      count set bits of x / trailing zeros of x     ->  count the set bits of x / count the trailing zeros of x
      isolate lowest bit of x, reverse bytes of x   ->  isolate the lowest bit of x, reverse the bytes of x
      extract bits of x using mask m                ->  extract the bits of x using the mask m   (also deposit)
      read byte c / read char c                     ->  read the next byte into c / read the next character into c
      convert character 'a' to a number ...         ->  convert the character 'a' to a number and store the result in ...
      call f with 1 and 2 store in r                ->  call f with 1 and 2 and store the result in r
      set y to absolute value of x                  ->  set y to the absolute value of x   (also square root, natural log)
It prints notes on stderr for anything it could not decide. Always read the result once: it is a first draft, not magic.
If you would rather keep a program as it is, indent it under a line `Simply,` instead.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import zoomy_py as zp          # noqa: E402
import zoomy_grammar as gram  # noqa: E402

BUILTIN = {"pi", "input_ok", "problem", "arguments"}
SCOPED = {"if", "else", "otherwise", "while", "repeat", "for", "try", "always", "routine", "define", "action", "unless", "until"}
RENAME_WORDS = set(zp.ARTICLES)


class Line:
    def __init__(self, idx, raw):
        self.idx, self.raw = idx, raw
        code = zp.strip_comment(raw)
        self.trail = raw[len(code):] if code.strip() else ""
        self.text = code.strip()
        exp = code.expandtabs(4)
        self.indent = len(exp) - len(exp.lstrip()) if self.text else 0
        self.header = bool(self.text) and (self.text.endswith(":") or re.fullmatch(r"(?i)(structurally|simply),", self.text) is not None)
        self.body = self.text[:-1].strip() if self.header and self.text.endswith(":") else self.text.rstrip(",")
        w = re.match(r"[A-Za-z_]\w*", self.body or "")
        self.word = w.group(0) if w else None
        self.unit = None


def lex_with_pos(text):
    pos = []
    toks = zp.lex(text, lambda m: ValueError(m), pos)
    return toks, pos


def depth0(toks, lo, hi):
    """indexes of tokens at bracket depth 0 in [lo, hi)"""
    d, out = 0, []
    for k in range(lo, hi):
        kind, v, _ = toks[k]
        if kind == "op" and v in "([":
            d += 1
        elif kind == "op" and v in ")]":
            d -= 1
        elif d == 0:
            out.append(k)
    return out


def find_word(toks, lo, hi, word, last=False):
    hits = [k for k in depth0(toks, lo, hi) if toks[k][0] == "word" and toks[k][1] == word]
    if not hits:
        return None
    return hits[-1] if last else hits[0]


def clauses(toks):
    """split a statement into pipeline clauses (token ranges), like Front.arith"""
    n = len(toks) - 1
    cuts, d = [0], 0
    for k, (kind, v, _) in enumerate(toks[:n]):
        if kind == "op" and v in "([":
            d += 1
        elif kind == "op" and v in ")]":
            d -= 1
        elif d == 0 and k > 0 and kind == "word" and v == "and" and toks[k + 1][0] == "word" and toks[k + 1][1] in zp.ARITH_VERBS:
            cuts.append(k)
    cuts.append(n)
    return [(cuts[j] + (1 if j else 0), cuts[j + 1]) for j in range(len(cuts) - 1)]


def place_groups(toks, lo, hi):
    """split `x and y and z` into [(lo, hi), ...] token ranges"""
    out, start = [], lo
    for k in depth0(toks, lo, hi):
        if toks[k][0] == "word" and toks[k][1] == "and":
            out.append((start, k))
            start = k + 1
    out.append((start, hi))
    return out


def targets_of(toks, lo, hi):
    """-> list of (token index, role) where role is 'decl' (set-like, may create) or 'ref' (must exist) for plain-name targets"""
    verb = toks[lo][1]
    out = []

    def single(a, b, role):
        if b - a == 1 and toks[a][0] == "word":
            out.append((a, role))

    if verb == "set":
        k = find_word(toks, lo + 1, hi, "to")
        if k:
            single(lo + 1, k, "decl")
    elif verb == "add" or verb == "subtract":
        k = find_word(toks, lo + 1, hi, "to" if verb == "add" else "from", last=True)
        if k:
            for a, b in place_groups(toks, k + 1, hi):
                single(a, b, "ref")
    elif verb in ("multiply", "divide"):
        k = find_word(toks, lo + 1, hi, "by")
        if k:
            for a, b in place_groups(toks, lo + 1, k):
                single(a, b, "ref")
    elif verb in ("calculate", "call", "convert"):
        ks = [k for k in depth0(toks, lo + 1, hi - 1) if toks[k][0] == "word" and toks[k][1] == "store" and toks[k + 1][1] == "in"]
        if ks:
            single(ks[-1] + 2, hi, "decl")
    elif verb == "load":
        k = find_word(toks, lo + 1, hi, "into", last=True)
        if k:
            single(k + 1, hi, "decl")
    elif verb == "read":
        if hi - lo >= 3 and toks[lo + 1][1] == "file":
            k = find_word(toks, lo + 1, hi, "into", last=True)
            if k:
                single(k + 1, hi, "decl")
        elif hi - lo >= 3 and toks[lo + 1][1] == "line" and toks[lo + 2][1] == "into":
            single(lo + 3, hi, "decl")
        elif hi - lo >= 3 and toks[lo + 1][1] == "char" and toks[lo + 2][0] == "word":
            single(lo + 2, hi, "decl")
        else:
            single(lo + 1, hi, "decl")
    return out


class Migrator:
    def __init__(self, text, filename, known=(), assume_numbers=False):
        self.filename = filename
        self.notes = []
        self.lines = [Line(i, r) for i, r in enumerate(text.splitlines())]
        self.known = set(known)
        self.assume_numbers = assume_numbers
        self.array_slots = 1000
        self.arrays = set()
        for ln in self.lines:
            for m in re.finditer(r"\bstore\b.*?\bin\s+(\w+)\s+at\b|\bload\s+from\s+(\w+)\s+at\b", ln.body):
                self.arrays.add(m.group(1) or m.group(2))
        self.funcs = set()
        self.imports = set()
        self.renames = {}
        self.scan_headers()
        self.find_units()
        self.collect_events()

    # ------------------------------------------------------------------ analysis
    def note(self, line, msg):
        self.notes.append(f"{self.filename}:{line.idx + 1}: {msg}")

    def scan_headers(self):
        d = os.path.dirname(os.path.abspath(self.filename))
        for ln in self.lines:
            if not ln.text:
                continue
            m = re.match(r"(?:define|routine)\s+([A-Za-z_]\w*)", ln.body)
            if m and ln.indent == 0:
                self.funcs.add(m.group(1))
            m = re.match(r"use\s+python's\s+([\w.]+)(?:\s+as\s+(\w+))?$", ln.body)
            if m:
                self.imports.add(m.group(2) or m.group(1).split(".")[0])
            m = re.match(r"use\s+(.+?)\s+from\s+python's", ln.body)
            if m:
                self.imports.update(re.split(r"\s*,\s*|\s+and\s+", m.group(1)))
            m = re.match(r"include\s+(.+)$", ln.body)
            if m:
                self.known |= self.lib_names(m.group(1).strip(), d)

    @staticmethod
    def lib_names(spec, d):
        m = re.fullmatch(r"([A-Za-z_]\w*)'s\s+([A-Za-z_]\w*)", spec)
        rel = f"{m.group(1)}/{m.group(2)}" if m else spec.strip('"').replace(".zmy", "")
        found = zp.resolve_lib([d, ROOT], rel)
        names = set()
        if not found:
            return names
        with open(found, encoding="utf-8") as f:
            text = f.read()
        for ln in text.splitlines():
            if ln[:1] in " \t#(" or not ln.strip():
                continue
            m = re.match(r"include\s+(.+)$", ln)
            if m:
                names |= Migrator.lib_names(m.group(1).strip(), os.path.dirname(found))
                continue
            for pat in (r"(?i:let|create|define)\s+an?\s+\w+(?:\s+of\s+\w+)?\s+(?:be\s+called|named|for)\s+(\w+)",):
                m = re.match(pat, ln)
                if m:
                    names.add(m.group(1))
        return names

    def find_units(self):
        """unit of a line: the top-level routine/define it is inside, else 'main'"""
        unit = "main"
        for ln in self.lines:
            if not ln.text:
                continue
            if ln.indent == 0:
                if ln.header and ln.word in ("routine", "define"):
                    unit = f"fn{ln.idx}"
                elif ln.word in ("routine", "define") or ln.word != "action":
                    unit = "main"
                else:
                    unit = "main"
            ln.unit = unit
        # block extents: header line -> last line of its body
        self.end = {}
        stmts = [ln for ln in self.lines if ln.text]
        for k, ln in enumerate(stmts):
            if ln.header:
                last = ln.idx
                for nxt in stmts[k + 1:]:
                    if nxt.indent <= ln.indent:
                        break
                    last = nxt.idx
                self.end[ln.idx] = last

    def parse(self, ln):
        feats = set()
        front = zp.Front(self.filename, feats)
        front.simply = True
        body = ln.body
        m = re.match(r"(?:else|otherwise)\s+(if\s+.*)$", body)
        if m:
            body = m.group(1)
        elif ln.word in ("else", "otherwise") or re.match(r"if it fail", ln.body) or ln.word == "always":
            return None
        blk = zp.Blk(ln.idx + 1, body, ln.header)
        try:
            front.loop_depth = 1
            front.func_depth = 1
            return self.norm(front.convert_one(blk, []))
        except zp.ZoomyError:
            return None

    def norm(self, st):
        """turn the front end's 'decl' nodes back into plain variables / names"""
        if st is None:
            return None
        if st and isinstance(st[0], list):
            return [self.norm(s) for s in st]
        out = []
        for x in st:
            if isinstance(x, list) and x and x[0] == "decl":
                out.append(x[1] if st[0] in ("foreach", "for", "alloc") else ["var", x[1]])
            elif st[0] == "define" and isinstance(x, list) and x and isinstance(x[0], list) and x[0][0] == "decl":
                out.append([d[1] for d in x])
            else:
                out.append(x)
        return out

    def events_of(self, st):
        """[(kind, name)] in evaluation order for one parsed statement (or list of statements)"""
        if st is None:
            return []
        if st and isinstance(st[0], list):
            out = []
            for s in st:
                out += self.events_of(s)
            return out
        k = st[0]
        reads, writes = [], []

        def names(e):
            hit = []
            zp.walk(e, lambda x: hit.append(x[1]) if x[0] == "var" else None)
            return hit

        def place_reads(p):
            if p[0] == "var":
                return []
            return names(p)
        ex = zp.stmt_exprs(st)
        if k == "set":
            reads = names(st[3]) + place_reads(st[2])
            writes = zp.assigned_names(st)
        elif k == "aug":
            reads = names(st[3]) + names(st[4])
            writes = zp.assigned_names(st)
        elif k in ("calc", "load", "convert", "callstore", "readfile"):
            tgt = {"calc": 3, "load": 4, "convert": 4, "callstore": 3, "readfile": 3}[k]
            for i, e in enumerate(st[2:], 2):
                if i == tgt:
                    reads += place_reads(e)
                elif isinstance(e, list) and e and isinstance(e[0], str) and i >= 2:
                    reads += names(e)
            writes = zp.assigned_names(st)
        elif k == "read":
            reads = place_reads(st[3])
            writes = zp.assigned_names(st)
        elif k == "foreach":
            reads = names(st[3])
            writes = [st[2]]
        elif k == "for":
            reads = names(st[3]) + names(st[4]) + (names(st[5]) if st[5] else [])
            writes = [st[2]]
        elif k == "define":
            writes = list(st[3])
        elif k == "alloc":
            writes = [st[2]]
            reads = names(st[3])
        elif k in ("use", "usefrom"):
            writes = zp.assigned_names(st)
        elif k in ("routine", "action", "scope", "try", "pass", "global", "include", "extern"):
            pass
        else:
            for e in ex:
                reads += names(e)
        skip = self.funcs | BUILTIN
        return [("r", n) for n in reads if n not in skip] + [("w", n) for n in writes if n not in skip and not (k == "alloc")]

    def collect_events(self):
        self.ev = {}               # unit -> [(kind, name, line index)]
        self.name_lines = {}       # name -> [line idx]
        self.parsed = {}
        self.written_rhs = {}      # name -> [rhs text]
        for ln in self.lines:
            if not ln.text:
                continue
            m = re.match(r"if it fail(?:s|ed)?(?:\s+as\s+(\w+))?$", ln.body)
            if m:
                evs = [("w", m.group(1) or "problem")]
                st = None
            else:
                st = self.parse(ln)
                evs = self.events_of(st)
            if ln.word == "define" and ln.header:
                pass
            self.parsed[ln.idx] = st
            for kind, n in evs:
                self.ev.setdefault(ln.unit, []).append((kind, n, ln.idx))
                self.name_lines.setdefault(n, []).append(ln.idx)
            self.record_rhs(ln, st)
        # words of the grammar used as names get renamed
        used = {n for evs in self.ev.values() for _, n, _ in evs}
        decl_words = set()
        for ln in self.lines:
            if ln.text and not ln.header:
                try:
                    toks, _ = lex_with_pos(ln.body)
                    for lo, hi in clauses(toks):
                        if toks[lo][0] == "word":
                            decl_words |= {toks[k][1] for k, role in targets_of(toks, lo, hi)}
                except ValueError:
                    pass
        for n in used:
            if n in zp.ARTICLES or (n in zp.TYPE_NAMES and n in decl_words):
                self.renames[n] = n + "_"
                self.notes.append(f"{self.filename}: the name '{n}' is a grammar word; it is now '{n}_'")

    def record_rhs(self, ln, st):
        if st is None:
            return
        for s in (st if st and isinstance(st[0], list) else [st]):
            if s[0] == "set" and s[2][0] == "var":
                self.written_rhs.setdefault(s[2][1], []).append(("expr", s[3]))
            elif s[0] in ("read", "calc", "aug", "convert"):
                nm = {"read": 3, "calc": 3, "aug": 4, "convert": 4}[s[0]]
                if s[nm][0] == "var":
                    self.written_rhs.setdefault(s[nm][1], []).append(("num" if s[0] != "convert" or s[2] == "character" else "text", None))
            elif s[0] in ("foreach",):
                self.written_rhs.setdefault(s[2], []).append(("any", None))
            elif s[0] == "for":
                self.written_rhs.setdefault(s[2], []).append(("num", None))
            elif s[0] in ("load", "callstore", "readfile"):
                nm = {"load": 4, "callstore": 3, "readfile": 3}[s[0]]
                if s[nm][0] == "var":
                    self.written_rhs.setdefault(s[nm][1], []).append(("text" if s[0] == "readfile" else ("num" if self.assume_numbers else "any"), None))

    # ------------------------------------------------------------------ types for declarations made without a value
    def type_of(self, name, seen=()):
        kinds = set()
        for kind, e in self.written_rhs.get(name, []):
            if kind == "expr":
                kinds.add(self.expr_type(e, seen + (name,)))
            else:
                kinds.add(kind)
        kinds.discard(None)
        if self.assume_numbers:
            kinds.discard("any")
        if len(kinds) == 1:
            return kinds.pop()
        return "num" if self.assume_numbers and not kinds else "any"

    def expr_type(self, e, seen):
        k = e[0]
        if k == "num":
            return "num"
        if k == "str":
            return "text"
        if k == "bool":
            return "flag"
        if k in ("neg", "bin"):
            return "num" if all(self.expr_type(x, seen) == "num" for x in zp.children(e)) else "any"
        if k == "fn":
            return {"len": "num", "sqrt": "num", "abs": "num", "floor": "num", "ceil": "num", "rem": "num", "numfrom": "num",
                    "ask": "text", "upper": "text", "lower": "text", "trim": "text", "text": "text"}.get(e[1], "any")
        if k == "list":
            return "list"
        if k == "table":
            return "table"
        if k == "var":
            if e[1] in seen or e[1] == "pi":
                return "num" if e[1] == "pi" else None
            return self.type_of(e[1], seen)
        return "any"

    TYPE_WORD = {"num": "number", "text": "string", "flag": "flag", "list": "array", "table": "table", "any": "value"}

    def decl_phrase(self, name, kind=None, verb="Let"):
        """the statement that makes `name`"""
        kind = kind or self.type_of(name)
        word = self.TYPE_WORD.get(kind, "value")
        if word == "array":                      # arrays have no Let: Create ... named / Define ... for
            verb = "Create" if verb == "Let" else verb
            prep = {"Create": "named", "Define": "for"}[verb]
        else:
            prep = {"Let": "be called", "Create": "named", "Define": "as"}[verb]
        return f"{verb} {zp.article_for(word)} {word} {prep} {name}"

    # ------------------------------------------------------------------ globals
    def global_names(self):
        free = set()
        for unit, evs in self.ev.items():
            seen, written = set(), set()
            for kind, n, _ in evs:
                if n in self.imports or n in self.known:
                    continue
                if n not in seen:
                    seen.add(n)
                    if kind == "r":
                        free.add(n)
                if kind == "w":
                    written.add(n)
            if unit != "main":
                params = set()
                for ln in self.lines:
                    if ln.unit == unit and ln.word == "define" and ln.header:
                        st = self.parsed.get(ln.idx)
                        params = set(st[3]) if st else set()
                free |= {n for n in seen if n not in written and n not in params}
        main_written = {n for kind, n, _ in self.ev.get("main", []) if kind == "w"}
        # a name only ever used inside one routine and written before it is read is a local; the rest is shared
        glob = {n for n in free if n not in self.imports and n not in self.known and n not in BUILTIN}
        # names written in main and read in routines
        for unit, evs in self.ev.items():
            if unit == "main":
                continue
            params = set()
            for ln in self.lines:
                if ln.unit == unit and ln.word == "define" and ln.header:
                    st = self.parsed.get(ln.idx)
                    params = set(st[3]) if st else set()
            for kind, n, _ in evs:
                if kind == "r" and n not in params and n in main_written and n not in self.imports and n not in self.known:
                    glob.add(n)
        return glob

    # ------------------------------------------------------------------ rewriting
    def run(self):
        glob = self.global_names()
        self.glob = glob
        out_lines = {ln.idx: [] for ln in self.lines}          # extra lines inserted before a line
        scopes = [{"indent": -1, "names": set(glob) | self.known | self.imports, "kind": "program", "header": -1}]
        result = {}
        func_names = self.funcs
        in_unit = None
        for ln in self.lines:
            if not ln.text:
                result[ln.idx] = ln.raw
                continue
            # leave blocks that ended
            while len(scopes) > 1 and scopes[-1]["indent"] >= ln.indent:
                scopes.pop()
            new_text = ln.text
            if ln.word == "global" and ln.body.startswith("global "):
                result[ln.idx] = None
                continue
            handled = False
            m = re.match(r"if it fail(?:s|ed)?(?:\s+as\s+(\w+))?$", ln.body)
            if m:
                scopes.append({"indent": ln.indent, "names": {m.group(1) or "problem"}, "kind": "block", "header": ln.idx})
                new_text = ln.body
                handled = True
            elif ln.word in ("else", "otherwise") and ln.header:
                scopes.append({"indent": ln.indent, "names": set(), "kind": "block", "header": ln.idx})
                new_text = ln.body
                m2 = re.match(r"((?:else|otherwise)\s+)(if\s+.*)$", ln.body)
                if m2:
                    import copy
                    sub = copy.copy(ln)
                    sub.body, sub.word = m2.group(2), "if"
                    new_text = m2.group(1) + self.rewrite_statement(sub, scopes[:-1], out_lines)[0]
                handled = True
            if not handled:
                new_text, pushed = self.rewrite_statement(ln, scopes, out_lines)
                if pushed is not None:
                    scopes.append(pushed)
            if ln.header and ln.text.endswith(":"):
                new_text += ":"
            elif ln.header:
                new_text = ln.text
            result[ln.idx] = " " * ln.indent + new_text + ln.trail
        # assemble
        lines = []
        insert_at = self.top_insert_point()
        decls = sorted(glob - self.imports - self.known - set(BUILTIN))
        for ln in self.lines:
            if ln.idx == insert_at and decls:
                lines.append("(Variables shared by the whole program)")
                for n in decls:
                    if n in self.arrays:
                        lines.append(f"Create an array named {self.rename(n)} with {self.array_slots} slots")
                        self.notes.append(f"{self.filename}: '{n}' is an array: it was given {self.array_slots} slots")
                    else:
                        lines.append(self.decl_phrase(self.rename(n), self.type_of(n)))
                lines.append("")
            for extra in out_lines[ln.idx]:
                lines.append(extra)
            r = result.get(ln.idx)
            if r is not None:
                lines.append(r)
        return "\n".join(lines) + "\n"

    def top_insert_point(self):
        for ln in self.lines:
            if ln.text and ln.indent == 0 and ln.word not in ("include", "use", "extern"):
                return ln.idx
        return len(self.lines)

    def rename(self, n):
        return self.renames.get(n, n)

    def visible(self, scopes, name):
        return any(name in s["names"] for s in scopes)

    def hoist_point(self, ln, scopes, name):
        """outermost enclosing block (inside this unit) that ends before `name` is used again -> header line index, else None"""
        for k, s in enumerate(scopes):
            if s["kind"] != "block":
                continue
            end = self.end.get(s["header"])
            if end is None:
                continue
            if any(l > end and self.lines[l].unit == ln.unit for l in self.name_lines.get(name, [])):
                return k
        return None

    def declare_phrase_with_value(self, name, value_text, value_node):
        plural = gram.is_plural(name)
        is_list = value_node is not None and value_node[0] in ("list",) or (value_text.lstrip().startswith("empty list"))
        if plural and not is_list:
            kind = self.expr_type(value_node, ()) if value_node is not None else "any"
            return self.decl_phrase(name, kind if kind in ("num", "text", "flag", "table") else "any")
        if plural:
            return f"some {name}"
        return f"{zp.article_for(name)} {name}"

    def rewrite_statement(self, ln, scopes, out_lines):
        text = ln.body
        pushed = None
        w = ln.word
        if ln.header and re.fullmatch(r"(?i)structurally|simply", text or ""):
            return text, None
        try:
            toks, pos = lex_with_pos(text)
        except ValueError:
            self.note(ln, "could not read this line; left as it is")
            return ln.text, None
        edits = []

        # --- renamed words
        for k, (kind, v, _) in enumerate(toks):
            if kind == "word" and v in self.renames:
                prev = toks[k - 1][1] if k else None
                nxt = toks[k + 1][1] if k + 1 < len(toks) and toks[k + 1][0] == "word" else None
                if v in ("a", "an", "the", "some") and nxt in zp.TYPE_NAMES:
                    continue
                if nxt in ("of", "from") and v in zp.TYPE_NAMES and not (ln.word == "for" and k in (1, 2)):
                    continue
                if prev in ("is", "convert", "a", "an") and v in zp.TYPE_NAMES:
                    continue
                edits.append((pos[k], pos[k] + len(v), self.renames[v], "rename"))

        def rn(n):
            return self.renames.get(n, n)

        # --- header lines that bind names
        if ln.header and w in ("for",):
            st = self.parsed.get(ln.idx)
            if st:
                nm = st[2]
                pushed = {"indent": ln.indent, "names": {nm}, "kind": "block", "header": ln.idx}
        elif ln.header and w in ("routine", "define", "action"):
            st = self.parsed.get(ln.idx)
            names = set()
            if w == "define" and st:
                names = set(st[3])
            pushed = {"indent": ln.indent, "names": names, "kind": "function" if w != "action" else "block", "header": ln.idx}
            if w == "action":
                pushed["kind"] = "block"
        elif ln.header and w in ("if", "while", "repeat", "try", "always", "unless", "until"):
            pushed = {"indent": ln.indent, "names": set(), "kind": "block", "header": ln.idx}
        # --- array allocation
        if w == "allocate" and len(toks) > 3 and toks[1][1] == "array":
            nm = toks[2][1]
            if self.visible(scopes, nm):
                self.note(ln, f"'{nm}' is already declared (probably by a library): this allocation was dropped")
                return "(array '%s' comes from the library)" % nm, None
            self.declare(scopes, nm)
            edits.append((pos[0], pos[2] + len(nm), f"Create an array named {rn(nm)}"))
            kw = find_word(toks, 3, len(toks) - 1, "with")
            return self.apply(text, edits), pushed
        if w in ("for",):
            return self.apply(text, edits), pushed
        if ln.header:
            return self.apply(text, edits), pushed
        # --- clauses of an ordinary statement
        for lo, hi in clauses(toks):
            verb = toks[lo][1] if toks[lo][0] == "word" else None
            if verb is None:
                continue
            for k, role in targets_of(toks, lo, hi):
                name = toks[k][1]
                if name in BUILTIN or name == "input_ok" or self.visible(scopes, name):
                    continue
                edit_name = rn(name)
                if role == "ref":
                    self.note(ln, f"'{name}' is changed here but was never set; it is made as a number")
                kind = self.type_of(name) if role == "decl" else "num"
                hp = self.hoist_point(ln, scopes[1:], name)
                if hp is not None:                                 # needed after the block it is first set in: make it before the block
                    idx = hp + 1
                    header = scopes[idx]["header"]
                    hl = self.lines[header]
                    out_lines[header].append(" " * hl.indent + self.decl_phrase(edit_name, kind))
                    scopes[idx - 1]["names"].add(name)
                else:
                    out_lines[ln.idx].append(" " * ln.indent + self.decl_phrase(edit_name, kind))
                    scopes[-1]["names"].add(name)
        return self.apply(text, edits), pushed

    def declare(self, scopes, name):
        scopes[-1]["names"].add(name)

    @staticmethod
    def apply(text, edits):
        targets = [e for e in edits if len(e) == 3]
        keep = list(targets)
        for e in edits:                                     # a rename inside a declaration is already part of the declaration
            if len(e) == 4 and not any(t[0] <= e[0] and e[1] <= t[1] for t in targets):
                keep.append(e)
        for e in sorted(keep, key=lambda e: -e[0]):
            text = text[:e[0]] + e[2] + text[e[1]:]
        return text


# ---- the wording of Zoomy 6.2 ------------------------------------------------------------------------------------------
_STR = re.compile(r"(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')")
_OFWORDS = sorted({" ".join(k) if isinstance(k, tuple) else k for k in list(zp.OF_OPS) + list(zp.OF2_OPS)}, key=lambda w: -len(w))
_OFALT = "|".join(re.escape(w) for w in _OFWORDS)
_MATH = r"(?:absolute value|square root|natural log)"
_STMT_RULES = [          # (pattern on the statement text, replacement)  applied to the start of a statement
    (re.compile(r"^calculate\s+(?!the\b)((?:%s)\s+of\b)" % _OFALT), r"calculate the \1"),
    (re.compile(r"^count\s+set\s+bits\s+of\b"), "count the set bits of"),
    (re.compile(r"^(trailing|leading)\s+(zeros|zeroes)\s+of\b"), r"count the \1 \2 of"),
    (re.compile(r"^isolate\s+lowest\s+bit\s+of\b"), "isolate the lowest bit of"),
    (re.compile(r"^clear\s+lowest\s+bit\s+of\b"), "clear the lowest bit of"),
    (re.compile(r"^reverse\s+bytes\s+of\b"), "reverse the bytes of"),
    (re.compile(r"^(extract|deposit)\s+bits\s+of\b"), r"\1 the bits of"),
    (re.compile(r"^read\s+byte\s+(?=\S)"), "read the next byte into "),
    (re.compile(r"^read\s+char\s+(?=\S)"), "read the next character into "),
    (re.compile(r"^convert\s+(character|number)\b"), r"convert the \1"),
]
_STORE = re.compile(r"\s+(?:and\s+)?store\s+in\s+(?=\S)")
_STORE_VERBS = re.compile(r"^(calculate|convert|call|count|extract|deposit|isolate|reverse|clear|trailing|leading)\b")


def _polish_code(code):
    """code is a line without its comment: change only what lies outside quotes"""
    lead = code[:len(code) - len(code.lstrip())]
    body = code[len(lead):]
    parts = _STR.split(body)                            # odd parts are quoted text
    if not parts or not parts[0].strip() and len(parts) == 1:
        return code
    head = parts[0]
    for pat, rep in _STMT_RULES:
        new = pat.sub(rep, head, count=1)
        if new != head:
            head = new
            break
    parts[0] = head
    if _STORE_VERBS.match(head) and not code.rstrip().endswith(":"):
        last = len(parts) - 1 if (len(parts) - 1) % 2 == 0 else len(parts) - 2
        parts[last] = _STORE.sub(" and store the result in ", parts[last], count=1)
    # 'set y to absolute value of x' reads better with the article
    for i in range(0, len(parts), 2):
        parts[i] = re.sub(r"(\bset\s+[^\s]+\s+to\s+)(%s\s+of\b)" % _MATH, r"\1the \2", parts[i])
    return lead + "".join(parts)


def polish(text):
    out = []
    for raw in text.split("\n"):
        code = zp.strip_comment(raw)
        tail = raw[len(code):]
        if code.strip():
            code = _polish_code(code.rstrip("\r")) + ("\r" if code.endswith("\r") else "")
        out.append(code + tail)
    return "\n".join(out)


def migrate(text, filename="<text>", assume_numbers=False, wording_only=False):
    if wording_only:
        return polish(text), []
    m = Migrator(text, filename, assume_numbers=assume_numbers)
    out = polish(m.run())
    return out, m.notes


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 1
    src = argv[0]
    with open(src, encoding="utf-8") as f:
        text = f.read()
    out, notes = migrate(text, src, assume_numbers="--numbers" in argv, wording_only="--wording-only" in argv)
    for n in notes:
        print("note: " + n, file=sys.stderr)
    try:
        zp.Program(src).load_text(out, src)
    except zp.ZoomyError as e:
        print(f"note: the result does not compile yet: {e}", file=sys.stderr)
    if "--inplace" in argv:
        with open(src, "w", encoding="utf-8") as f:
            f.write(out)
    elif "-o" in argv:
        with open(argv[argv.index("-o") + 1], "w", encoding="utf-8") as f:
            f.write(out)
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
