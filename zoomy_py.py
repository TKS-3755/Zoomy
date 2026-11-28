#!/usr/bin/env python3
"""
Zoomy full language: front end + Python back end.

zoomy.py uses this module for every program that needs more than the native number-only subset
(text, lists, tables, functions, loops, files, Python libraries, ...). The output is one standalone
Python file (zoomy_runtime.py is copied into it), so compiled programs need only Python 3.8+.
"""
import itertools
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


import zoomy_sentence as zs

STRICT = False            # --strict: grammar slips (a/an, is/are, ordinal nouns) stop the compile instead of warning
ELEM_VARS = set()         # hidden loop variables of 'scores that are above 5' and 'all of scores are above 5'
_QN = itertools.count(1)
_SOFT_SEEN = set()


def soft(file, line, msg):
    """A grammar slip that Zoomy can still understand: a warning, or an error under --strict."""
    if STRICT:
        raise ZoomyError(msg, file, line)
    key = (file, line, msg)
    if key not in _SOFT_SEEN:
        _SOFT_SEEN.add(key)
        print(f"[Warning] {file}:{line}: {msg} (understood anyway; use --strict to make this an error)", file=sys.stderr)


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
# Lexer
# =============================================================================
DEC_MODE = False                       # set while a program that uses Big Decimals is read (a decimal literal keeps all its digits)
BIG_MODE = False                       # set while a program that uses Big Numbers is read (hex literals are 1024 bits wide)
HEXBIN_RE = re.compile(r"0[xX][0-9A-Fa-f][0-9A-Fa-f_]*|0[bB][01][01_]*")
NUM_RE = re.compile(r"\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?")
WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
CHR_RE = re.compile(r"'(?:[^'\\]|\\[nt0\\'])'")
ESC = {'n': "\n", 't': "\t", 'r': "\r", '0': "\0", '\\': "\\", '"': '"', "'": "'", '{': "\0{", '}': "\0}"}
CHR_ESC = {'n': 10, 't': 9, '0': 0, '\\': 92, "'": 39}
TWO_OPS = ("<=", ">=", "==", "!=")


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


def lex(s, err, pos=None):
    """-> list of (kind, value, spaced) ; kinds: num str word op eof ; 'str' value is a list of parts."""
    toks, i, n = [], 0, len(s)
    start = 0

    class _Toks(list):
        def append(self, tok):
            list.append(self, tok)
            if pos is not None:
                pos.append(start)
    toks = _Toks()
    while True:
        sp = False
        while i < n and s[i] in " \t":
            i += 1
            sp = True
        start = i
        if i >= n:
            toks.append(("eof", None, sp))
            return toks
        c = s[i]
        if c == '"':
            parts, buf, i = [], [], i + 1
            while True:
                if i >= n:
                    raise err("unterminated text (missing closing \")")
                c = s[i]
                if c == '"':
                    i += 1
                    break
                if c == '\\':
                    if i + 1 >= n or s[i + 1] not in ESC:
                        raise err("bad escape in text (use \\n \\t \\\\ \\\" \\{ \\} or \\0)")
                    e = ESC[s[i + 1]]
                    buf.append(e[1:] if e.startswith("\0") and len(e) == 2 else e)
                    i += 2
                elif c == '{':
                    depth, j, instr = 1, i + 1, False
                    while j < n and depth:
                        if instr:
                            if s[j] == '\\':
                                j += 1
                            elif s[j] == '"':
                                instr = False
                        elif s[j] == '"':
                            instr = True
                        elif s[j] == '{':
                            depth += 1
                        elif s[j] == '}':
                            depth -= 1
                        j += 1
                    if depth:
                        raise err("missing } in text")
                    if buf:
                        parts.append("".join(buf))
                        buf = []
                    parts.append(("expr", s[i + 1:j - 1]))
                    i = j
                else:
                    buf.append(c)
                    i += 1
            if buf or not parts:
                parts.append("".join(buf))
            toks.append(("str", parts, sp))
            continue
        if c == "'":
            prev_word = i > 0 and (s[i - 1].isalnum() or s[i - 1] == '_')
            if prev_word and s[i + 1:i + 2] == 's' and s[i + 2:i + 3] != "'":
                toks.append(("op", "'s", False))
                i += 2
                continue
            m = CHR_RE.match(s, i)
            if not m:
                raise err("cannot understand the quote mark here (characters look like 'a'; text uses \"double quotes\")")
            body = m.group(0)[1:-1]
            toks.append(("num", float(CHR_ESC[body[1]] if body[0] == '\\' else ord(body)), sp))
            i = m.end()
            continue
        mh = HEXBIN_RE.match(s, i)
        if mh:                                         # 0xFF  0b1010  (whole numbers; Zoomy 5.5)
            v = int(mh.group(0).replace("_", ""), 0)
            width = 1024 if BIG_MODE else 64                 # Big Numbers (Zoomy 7) are 1024 bits wide
            if v >= 1 << width:
                raise err(f"{mh.group(0)} does not fit in {width} bits")
            toks.append(("num", v - (1 << width) if v >= 1 << (width - 1) else v, sp))
            i = mh.end()
            if i < n and (s[i].isalnum() or s[i] == '_'):
                raise err(f"a number cannot be followed by letters ('{mh.group(0)}{s[i]}...')")
            continue
        m = NUM_RE.match(s, i)
        if m and not (c == '.' and toks and toks[-1][0] in ("word", "op") and toks[-1][1] in (")", "]") and False):
            if c == '.' and toks and (toks[-1][0] == "word" or toks[-1][1] in (")", "]")) and not sp:
                pass                                   # attribute access like x.y handled below
            else:
                txt = m.group(0)
                if DEC_MODE and not txt.isdigit():
                    import fractions
                    toks.append(("num", fractions.Fraction(txt), sp))
                else:
                    toks.append(("num", int(txt) if txt.isdigit() and int(txt) >= 1 << 53 else float(txt), sp))
                i = m.end()
                if i < n and (s[i].isalpha() or s[i] == '_'):
                    raise err(f"a number cannot be followed by letters ('{m.group(0)}{s[i]}...')")
                continue
        m = WORD_RE.match(s, i)
        if m:
            toks.append(("word", m.group(0), sp))
            i = m.end()
            continue
        if c in "×÷":
            toks.append(("op", "*" if c == "×" else "/", sp))
            i += 1
            continue
        if s[i:i + 2] == "**":
            toks.append(("op", "^", sp))
            i += 2
            continue
        two = s[i:i + 2]
        if two in TWO_OPS:
            toks.append(("op", two, sp))
            i += 2
            continue
        if c in "()[],.+-*/%^<>":
            toks.append(("op", c, sp))
            i += 1
            continue
        if c == "#":
            raise err("comments are written as a (note in brackets) after 4 spaces or a tab, or on a line of their own; '#' is not used")
        raise err(f"I don't understand the character '{c}'")


# =============================================================================
# Expressions
# =============================================================================
RESERVED = {"and", "or", "not", "is", "plus", "minus", "times", "divided", "mod", "modulo", "contains",
            "yes", "no", "true", "false", "nothing", "call",
            "yeah", "yep", "yup", "aye", "affirmative", "nope", "nah", "nay"}

OF_OPS = {"length": "len", "uppercase": "upper", "lowercase": "lower", "trim": "trim", "text": "text",
          "sum": "sum", "smallest": "min", "largest": "max", "sorted": "sorted", "reversed": "reversed",
          "first": "first", "last": "last", "keys": "keys", "values": "values", "lines": "lines",
          "round": "round", "floor": "floor", "ceiling": "ceil", "sine": "sin", "cosine": "cos",
          "tangent": "tan", "arctangent": "atan", "exp": "exp"}
STORY = '[Zoomy]: “Though the doughty ploughman, home on furlough, leaned upon his plough and thought he ought to have bought and brought enough fresh dough and water from the lough after giving his land a thorough inspection before the rough drought fought its way through the borough, his once-haughty daughter—fraught with dread and distraught after a sudden onslaught of wolves had wrought slaughter upon their herd—sought shelter beneath an oak bough in a shadowed clough, where a startled chough cried out amid the eerie sough of the wind, and where, caught by a freezing draught that provoked a hacking cough and a sudden hiccough, she gazed past the dry cattle trough into the muddy slough, wondering if aught remained to prevent their winter from coming to nought, yet remembering how he had taught her that even a naughty child’s tender laugh could conquer a tough trial and reduce the heaviest burden to naught.”'

OF2_OPS = {("square", "root"): "sqrt", ("absolute", "value"): "abs", ("natural", "log"): "ln",
           ("character", "code"): "code"}
LEGACY_UNARY = {"sqrt", "abs", "floor", "ceil"}
ARITH_VERBS = {"set", "add", "subtract", "multiply", "divide"}
COMPARE_WORDS = [(("less", "than"), "lt"), (("greater", "than"), "gt"), (("at", "least"), "ge"), (("at", "most"), "le"),
                 (("equal", "to"), "eq"), (("more", "than"), "gt"), (("fewer", "than"), "lt")]
# comparatives and prepositions of the English grammar (not available under 'Simply,')
ENGLISH_COMPARE = [(("bigger", "than"), "gt"), (("larger", "than"), "gt"), (("higher", "than"), "gt"),
                   (("smaller", "than"), "lt"), (("lower", "than"), "lt"), (("no", "more", "than"), "le"),
                   (("no", "less", "than"), "ge"), (("same", "as"), "eq"), (("different", "from"), "ne"),
                   (("other", "than"), "ne"), (("under",), "lt"), (("below",), "lt"), (("over",), "gt"), (("above",), "gt")]
ARTICLES = {"the"}                                   # "a" and "an" are ordinary names unless a kind of thing follows (a number, an array...)
TUPLE_SIZES = {"pair": 2, "triple": 3, "quad": 4}
AN_EXCEPTIONS = ("hour", "honest", "honor", "honour", "heir")                       # silent h: 'an hour'
A_EXCEPTIONS = ("uni", "use", "usu", "util", "euro", "one", "once", "url", "uuid")  # 'u' that sounds like 'y': 'a unit'
TYPE_NAMES = {"number": "number", "numbers": "number", "index": "number", "indexes": "number", "indices": "number",
              "string": "text", "strings": "text", "text": "text", "texts": "text", "flag": "flag", "flags": "flag",
              "value": "value", "values": "value", "table": "table", "tables": "table",
              "array": "list", "arrays": "list", "list": "list", "lists": "list",
              "pair": ("tuple", 2), "pairs": ("tuple", 2), "triple": ("tuple", 3), "triples": ("tuple", 3),
              "quad": ("tuple", 4), "quads": ("tuple", 4)}
PLURAL_TYPE_WORDS = {"numbers", "indexes", "indices", "strings", "texts", "flags", "values", "tables", "arrays", "lists",
                     "pairs", "triples", "quads"}
SINGULAR_TYPE = {"numbers": "number", "indexes": "index", "indices": "index", "strings": "string", "texts": "text",
                 "flags": "flag", "values": "value", "tables": "table", "arrays": "array", "lists": "list",
                 "pairs": "pair", "triples": "triple", "quads": "quad"}
# Let ... be called NAME   /   Create ... named NAME  or  for NAME   /   Define ... for NAME
DECLARE_VERBS = {"let": [("be", "called")], "create": [("named",)], "define": [("as",)]}
ARRAY_VERBS = {"create": [("named",), ("for",)], "define": [("for",)]}      # arrays have their own sentences; no Let


def article_for(word):
    """'a' or 'an' for the (first word of the) name: an apple, an index, a unit, a total"""
    base = word.lower().split("_")[0]
    if base.startswith(AN_EXCEPTIONS):
        return "an"
    if base.startswith(A_EXCEPTIONS):
        return "a"
    return "an" if base[:1] in ("a", "e", "i", "o", "u") else "a"


ORDINALS = {"first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4, "sixth": 5, "seventh": 6, "eighth": 7,
            "ninth": 8, "tenth": 9, "last": -1}
SYMBOL_CMP = {"<": "lt", ">": "gt", "<=": "le", ">=": "ge", "==": "eq", "!=": "ne"}


class Parser:
    def __init__(self, toks, file, line, features, structural=False, simply=False):
        self.t, self.i, self.file, self.line, self.features = toks, 0, file, line, features
        self.structural = structural
        self.simply = simply                 # under 'Simply,' the old grammar applies (no articles, plurals, ...)
        self.eng = not simply
        self.it_name = None        # what 'it' means: the variable the line before used
        self.elem_hint = None      # name of the loop variable when a filter follows 'for each NAME in'

    # -- helpers
    def err(self, msg):
        return ZoomyError(msg, self.file, self.line)

    def peek(self, k=0):
        j = min(self.i + k, len(self.t) - 1)
        return self.t[j]

    def is_word(self, w, k=0):
        t = self.peek(k)
        return t[0] == "word" and t[1] == w

    def is_op(self, o, k=0):
        t = self.peek(k)
        return t[0] == "op" and t[1] == o

    def accept_words(self, *ws):
        for k, w in enumerate(ws):
            if not self.is_word(w, k):
                return False
        self.i += len(ws)
        return True

    def accept_store_in(self):
        """and store the result in   /   and store the answer in   (the bare 'store in' of Zoomy 6.1 and earlier is an error)"""
        save = self.i
        had_and = self.accept_words("and")
        if self.accept_words("store"):
            if had_and and (self.accept_words("the", "result") or self.accept_words("the", "answer")) and self.accept_words("in"):
                return True
            raise self.err("write 'and store the result in' (tools/migrate.py converts old programs)")
        self.i = save
        return False

    def expect_store_in(self):
        if not self.accept_store_in():
            raise self.err(f"expected 'and store the result in' but found {self.describe()}")

    def accept_op(self, o):
        if self.is_op(o):
            self.i += 1
            return True
        return False

    def expect_word(self, w, what=None):
        if not self.accept_words(w):
            raise self.err(f"expected '{w}'" + (f" {what}" if what else "") + f" but found {self.describe()}")

    def expect_op(self, o):
        if not self.accept_op(o):
            raise self.err(f"expected '{o}' but found {self.describe()}")

    def describe_at(self, off):
        save = self.i
        self.i += off
        try:
            return self.describe()
        finally:
            self.i = save

    def describe(self):
        k, v, _ = self.peek()
        if k == "eof":
            return "the end of the line"
        if k == "str":
            return "some text"
        return f"'{v if k != 'num' else _fmt_num(v)}'"

    def at_end(self):
        return self.peek()[0] == "eof"

    def expect_end(self):
        if not self.at_end():
            raise self.err(f"I did not expect {self.describe()} here")

    def attempt(self, fn):
        save = self.i
        try:
            return fn()
        except ZoomyError:
            self.i = save
            return None

    # -- precedence climbing
    def parse_or(self):
        left = self.parse_and()
        while self.accept_words("or"):
            self.features.add("logic")
            left = ["or", left, self.parse_and()]
        return left

    def parse_and(self):
        left = self.parse_not()
        while (self.is_word("and") and not self._and_is_separator() and not self.is_word("store", 1)) or (self.eng and self.is_word("but")):
            self.i += 1
            self.features.add("logic")
            left = ["and", left, self.parse_not()]
        return left

    def _and_is_separator(self):
        return getattr(self, "no_and", 0) > 0

    def parse_not(self):
        if self.accept_words("not"):
            self.features.add("logic")
            return ["not", self.parse_not()]
        if self.eng and self.is_word("neither") and self.peek(1)[0] != "eof":
            self.i += 1
            self.features.add("logic")
            node = self.parse_cmp()
            self.expect_word("nor", "after the first part of 'neither'")
            node = ["or", node, self.parse_cmp()]
            while self.accept_words("nor"):
                node = ["or", node, self.parse_cmp()]
            return ["not", node]
        if self.eng and self.is_word("either") and self.peek(1)[0] != "eof":
            self.i += 1
            self.features.add("logic")
            a = self.parse_and()
            self.expect_word("or", "after the first part of 'either'")
            return ["or", a, self.parse_and()]
        if self.eng and self.is_word("both") and self.peek(1)[0] != "eof":
            self.i += 1
            self.features.add("logic")
            a = self.parse_cmp()
            self.expect_word("and", "after the first part of 'both'")
            return ["and", a, self.parse_not()]
        if self.eng:
            q = self._quantifier()
            if q is not None:
                return q
            t = self._there()
            if t is not None:
                return t
        return self.parse_cmp()

    # -- Zoomy 5: all of / any of / none of / every X in / no X in ...  and  there is / there are ...
    def _word_at(self, k):
        t = self.peek(k)
        return t[1] if t[0] == "word" else None

    def _quantifier(self):
        w, n1, n2 = self._word_at(0), self._word_at(1), self._word_at(2)
        if w in ("all", "any", "none") and n1 == "of":
            mode, elem, skip = {"all": "all", "any": "any", "none": "none"}[w], f"__q{next(_QN)}", 2
        elif w in ("every", "each") and n1 and n2 == "in":
            mode, elem, skip = "all", n1, 3
        elif w in ("any", "no") and n1 and n2 == "in":
            mode, elem, skip = ("any" if w == "any" else "none"), n1, 3
        else:
            return None
        self.i += skip
        self.features.add("python")
        self.features.add("list")
        lst = self.parse_add()
        if not (self.accept_words("is") or self.accept_words("are")):
            raise self.err(f"after '{w} ... {'of ' if skip == 2 else 'in '}' say what is true of each one: 'is' or 'are' "
                           f"(like: {w} of scores are above 50)")
        self.t[self.i:self.i] = [("word", elem, True), ("word", "is", True)]
        cond = self.parse_cmp()
        return ["quant", mode, lst, cond, elem]

    def _there(self):
        if not (self.is_word("there") and (self.is_word("is", 1) or self.is_word("are", 1))):
            return None
        self.i += 2
        self.features.add("python")
        if self.is_word("nothing") and self.is_word("in", 1):
            self.i += 2
            return ["cmp", "eq", ["fn", "len", [self.parse_add()]], ["num", 0.0]]
        det = self._word_at(0)
        if det in ("no", "any", "a", "an", "some", "the"):
            self.i += 1
        else:
            det = None
        x = self.parse_add()
        if self.accept_words("in") or self.accept_words("inside"):
            c = self.parse_add()
            node = ["cmp", "contains", c, x, None]
            return ["not", node] if det == "no" else node
        ln = ["fn", "len", [x]]
        return ["cmp", "eq", ln, ["num", 0.0]] if det == "no" else ["cmp", "gt", ln, ["num", 0.0]]

    def parse_cmp(self):
        left = self.parse_add()
        k, v, _ = self.peek()
        if k == "op" and v in SYMBOL_CMP:
            self.i += 1
            return ["cmp", SYMBOL_CMP[v], left, self.parse_add()]
        if k != "word":
            return left
        cop = v if (v == "is" or (v == "are" and self.eng)) else None      # the verb 'to be' (agreement is checked later)
        if cop:
            self.i += 1
            neg = self.accept_words("not")
            if self.eng and self.is_word("the", 0) and self.is_word("same", 1):
                self.i += 1
            for words, op in COMPARE_WORDS + (ENGLISH_COMPARE if self.eng else []):
                if self.accept_words(*words):
                    node = ["cmp", op, left, self.parse_add(), cop]
                    return ["not", node] if neg and op != "eq" else (["cmp", "ne", left, node[3], cop] if neg else node)
            if self.eng and self.accept_words("between"):
                self.features.add("logic")
                lo = self.parse_add()
                self.expect_word("and", "in 'between A and B'")
                hi = self.parse_add()
                node = ["and", ["cmp", "ge", left, lo, cop], ["cmp", "le", left, hi]]
                return ["not", node] if neg else node
            if self.accept_words("in"):
                self.features.add("logic")
                node = ["cmp", "in", left, self.parse_add(), cop]
                return ["not", node] if neg else node
            for words, kind in ((("empty",), "empty"), (("nothing",), "none"), (("a", "number"), "number"),
                                (("a", "list"), "list"), (("a", "table"), "table"), (("text",), "text"),
                                (("a", "text"), "text"), (("a", "flag"), "bool"), (("a", "yes/no"), "bool")):
                if self.accept_words(*words):
                    self.features.add("logic")
                    return ["is", kind, left, neg, cop]
            return ["cmp", "ne" if neg else "eq", left, self.parse_add(), cop]
        if v == "contains" or (v == "contain" and self.eng):
            self.i += 1
            self.features.add("logic")
            return ["cmp", "contains", left, self.parse_add(), v]
        if self.eng and v in ("does", "do") and self.is_word("not", 1) and (self.is_word("contain", 2) or self.is_word("contains", 2)):
            cop = "contains" if v == "does" else "contain"
            self.i += 3
            self.features.add("logic")
            return ["not", ["cmp", "contains", left, self.parse_add(), cop]]
        if v in ("starts", "ends") and self.is_word("with", 1):
            self.i += 2
            self.features.add("logic")
            return ["cmp", v, left, self.parse_add()]
        return left

    def parse_linear(self):
        """Conversational mode: arithmetic is read strictly left to right, like a recipe."""
        left = self.parse_step()
        while True:
            if self.accept_words("plus") or self.accept_op("+"):
                left = ["bin", "plus", left, self.parse_step()]
            elif self.accept_words("minus") or self.accept_op("-"):
                left = ["bin", "minus", left, self.parse_step()]
            elif (self.is_word("times") and self.peek(1)[0] != "eof" and self.accept_words("times")) or self.accept_op("*"):
                left = ["bin", "times", left, self.parse_step()]
            elif self.accept_words("divided", "by") or self.accept_op("/"):
                left = ["bin", "divide", left, self.parse_step()]
            elif self.accept_words("modulo") or self.accept_words("mod") or self.accept_op("%"):
                left = ["bin", "mod", left, self.parse_step()]
            elif self.accept_words("to", "the", "power", "of") or self.accept_op("^"):
                left = ["bin", "pow", left, self.parse_step()]
            else:
                return left

    def parse_step(self):
        if self.accept_op("-"):
            e = self.parse_step()
            return ["num", -e[1]] if e[0] == "num" else ["neg", e]
        if self.accept_op("+"):
            return self.parse_step()
        return self.parse_postfix()

    def parse_add(self):
        if not self.structural:
            return self.parse_linear()
        left = self.parse_mul()
        while True:
            if self.accept_words("plus") or self.accept_op("+"):
                left = ["bin", "plus", left, self.parse_mul()]
            elif self.accept_words("minus") or self.accept_op("-"):
                left = ["bin", "minus", left, self.parse_mul()]
            else:
                return left

    def parse_mul(self):
        left = self.parse_unary()
        while True:
            if (self.is_word("times") and self.peek(1)[0] != "eof" and self.accept_words("times")) or self.accept_op("*"):
                left = ["bin", "times", left, self.parse_unary()]
            elif self.accept_words("divided", "by") or self.accept_op("/"):
                left = ["bin", "divide", left, self.parse_unary()]
            elif self.accept_words("modulo") or self.accept_words("mod") or self.accept_op("%"):
                left = ["bin", "mod", left, self.parse_unary()]
            else:
                return left

    def parse_unary(self):
        if self.accept_op("-"):
            e = self.parse_unary()
            return ["num", -e[1]] if e[0] == "num" else ["neg", e]
        if self.accept_op("+"):
            return self.parse_unary()
        return self.parse_pow()

    def parse_pow(self):
        base = self.parse_postfix()
        if self.accept_words("to", "the", "power", "of") or self.accept_op("^"):
            return ["bin", "pow", base, self.parse_unary()]
        return base

    def parse_postfix(self):
        e = self.parse_primary()
        while True:
            k, v, sp = self.peek()
            if k == "op" and v == "'s" or (k == "op" and v == "." and self.peek(1)[0] == "word"):
                self.i += 1
                t = self.peek()
                if t[0] != "word":
                    raise self.err(f"expected a name after '{v}'")
                self.i += 1
                self.features.add("python")
                e = ["attr", e, t[1]]
            elif (k == "word" and v == "at" and not getattr(self, "no_at", 0)
                  and (self.peek(1)[0] in ("str", "num") or (self.peek(1)[0] == "word" and self.peek(1)[1] not in RESERVED)
                       or (self.peek(1)[0] == "op" and self.peek(1)[1] in ("(", "[")))
                  and not self.is_word("index", 1)):
                self.i += 1
                key = self.operand()
                self.features.add("index")
                e = ["index", e, key]
            elif k == "op" and v == "[" and not sp:
                self.i += 1
                idx = self.parse_or()
                self.expect_op("]")
                self.features.add("index")
                e = ["index", e, idx]
            elif k == "op" and v == "(" and not sp and e[0] in ("var", "attr", "call"):
                self.i += 1
                args, kw = self.parse_paren_args()
                self.features.add("call")
                e = ["call", e, args, kw]
            elif (self.eng and k == "word" and v in ("that", "which", "who", "where", "whose") and e[0] in ("var", "attr", "index", "call")
                  and self.peek(1)[0] != "eof"):
                e = self._filter(e)
            else:
                return e

    def parse_paren_args(self):
        args, kw = [], []
        self.no_and = getattr(self, "no_and", 0) + 1
        try:
            if self.accept_op(")"):
                return args, kw
            while True:
                if self.peek()[0] == "word" and self.is_word("named", 1):
                    name = self.peek()[1]
                    self.i += 2
                    kw.append((name, self.parse_cmp()))
                else:
                    args.append(self.parse_or_saved())
                if self.accept_op(","):
                    continue
                self.expect_op(")")
                return args, kw
        finally:
            self.no_and -= 1

    def parse_or_saved(self):                       # an argument inside ( ) may use 'and'/'or' freely
        save, self.no_and = self.no_and, 0
        try:
            return self.parse_or()
        finally:
            self.no_and = save

    def parse_with_args(self):
        args, kw = [], []
        self.no_and = getattr(self, "no_and", 0) + 1
        try:
            while True:
                if self.peek()[0] == "word" and self.is_word("named", 1):
                    name = self.peek()[1]
                    self.i += 2
                    kw.append((name, self.parse_cmp()))
                else:
                    args.append(self.parse_cmp())
                if not self._accept_and():
                    return args, kw
        finally:
            self.no_and -= 1

    def _accept_and(self):
        if self.is_word("and") and not self.is_word("store", 1):
            self.i += 1
            return True
        return False

    def parse_primary(self):
        k, v, sp = self.peek()
        if k == "num":
            self.i += 1
            return ["num", v]
        if k == "str":
            self.i += 1
            parts = []
            for p in v:
                if isinstance(p, tuple):
                    parts.append(self.sub_expr(p[1]))
                    self.features.add("interp")
                else:
                    parts.append(p)
            return ["str", parts]
        if k == "op":
            if v == "(":
                self.i += 1
                save, self.no_and = getattr(self, "no_and", 0), 0
                try:
                    e = self.parse_or()
                    if self.eng and self.is_op(","):
                        items = [e]
                        while self.accept_op(","):
                            items.append(self.parse_or())
                        e = ["tuple", items]
                finally:
                    self.no_and = save
                self.expect_op(")")
                return e
            if v == "[":
                self.i += 1
                self.features.add("list")
                items = []
                save, self.no_and = getattr(self, "no_and", 0), 0
                try:
                    if not self.accept_op("]"):
                        while True:
                            items.append(self.parse_or())
                            if self.accept_op(","):
                                continue
                            self.expect_op("]")
                            break
                finally:
                    self.no_and = save
                return ["list", items]
            raise self.err(f"I did not expect {self.describe()} here")
        if k == "eof":
            raise self.err("the line ends too early (a value is missing)")
        return self.parse_word()

    def sub_expr(self, src):
        toks = lex(src, self.err)
        p = Parser(toks, self.file, self.line, self.features, self.structural, self.simply)
        e = p.parse_or()
        p.expect_end()
        return e

    def operand(self):
        if self.accept_op("-"):
            e = self.operand()
            return ["num", -e[1]] if e[0] == "num" else ["neg", e]
        if self.accept_op("+"):
            return self.operand()
        return self.parse_postfix()

    def _it(self, w):
        if self.it_name is None:
            raise self.err(f"'{w}' has nothing to point at yet: it means the variable the line before used, so name the variable here instead")
        return self.it_name

    def _singular_hint(self, e):
        if self.elem_hint:
            return self.elem_hint
        if e[0] == "var":
            n = e[1]
            if n.lower().endswith("ies") and len(n) > 3:
                return n[:-3] + "y"
            if n.lower().endswith("s") and not n.lower().endswith("ss") and len(n) > 2:
                return n[:-1]
        return "item"

    def _filter(self, e):
        """scores that are above 80  /  players where player's score is above 50  /  players whose score is above 50"""
        elem = self._singular_hint(e)
        w = self.peek()[1]
        self.i += 1
        nk, nv, _ = self.peek()
        if w == "whose":
            self.t[self.i:self.i] = [("word", elem, True), ("op", "'s", False)]
        elif w in ("that", "which", "who") and nk == "word" and nv in ("is", "are"):
            self.t[self.i] = ("word", "is", True)
            self.t.insert(self.i, ("word", elem, True))
        elif w in ("that", "which", "who") and nk == "word" and nv in ("contain", "contains", "start", "starts", "end", "ends"):
            self.t[self.i] = ("word", {"contain": "contains", "start": "starts", "end": "ends"}.get(nv, nv), True)
            self.t.insert(self.i, ("word", elem, True))
        self.features.add("python")
        self.features.add("list")
        cond = self.parse_or()
        return ["filter", e, cond, elem]

    def _number_words(self):
        """twenty one / three hundred / one thousand five: several number words in a row are one number
        (a single word such as 'three' is left to the resolver, so a variable called three still wins)"""
        words, j = [], self.i
        while True:
            t = self.t[j]
            if t[0] != "word" or t[1].lower() not in zs.NUMBER_WORDS:
                break
            words.append(t[1])
            j += 1
            if self.t[j][0] == "op" and self.t[j][1] == "-" and self.t[j + 1][0] == "word" and self.t[j + 1][1].lower() in zs.NUM_WORDS:
                j += 1
        if len(words) < 2:
            return None
        val = zs.number_run(words)
        if val is None:
            return None
        self.i = j
        return ["num", float(val)]

    def parse_word(self):
        w = self.peek()[1]
        nxt = self.peek(1)
        nw = nxt[1] if nxt[0] == "word" else None
        if self.eng:
            if w.lower() in ("a", "an") and nw is not None and nw.lower() in zs.BIG_WORDS or nw is not None and w.lower() == "a" and nw.lower() in zs.MULT_WORDS:
                self.i += 1                                  # 'a hundred', 'a dozen'
                return self.parse_word()
            if w.lower() in zs.NUMBER_WORDS:
                n = self._number_words()
                if n is not None:
                    return n
            if w in ("it", "them") and nw not in ("fails", "fail", "failed"):
                self.i += 1
                return ["var", self._it(w)]
            if w in ("its", "their") and nxt[0] == "word":
                name = self._it(w)
                two = {("square", "root"), ("absolute", "value"), ("natural", "log"), ("character", "code")}
                if (nw, self._word_at(2)) in two:
                    self.t[self.i:self.i + 3] = [self.t[self.i + 1], self.t[self.i + 2], ("word", "of", True), ("word", name, True)]
                elif nw in OF_OPS:
                    self.t[self.i:self.i + 2] = [self.t[self.i + 1], ("word", "of", True), ("word", name, True)]
                else:
                    self.t[self.i:self.i + 1] = [("word", name, True), ("op", "'s", False)]
                return self.parse_word() if self.t[self.i][0] == "word" else self.parse_primary()
            if w == "the":
                if nxt[0] != "word":
                    raise self.err(f"expected a name after 'the' but found {self.describe_at(1)}")
                self.i += 1
                return self.parse_word()
            if w in ("a", "an") and nw in TUPLE_SIZES:
                return self._tuple(TUPLE_SIZES[nw])
            if w in ("a", "an") and (nw in TYPE_NAMES or nw == "shared"):
                raise self.err(f"'{w}' is for making something new, and that is its own statement: 'Let a number be called total'. "
                               f"To use something that exists, just name it (or say 'the total')")
            if w in ORDINALS and not (w in ("first", "last") and nw == "of"):
                r = self.attempt(self._ordinal)
                if r is not None:
                    self.features.add("index")
                    return r
        if w in ("yes", "true", "yeah", "yep", "yup", "aye", "affirmative"):
            self.i += 1
            self.features.add("logic")
            return ["bool", True]
        if w in ("no", "false", "nope", "nah", "nay"):
            self.i += 1
            self.features.add("logic")
            return ["bool", False]
        if w == "nothing":
            self.i += 1
            self.features.add("logic")
            return ["none"]
        if w == "call":
            self.i += 1
            self.features.add("call")
            target = self.parse_postfix()
            if self.accept_words("with"):
                args, kw = self.parse_with_args()
                if target[0] == "call":
                    raise self.err("a call cannot have two sets of arguments")
                return ["call", target, args, kw]
            return target if target[0] == "call" else ["call", target, [], []]
        if w == "empty" and nw in ("list", "table"):
            self.i += 2
            self.features.add("list")
            return ["list", []] if nw == "list" else ["table", []]
        if w == "table" and nw == "with":
            self.i += 2
            self.features.add("list")
            pairs = []
            self.no_and = getattr(self, "no_and", 0) + 1
            try:
                while True:
                    key = self.parse_add()
                    self.expect_word("as", "after a table key")
                    pairs.append((key, self.parse_cmp()))
                    if not self._accept_and():
                        break
            finally:
                self.no_and -= 1
            return ["table", pairs]
        # ---- "<word> of X" operators
        if nw == "of" and w in OF_OPS:
            self.i += 2
            if OF_OPS[w] not in LEGACY_UNARY:
                self.features.add("fn")
            return ["fn", OF_OPS[w], [self.operand()]]
        if nw and self.is_word("of", 2) and (w, nw) in OF2_OPS:
            self.i += 3
            op = OF2_OPS[(w, nw)]
            if op not in LEGACY_UNARY:
                self.features.add("fn")
            return ["fn", op, [self.operand()]]
        if w == "remainder" and nw == "of":
            self.i += 2
            a = self.operand()
            self.expect_word("divided")
            self.expect_word("by")
            return ["fn", "rem", [a, self.operand()]]
        if w == "number" and nw == "from":
            self.i += 2
            self.features.add("fn")
            return ["fn", "numfrom", [self.operand()]]
        if w == "character" and nw == "with" and self.is_word("code", 2):
            self.i += 3
            self.features.add("fn")
            return ["fn", "chr", [self.operand()]]
        if w == "random" and nw == "number":
            self.i += 2
            self.features.add("fn")
            return ["fn", "randnum", []]
        if w == "random" and nw == "between":
            self.i += 2
            self.features.add("fn")
            self.no_and = getattr(self, "no_and", 0) + 1
            try:
                a = self.operand()
                self.expect_word("and")
                return ["fn", "randbetween", [a, self.operand()]]
            finally:
                self.no_and -= 1
        if w == "current" and nw == "time":
            self.i += 2
            self.features.add("fn")
            return ["fn", "now", []]
        if w == "arguments" and (nxt[0] != "op" or nxt[1] not in ("=",)):
            if nw is None or nw in ("and", "or", "plus", "minus", "times", "is", "to", "by", "in"):
                self.i += 1
                self.features.add("fn")
                return ["fn", "args", []]
        if w == "ask" and nxt[0] in ("str", "word", "num", "op") and nxt[0] != "eof" and not (nxt[0] == "op" and nxt[1] not in ("(", "[")):
            self.i += 1
            self.features.add("fn")
            return ["fn", "ask", [self.operand()]]
        if w == "file" and nxt[0] != "eof":
            r = self.attempt(lambda: self._file_exists())
            if r is not None:
                return r
        specials = {"item": self._item, "split": self._split, "join": self._join, "replace": self._replace,
                    "slice": self._slice, "position": self._position, "count": self._count,
                    "format": self._format, "rounded": self._rounded}
        if w in specials and nxt[0] != "eof":
            r = self.attempt(specials[w])
            if r is not None:
                self.features.add("fn")
                return r
        if w in RESERVED:
            raise self.err(f"'{w}' is a word with a special meaning here; I did not expect it at this point")
        self.i += 1
        return ["var", w]

    def _tuple(self, n):
        """a pair 3, 4   /   a triple (1, 2, 3)   /   a quad a, b, c, d : exactly n values"""
        word = self.peek(1)[1]
        self.i += 2
        self.features.add("list")
        if self.is_op("("):
            save = self.i
            e = self.attempt(self.parse_primary)
            if e is not None and e[0] == "tuple" and len(e[1]) == n:
                return e
            self.i = save
        items = [self.parse_add()]
        while len(items) < n:
            if not self.accept_op(","):
                raise self.err(f"a {word} has {n} values separated by commas (like: a {word} " + ", ".join(str(k + 1) for k in range(n)) + ")")
            items.append(self.parse_add())
        return ["tuple", items]

    def _ordinal(self):
        """the third item of L  /  the last score in L  /  the second of P"""
        w = self.peek()[1]
        self.i += 1
        noun = None
        if self.is_word("of"):
            self.i += 1
        else:
            t = self.peek()
            if t[0] != "word" or t[1] in RESERVED or not (self.is_word("of", 1) or self.is_word("in", 1)):
                raise self.err("not an ordinal phrase")
            noun = t[1]
            self.i += 2
        cont = self.operand()
        if w == "last":
            self.features.add("fn")
            return ["fn", "last", [cont], noun]
        return ["index", cont, ["num", float(ORDINALS[w])], noun]

    # ---- multi-word operators (tried with backtracking, so that e.g. a variable called 'item' still works)
    def _file_exists(self):
        self.expect_word("file")
        p = self.operand()
        self.expect_word("exists")
        return ["fn", "exists", [p]]

    def _item(self):
        self.expect_word("item")
        idx = self.parse_add()
        self.expect_word("of")
        lst = self.operand()
        self.features.add("index")
        return ["index", lst, idx]

    def _split(self):
        self.expect_word("split")
        t = self.operand()
        self.expect_word("by")
        return ["fn", "split", [t, self.operand()]]

    def _join(self):
        self.expect_word("join")
        lst = self.operand()
        self.expect_word("with")
        return ["fn", "join", [lst, self.operand()]]

    def _replace(self):
        self.expect_word("replace")
        a = self.operand()
        self.expect_word("with")
        b = self.operand()
        self.expect_word("in")
        return ["fn", "replace", [a, b, self.operand()]]

    def _slice(self):
        self.expect_word("slice")
        lst = self.operand()
        self.expect_word("from")
        a = self.operand()
        self.expect_word("to")
        return ["fn", "slice", [lst, a, self.operand()]]

    def _position(self):
        self.expect_word("position")
        self.expect_word("of")
        x = self.operand()
        self.expect_word("in")
        return ["fn", "position", [x, self.operand()]]

    def _count(self):
        self.expect_word("count")
        self.expect_word("of")
        x = self.operand()
        self.expect_word("in")
        return ["fn", "count", [x, self.operand()]]

    def _format(self):
        self.expect_word("format")
        x = self.operand()
        self.expect_word("with")
        n = self.operand()
        if not (self.accept_words("decimals") or self.accept_words("decimal")):
            raise self.err("expected 'decimals'")
        return ["fn", "format", [x, n]]

    def _rounded(self):
        self.expect_word("rounded")
        x = self.operand()
        self.expect_word("to")
        n = self.operand()
        if not (self.accept_words("places") or self.accept_words("place")):
            raise self.err("expected 'places'")
        return ["fn", "rounded", [x, n]]


def _fmt_num(v):
    return repr(int(v)) if v == int(v) else repr(v)


# =============================================================================
# Source -> blocks -> statements
# =============================================================================
class Blk:
    __slots__ = ("line", "text", "body", "header")

    def __init__(self, line, text, header):
        self.line, self.text, self.header, self.body = line, text, header, []


_DECL_START = re.compile(r"(?i)(let|create|define)\s+(a|an)\s")


def split_declarations(stmt):
    """'Let a number be called x and set x to 5'  ->  two statements (making and filling stay separate actions,
    but one line may chain them with 'and')."""
    if stmt.endswith(":") or not _DECL_START.match(stmt):
        return [stmt]
    cuts, depth, quote, k = [], 0, None, 0
    while k < len(stmt):
        c = stmt[k]
        if quote:
            quote = None if c == quote else quote
        elif c in "\"'" and not (c == "'" and k > 0 and stmt[k - 1].isalnum()):
            quote = c
        elif c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif depth == 0 and re.match(r"\sand\s", stmt[k:k + 5], re.I) and k > 0:
            head = stmt[(cuts[-1] if cuts else 0):k]
            rest = stmt[k + 5:]
            if _DECL_START.match(head.strip()) or _DECL_START.match(rest.lstrip()):
                cuts.append(k + 5)
                k += 4
        k += 1
    if not cuts:
        return [stmt]
    out, a = [], 0
    for c in cuts:
        out.append(stmt[a:c - 5].strip())
        a = c
    out.append(stmt[a:].strip())
    return out


def parse_blocks(text, filename, trace=None):
    """trace: a list that collects (first line, last line, the statement as written, the plain statements it was read as)"""
    items = []
    lines = text.splitlines()
    idx_line = 0
    while idx_line < len(lines):
        lineno, raw = idx_line + 1, lines[idx_line]
        idx_line += 1
        stmt = strip_comment(raw).strip()
        raw = raw.expandtabs(4)
        # Zoomy 5: a line that ends in a comma, 'and', 'or' or 'then' goes on with the next line
        while stmt and zs.needs_continuation(stmt) and idx_line < len(lines):
            more = strip_comment(lines[idx_line]).strip()
            idx_line += 1
            if more:
                if stmt.endswith(",") and zs.first_word(more) in zs.STMT_VERBS:
                    stmt = stmt[:-1].rstrip() + " then " + more      # set x to 1,  <newline>  print x
                else:
                    stmt = stmt + " " + more
        if stmt:
            try:
                sentences = zs.normalize(stmt)
            except zs.SentenceError as e:
                raise ZoomyError(str(e), filename, lineno)
            if trace is not None:
                trace.append((lineno, idx_line, [strip_comment(l).strip() for l in lines[lineno - 1:idx_line] if strip_comment(l).strip()], list(sentences)))
            base = len(raw) - len(raw.lstrip())
            for depth, sent in sentences:
                for part in split_declarations(sent):
                    items.append((lineno, base + 4 * depth, part))

    def block(idx, indent):
        out = []
        while idx < len(items):
            lineno, ind, stmt = items[idx]
            if ind < indent:
                break
            if ind > indent:
                raise ZoomyError("unexpected indentation (this line is indented more than the one before it)", filename, lineno)
            header = stmt.endswith(':') or re.fullmatch(r"(?i)(structurally|simply),", stmt) is not None
            b = Blk(lineno, stmt[:-1].strip() if header else stmt, header)
            idx += 1
            if idx < len(items) and items[idx][1] > ind:
                if not header:
                    raise ZoomyError("unexpected indentation (only lines ending in ':' can have an indented block below them)",
                                     filename, items[idx][0])
                b.body, idx = block(idx, items[idx][1])
            out.append(b)
        return out, idx

    blocks, idx = block(0, items[0][1] if items else 0)
    if idx < len(items):
        raise ZoomyError("inconsistent indentation", filename, items[idx][0])
    return blocks


def _why(written, sentences):
    """short reasons (plain English) why the sentence layer read WRITTEN as SENTENCES"""
    src = " ".join(written)
    low = src.lower()
    first = zs.first_word(zs.strip_lead(src.strip()))
    notes = []
    if zs._LEAD.match(src.strip()) and zs.strip_lead(src.strip()) != src.strip():
        notes.append("'And' / 'Also' / 'Then' / 'After that,' only link a sentence to the one before it, so they are ignored")
    body = zs.strip_lead(src.strip())
    cleaned = zs._fillers(zs._strip_punct(body))
    if cleaned != zs._strip_punct(body):
        removed = zs._strip_punct(body)[:len(zs._strip_punct(body)) - len(cleaned)].strip(" ,")
        notes.append(f"'{removed}' is only a polite or chatty opening, so it is ignored")
    if len(written) == 1 and re.search(r"[.!]$", src) and not src.endswith(".."):
        notes.append("the full stop / exclamation mark at the end is ignored")
    pieces = [p for chunk in zs.split_top(src, ";") for p in zs._split_joiners(chunk)] or [src]
    seen = set()
    for piece in pieces:
        fw = zs.first_word(zs.strip_lead(piece.strip()))
        if fw in seen:
            continue
        seen.add(fw)
        reg = zs.register_note(zs._fillers(zs._strip_punct(zs.strip_lead(piece.strip()))))
        if reg:
            notes.append(reg)
            continue
        if fw in ("show", "display", "say"):
            notes.append(f"'{fw}' means 'print'")
        elif fw in ("increase", "decrease"):
            notes.append(f"'{fw}' means '{'add' if fw == 'increase' else 'subtract'}'")
        elif fw in ("double", "triple", "halve"):
            notes.append(f"'{fw}' means '{'divide by 2' if fw == 'halve' else 'multiply by ' + ('2' if fw == 'double' else '3')}'")
        elif fw == "take":
            notes.append("'take ... away from' means 'subtract ... from'")
        elif fw in ("put", "insert", "return", "continue"):
            notes.append(f"'{fw}' is another way to say '{sentences[0][1].split()[0]}'" if sentences else "")
    if re.search(r"(?i)\b(twice|once|\w+ times)\s*[.!]?$", src) and any(t.startswith("repeat") for _, t in sentences):
        notes.append("a counting word at the end ('twice', '3 times') makes the action a 'repeat'")
    if sentences and re.match(r"(?i)^(unless|until|while|if)\b", sentences[0][1]) and not zs._IF_START.match(body):
        notes.append(f"a condition after the action ('... {sentences[0][1].split()[0]} ...') puts the action under that condition")
    for m in zs._TRAILING.finditer(src):
        w = re.sub(r"\s+", " ", m.group(1).lower())
        if zs.HEAD_KW.get(w) not in (None, w) and not zs.mask_of(src)[m.start()]:
            notes.append(f"'{w}' means '{zs.HEAD_KW[w]}'")
            break
    m = re.search(r"(?i)\b(" + zs.ELSE_WORDS + r")\b", src)
    if m and not zs.mask_of(src)[m.start()] and m.group(1).lower() not in ("otherwise", "else"):
        notes.append(f"'{re.sub(chr(92) + 's+', ' ', m.group(1).lower())}' means 'otherwise'")
    elif re.match(r"(?i)^(else|otherwise)\b", body):
        notes.append("'else' and 'otherwise' mean the same")
    for pat, rep_ in zs._LOOP_HEADS:
        if re.fullmatch(pat + r":?", body.strip(), re.I) and sentences:
            notes.append(f"'{body.strip().rstrip(':')}' is another way to say '{sentences[0][1].rstrip(':')}'")
            break
    cm = zs._comparisons(body)
    if cm != body:
        notes.append("a different way to compare is read as the plain one ('exceeds' = 'is above', 'differs from' = 'is not', ...)")
    if len([s for s in sentences if s[0] == 0 and not s[1].startswith(("otherwise", "else"))]) > 1 and ";" in src + " then " + low:
        notes.append("one line holds several actions (joined with ';', 'then', ', and' ...): each becomes its own statement")
    if "'t" in src or "n't" in low or "it's" in low:
        notes.append("a contraction ('isn't', 'can't', ...) is written out in full")
    if re.search(r"(?i)\b(must|should|cannot|can't)\b", low) and any(t.startswith("check") for _, t in sentences):
        notes.append("'must / should / cannot' states something the program checks")
    mask = zs.mask_of(src)
    for m in re.finditer(r"(?i)\b(?:(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million)(?:[\s-]+|\b))+", src):
        if not mask[m.start()] and m.group().strip().lower() not in ("one", "first"):
            val = zs.number_run(re.split(r"[\s-]+", m.group().strip()))
            if val is not None:
                notes.append(f"'{m.group().strip()}' is read as the number {val}")
                break
    return [n for n in notes if n]


def explain(text, filename="program"):
    """--explain: for every line, how the sentence layer read it. Returns the text to print."""
    recs, err = [], None
    try:
        parse_blocks(text, filename, recs)
    except ZoomyError as e:
        err = e
    lines = text.splitlines()
    out, by_line = [], {r[0]: r for r in recs}
    i = 1
    width = len(str(len(lines)))
    while i <= len(lines):
        raw = lines[i - 1]
        if i in by_line:
            first, last, written, sentences = by_line[i]
            plain_same = len(written) == 1 and [t.lower() for _, t in sentences] == [written[0].lower()]
            # an unchanged line is shown on one line
            mark = "=" if plain_same else "~"
            out.append(f"{i:>{width}} {mark} {written[0]}")
            for k, w in enumerate(written[1:], 1):
                out.append(f"{first + k:>{width}} ~ {w}")
            if not plain_same:
                n = len(sentences)
                out.append(" " * (width + 3) + "I read this as:")
                for depth, t in sentences:
                    out.append(" " * (width + 3) + "    " + "    " * depth + t)
                for n_ in _why(written, sentences):
                    out.append(" " * (width + 3) + "  because " + n_)
            i = last + 1
        else:
            if raw.strip():
                out.append(f"{i:>{width}}   {raw.strip()}")
            i += 1
    if err is not None:
        out.append("")
        out.append(f"[Error] {err}")
    else:
        changed = sum(1 for r in recs if not (len(r[2]) == 1 and [t.lower() for _, t in r[3]] == [r[2][0].lower()]))
        out.append("")
        out.append(f"{len(recs)} statement line(s); {changed} read differently from how they are written ('~'), {len(recs) - changed} already plain ('=').")
    return "\n".join(out) + "\n"


class Front:
    """Turns blocks into statement lists (each statement is a list: [kind, line, ...])."""

    def __init__(self, filename, features):
        self.file, self.features = filename, features
        self.loop_depth = 0
        self.func_depth = 0
        self.structural = False
        self.simply = False
        self.last_var = None       # what 'it' means: the variable the previous statement used

    def err(self, line, msg):
        return ZoomyError(msg, self.file, line)

    def parser(self, text, line):
        def mk(msg):
            return ZoomyError(msg, self.file, line)
        p = Parser(lex(text, mk), self.file, line, self.features, self.structural, self.simply)
        p.it_name = self.last_var
        return p

    # -- Zoomy 5: what does 'it' point at?
    def _target_name(self, s):
        k = s[0]
        place = None
        if k == "set":
            place = s[2]
        elif k == "aug":
            place = s[4]
        elif k in ("append", "remove", "removeat"):
            place = s[3]
        elif k == "insert":
            place = s[3]
        elif k in ("sort", "reverse", "clear"):
            place = s[2]
        elif k == "store":
            place = s[2]
        elif k == "load":
            place = s[4]
        elif k == "read":
            place = s[3]
        elif k == "callstore":
            place = s[3]
        elif k == "let":
            return s[2] if isinstance(s[2], str) else None
        if not isinstance(place, list):
            return None
        while place and place[0] in ("index", "attr"):
            place = place[1]
        if place and place[0] in ("var", "decl"):
            return place[1]
        return None

    def _note(self, st):
        for one in (st if st and isinstance(st[0], list) else [st]):
            name = self._target_name(one) if one else None
            if name:
                self.last_var = name

    # -- blocks
    def convert(self, blks):
        out = []
        for b in blks:
            st = self.convert_one(b, out)
            if st is None:
                continue
            if st and isinstance(st[0], list):
                out.extend(st)
            else:
                out.append(st)
            self._note(st)
        return out

    def body(self, b, loop=False, func=False):
        if loop:
            self.loop_depth += 1
        if func:
            self.func_depth += 1
        try:
            return self.convert(b.body)
        finally:
            if loop:
                self.loop_depth -= 1
            if func:
                self.func_depth -= 1

    def convert_one(self, b, out):
        text, line = b.text, b.line
        p = self.parser(text, line)
        t0 = p.peek()
        w = t0[1] if t0[0] == "word" else None
        if w is not None and not self.simply:
            self.sentence_guard(w, text, line)
        try:
            if b.header:
                return self.header(b, p, w, out)
            if b.body:
                raise self.err(line, "unexpected indentation")
            return self.simple(b, p, w)
        except ZoomyError as e:
            raise self.friendlier(e, text, line)

    # -- Zoomy 5: friendlier mistakes (Zoomy speaks in the present tense, one action per sentence)
    PAST = {"added": "add", "subtracted": "subtract", "multiplied": "multiply", "divided": "divide", "printed": "print",
            "appended": "append", "inserted": "insert", "removed": "remove", "sorted": "sort", "reversed": "reverse",
            "cleared": "clear", "stored": "store", "loaded": "load", "finished": "finish", "failed": "fail",
            "checked": "check", "skipped": "skip", "stopped": "stop", "waited": "wait", "wrote": "write",
            "deleted": "delete", "converted": "convert", "calculated": "calculate", "ran": "run", "gave": "give",
            "showed": "show", "displayed": "display", "increased": "increase", "decreased": "decrease", "doubled": "double",
            "halved": "halve", "returned": "return"}

    def sentence_guard(self, w, text, line):
        lw = w.lower()
        rest = text.split(None, 1)[1] if len(text.split(None, 1)) > 1 else ""
        if lw in self.PAST and not (lw in ("sorted", "reversed") and rest.lower().startswith("of ")):
            raise self.err(line, f"Zoomy always speaks in the present tense: say '{self.PAST[lw]} {rest}'".rstrip() + f", not '{w} {rest}'".rstrip())
        if lw == "will" or (lw == "going" and rest.lower().startswith("to ")):
            after = rest.split(None, 1)[1] if lw == "going" and len(rest.split(None, 1)) > 1 else rest
            raise self.err(line, f"Zoomy always speaks in the present tense: just say what to do now (like: '{after}'), not '{w} ...'")
        if lw == "because":
            raise self.err(line, "'because' explains an action, so it goes after one: check that total is above 0 because \"total must be positive\"")
        if lw in ("although", "though", "whereas"):
            raise self.err(line, f"Zoomy has no '{lw}'; write two lines, or join the conditions with 'but' (like: if a is 1 but b is 2:)")

    def friendlier(self, e, text, line):
        m = re.match(r"I did not expect '([A-Za-z_]+)' here", e.message)
        if m and m.group(1).lower() in zs.STMT_VERBS and m.group(1).lower() not in ("let", "create", "define") and not self.simply:
            return self.err(line, f"this line has two actions (I did not expect '{m.group(1)}' here): join them with 'and', 'then' or ';', "
                                  f"or put each on its own line")
        return e

    # -- headers --------------------------------------------------------------------
    def header(self, b, p, w, out):
        line = b.line
        if w in ("else", "otherwise"):
            p.i += 1
            prev = out[-1] if out else None
            if prev is None or prev[0] != "if":
                raise self.err(line, f"'{w}:' must directly follow an 'if' block")
            tail = prev
            while tail[4] is not None and len(tail[4]) == 1 and tail[4][0][0] == "if" and tail[4][0][-1] == "elif":
                tail = tail[4][0]
            if tail[4] is not None:
                raise self.err(line, f"this '{w}' has no 'if' left to belong to")
            if p.accept_words("if"):
                cond = p.parse_or()
                p.expect_end()
                node = ["if", line, cond, self.body(b), None, "elif"]
                tail[4] = [node]
                return None
            p.expect_end()
            tail[4] = self.body(b)
            return None
        if w == "if" and p.is_word("it", 1) and (p.is_word("fails", 2) or p.is_word("fail", 2) or p.is_word("failed", 2)):
            p.i += 3
            name = "problem"
            if p.accept_words("as"):
                name = p.peek()[1] if p.peek()[0] == "word" else None
                if name is None:
                    raise self.err(line, "expected a name after 'as'")
                p.i += 1
            p.expect_end()
            prev = out[-1] if out else None
            if prev is None or prev[0] != "try" or prev[3] is not None:
                raise self.err(line, "'if it fails:' must directly follow a 'try:' block")
            prev[3] = (name, self.body(b))
            self.features.add("try")
            return None
        if w == "always" and p.peek(1)[0] == "eof":
            prev = out[-1] if out else None
            if prev is None or prev[0] != "try" or prev[5] is not None:
                raise self.err(line, "'always:' must directly follow a 'try:' block")
            prev[5] = self.body(b)
            return None
        if w == "try" and p.peek(1)[0] == "eof":
            self.features.add("try")
            return ["try", line, self.body(b), None, None, None]
        if w == "if":
            p.i += 1
            cond = p.parse_or()
            p.expect_end()
            return ["if", line, cond, self.body(b), None]
        if w == "unless" and not self.simply:
            p.i += 1
            self.features.add("logic")
            cond = p.parse_or()
            p.expect_end()
            return ["if", line, ["not", cond], self.body(b), None]
        if w == "until" and not self.simply:
            p.i += 1
            self.features.add("logic")
            cond = p.parse_or()
            p.expect_end()
            return ["while", line, ["not", cond], self.body(b, loop=True)]
        if w == "while":
            p.i += 1
            cond = p.parse_or()
            p.expect_end()
            return ["while", line, cond, self.body(b, loop=True)]
        if w == "repeat":
            p.i += 1
            self.features.add("loop")
            if p.accept_words("forever"):
                p.expect_end()
                return ["repeat", line, None, self.body(b, loop=True)]
            n = p.parse_add()
            p.expect_word("times")
            p.expect_end()
            return ["repeat", line, n, self.body(b, loop=True)]
        if w == "for":
            p.i += 1
            self.features.add("loop")
            if p.accept_words("each") or p.accept_words("every"):
                name = self.decl(p, line, "loop")
                p.expect_word("in")
                p.elem_hint = name[1] if isinstance(name, list) else name
                it = p.parse_or()
                p.expect_end()
                return ["foreach", line, name, it, self.body(b, loop=True)]
            name = self.decl(p, line, "loop")
            p.expect_word("from")
            a = p.parse_add()
            p.expect_word("to")
            z = p.parse_add()
            step = None
            if p.accept_words("by") or p.accept_words("step"):
                step = p.parse_add()
            p.expect_end()
            return ["for", line, name, a, z, step, self.body(b, loop=True)]
        if w is not None and w.lower() == "simply" and p.peek(1)[0] == "eof":
            saved, self.simply = self.simply, True
            try:
                return ["simply", line, self.body(b)]
            finally:
                self.simply = saved
        if w is not None and w.lower() == "structurally" and p.peek(1)[0] == "eof":
            self.features.add("scope")
            saved, self.structural = self.structural, True
            try:
                return ["scope", line, self.body(b)]
            finally:
                self.structural = saved
        if w == "routine":
            p.i += 1
            name = self.name(p, line)
            p.expect_end()
            return ["routine", line, name, self.body(b, func=True)]
        if w == "define":
            p.i += 1
            self.features.add("define")
            name = self.name(p, line)
            params = []
            if p.accept_words("with"):
                while True:
                    params.append(self.decl(p, line, "param"))
                    if p.accept_op(",") or p.accept_words("and"):
                        continue
                    break
            p.expect_end()
            saved_loop, self.loop_depth = self.loop_depth, 0
            try:
                body = self.body(b, func=True)
            finally:
                self.loop_depth = saved_loop
            return ["define", line, name, params, body]
        if w == "action":
            p.i += 1
            if p.peek()[0] == "word":
                p.i += 1
            p.expect_end()
            return ["action", line, self.body(b)]
        raise self.err(line, f"I don't understand the block '{b.text}:'")

    def name(self, p, line):
        t = p.peek()
        if t[0] != "word":
            raise self.err(line, f"expected a name but found {p.describe()}")
        if t[1] in RESERVED:
            raise self.err(line, f"'{t[1]}' is a special word and cannot be used as a name")
        if not self.simply and t[1] in ARTICLES:
            raise self.err(line, f"'{t[1]}' is an article and cannot be used as a name; pick another name")
        if t[1].startswith("__"):
            raise self.err(line, f"names starting with '__' are reserved ('{t[1]}')")
        p.i += 1
        return t[1]

    def type_spec(self, p, line):
        """number | text | flag | value | table | pair | triple | quad | list [of numbers]  ->  type, or None if no type word follows"""
        t = p.peek()
        if t[0] != "word" or t[1] not in TYPE_NAMES:
            return None
        ty = TYPE_NAMES[t[1]]
        p.i += 1
        if ty == "value":
            return "value"
        if ty == "list":
            elem = None
            if p.is_word("of") and p.peek(1)[0] == "word" and p.peek(1)[1] in TYPE_NAMES:
                elem = TYPE_NAMES[p.peek(1)[1]]
                p.i += 2
                if elem == "list":
                    elem = ("list", None)
                elif elem == "value":
                    elem = None
            return ("list", elem)
        return ty

    def decl(self, p, line, mode="a"):
        """a bare name that a loop or a function parameter creates -> ['decl', name, None, mode]"""
        return ["decl", self.name(p, line), None, "simply" if self.simply else mode]

    def let_stmt(self, p, line, verb):
        """Let a number be called total   /   Create a number named total   /   Define a number as total
        Arrays: Create an array named|for scores   /   Define an array for scores   (with 10 slots: a fixed size)"""
        options = DECLARE_VERBS[verb]
        words = options[0]
        p.i += 1
        art = p.peek()
        if art[0] != "word" or art[1] not in ("a", "an"):
            raise self.err(line, f"say what you are making: '{verb.capitalize()} a number {' '.join(words)} total'")
        p.i += 1
        shared = p.accept_words("shared")             # Zoomy 5.5: Create a shared array named x with 100 slots
        t = p.peek()
        if shared and not (t[0] == "word" and t[1] == "array"):
            raise self.err(line, "only an array can be shared between workers (like: Create a shared array named board with 64 slots)")
        if t[0] != "word" or t[1] not in TYPE_NAMES:
            raise self.err(line, f"after '{art[1]}' I expected a kind of thing: number, index, string, array, flag, table, pair, triple, quad "
                                 f"or value (like: {verb.capitalize()} a number {' '.join(words)} total)")
        word = t[1]
        if word in PLURAL_TYPE_WORDS:
            raise self.err(line, f"'{art[1]}' goes with ONE thing: say '{art[1]} {SINGULAR_TYPE[word]}'")
        if art[1] != ("a" if shared else article_for(word)):
            soft(self.file, line, f"it is '{'a' if shared else article_for(word)} {'shared ' if shared else ''}{word}', not '{art[1]} {word}'")
        ty = self.type_spec(p, line)
        if isinstance(ty, tuple) and ty[0] == "list":
            if verb not in ARRAY_VERBS:
                raise self.err(line, "an array is made with 'Create an array named scores', 'Create an array for scores' "
                                     "or 'Define an array for scores' (there is no Let for arrays)")
            options = ARRAY_VERBS[verb]
            words = options[0]
        if not any(p.accept_words(*w) for w in options):
            say = " or ".join(" ".join(w) for w in options)
            raise self.err(line, f"after the kind of thing say {say} followed by the NAME (like: {verb.capitalize()} {art[1]} {word} {' '.join(words)} total)")
        n = p.peek()
        if n[0] != "word" or n[1] in RESERVED or n[1] in ARTICLES:
            raise self.err(line, f"expected a name but found {p.describe()}")
        name = self.name(p, line)
        slots = None
        if p.accept_words("with"):
            if ty != ("list", None) and not (isinstance(ty, tuple) and ty[0] == "list"):
                raise self.err(line, "only an array can have slots (like: Create an array named weights with 10 slots)")
            slots = p.parse_add()
            if not (p.accept_words("slots") or p.accept_words("slot")):
                raise self.err(line, "expected 'slots' (like: Create an array named weights with 10 slots)")
        if p.is_word("to"):
            raise self.err(line, f"making a variable and giving it a value are two statements: "
                                 f"'{verb.capitalize()} {art[1]} {word} {' '.join(words)} {name}' and then 'set {name} to ...'")
        p.expect_end()
        self.features.add("list" if isinstance(ty, tuple) else "logic")
        if shared:
            if slots is None:
                raise self.err(line, "a shared array needs a size (like: Create a shared array named board with 64 slots)")
            return ["let", line, name, ty, slots, "shared"]
        return ["let", line, name, ty, slots]

    def workers_stmt(self, p, line):
        """start 8 workers and store my worker number in id   (Zoomy 5.5)
        Every worker runs the lines after this one; worker 0 is the original program."""
        p.i += 1
        n = p.parse_add()
        if not (p.accept_words("workers") or p.accept_words("worker")):
            raise self.err(line, "expected 'workers' (like: start 8 workers and store my worker number in id)")
        p.expect_word("and")
        p.expect_word("store")
        p.expect_word("my")
        p.expect_word("worker")
        p.expect_word("number")
        p.expect_word("in")
        target = self.place(p, line)
        p.expect_end()
        self.features.add("workers")
        return ["workers", line, n, target]

    # -- Zoomy 5.5: integer mode and the bitwise statements
    def numtype_stmt(self, p, line):
        """from now on, use integers instead of floats   /   from now on, use floats instead of integers"""
        p.i += 2
        p.expect_word("on")
        p.accept_op(",")
        p.expect_word("use")
        t = p.peek()
        kinds = {"integers": "int", "integer": "int", "ints": "int", "floats": "float", "float": "float",
                 "uints": "uint", "unsigned": "uint", "big": "big", "bignum": "big", "bignums": "big", "bigint": "big",
                 "bigints": "big", "biginteger": "big", "bigintegers": "big", "bignumber": "big", "bignumbers": "big",
                 "bigdecimal": "bigdec", "bigdecimals": "bigdec", "bigdec": "bigdec", "bigdecs": "bigdec"}

        def kind_word():
            t = p.peek()
            if t[0] == "word" and t[1].lower() in kinds:
                t = (t[0], t[1].lower(), t[2])
            if t[0] != "word" or t[1] not in kinds:
                raise self.err(line, "say which numbers to use: 'from now on, use integers instead of floats' "
                                     "(or 'use unsigned integers instead of floats', 'use Big Numbers instead of floats', or 'use Big Decimals instead of floats')")
            p.i += 1
            k = kinds[t[1]]
            if t[1] == "big" and p.peek()[0] == "word" and p.peek()[1].lower() in ("decimals", "decimal", "decs"):
                p.i += 1
                k = "bigdec"
            elif t[1] == "big" and p.peek()[0] == "word" and p.peek()[1].lower() in ("numbers", "number", "integers", "integer", "ints", "nums"):
                p.i += 1
            if t[1] == "unsigned" and p.peek()[0] == "word" and p.peek()[1] in ("integers", "integer", "ints"):
                p.i += 1
            return k
        kind = kind_word()
        if p.accept_words("instead"):
            p.expect_word("of")
            if kind_word() == kind:
                raise self.err(line, "say it like: 'from now on, use integers instead of floats' (or floats instead of integers, "
                                     "or unsigned integers instead of integers)")
        p.expect_end()
        return ["numtype", line, kind]

    def vector_stmt(self, p, line, w, nw):
        """vector add items I of A and items J of B into items K of C      (also subtract, and, or, xor)
           vector sum items I of A into x
        Four numbers at a time (integer mode).  It means exactly the four ordinary statements, one per lane, so every backend
        runs it; the native backend turns it into one AVX2 instruction sequence when it can.  The three groups of four slots
        must be the same slots or not overlap at all."""
        if w != "vector":
            return None
        p.i += 1
        t = p.peek()
        if t[0] != "word" or t[1] not in ("add", "subtract", "and", "or", "xor", "sum"):
            raise self.err(line, "after 'vector' say add, subtract, and, or, xor or sum (like: vector add items 0 of a and items 4 of b into items 8 of c)")
        op = t[1]
        p.i += 1

        def group():
            p.expect_word("items")
            pos = p.parse_add()
            p.expect_word("of")
            arr = p.parse_postfix()
            if arr[0] != "var":
                raise self.err(line, "name an array after 'of' (like: items 0 of scores)")
            if pos[0] not in ("num", "var"):
                raise self.err(line, "give the first slot as a number or a variable (like: items 0 of scores, or items i of scores)")
            return arr, pos

        def lane(g, n):
            arr, pos = g
            if pos[0] == "num":
                return ["index", arr, ["num", pos[1] + n]]
            return ["index", arr, pos if n == 0 else ["bin", "plus", pos, ["num", float(n)]]]
        self.features.add("list")
        if op == "sum":
            g = group()
            p.expect_word("into")
            target = self.place(p, line)
            p.expect_end()
            e = ["bin", "plus", ["bin", "plus", lane(g, 0), lane(g, 1)], ["bin", "plus", lane(g, 2), lane(g, 3)]]
            return ["if", line, ["bool", True], [["set", line, target, e]], None, "vec", ("sum", g, target)]
        ga = group()
        p.expect_word("and")
        gb = group()
        p.expect_word("into")
        gc = group()
        p.expect_end()
        sets = []
        for n in range(4):
            x, y = lane(ga, n), lane(gb, n)
            e = ["bin", "plus", x, y] if op == "add" else ["bin", "minus", x, y] if op == "subtract" else ["bitop", op, x, y]
            sets.append(["set", line, lane(gc, n), e])
        if op in ("and", "or", "xor"):
            self.features.add("bits")
        return ["if", line, ["bool", True], sets, None, "vec", (op, ga, gb, gc)]

    def bit_stmt(self, p, line, w, nw):
        """shift x left by 8 bits / bitwise and x with y / count set bits of x / ...  They all become
        'set x to <bit operation>', so every kind of place (variable, array item) works."""
        def expr_of(place):
            return place

        def count_of(op):
            return p.parse_add()

        def finish(target, op, a, b):
            p.expect_end()
            self.features.add("bits")
            return ["set", line, target, ["bitop", op, a, b]]

        def bits_word():
            if not (p.accept_words("bits") or p.accept_words("bit")):
                raise self.err(line, "expected 'bits' (like: shift x left by 8 bits)")
        if w in ("shift", "rotate") and p.peek(1)[0] == "word":
            p.i += 1
            target = self.place(p, line)
            if p.accept_words("left"):
                d = "l"
            elif p.accept_words("right"):
                d = "r"
            else:
                raise self.err(line, f"say which way: '{w} x left by 8 bits' or '{w} x right by 8 bits'")
            p.expect_word("by")
            n = p.parse_add()
            bits_word()
            op = {("shift", "l"): "shl", ("shift", "r"): "shr", ("rotate", "l"): "rol", ("rotate", "r"): "ror"}[(w, d)]
            return finish(target, op, target, n)
        if w in ("arithmetic", "logical") and nw == "shift":
            # logical shift x left/right by n bits   (zeros come in, like plain 'shift')
            # arithmetic shift x right by n bits     (the sign bit is copied in); arithmetic left is the same as logical left
            p.i += 2
            target = self.place(p, line)
            if p.accept_words("left"):
                op = "shl"
            elif p.accept_words("right"):
                op = "sar" if w == "arithmetic" else "shr"
            else:
                raise self.err(line, f"say which way: '{w} shift x left by 8 bits' or '{w} shift x right by 8 bits'")
            p.expect_word("by")
            n = p.parse_add()
            bits_word()
            return finish(target, op, target, n)
        if w == "bitwise" and p.peek(1)[0] == "word":
            p.i += 1
            t = p.peek()
            if t[1] == "not":
                p.i += 1
                target = self.place(p, line)
                return finish(target, "not", target, None)
            if t[1] not in ("and", "or", "xor", "andnot"):
                raise self.err(line, "after 'bitwise' say and / or / xor / not (like: bitwise and x with y)")
            p.i += 1
            op = t[1]
            if op == "and" and p.accept_words("not"):
                op = "andnot"
            target = self.place(p, line)
            p.expect_word("with")
            val = p.parse_add()
            return finish(target, op, target, val)
        if w in ("extract", "deposit") and (nw == "bits" or (nw == "the" and p.is_word("bits", 2))):
            # extract bits of x using mask m [store in y]   -> PEXT: the bits of x chosen by the mask, packed to the bottom
            # deposit bits of x using mask m [store in y]   -> PDEP: the low bits of x spread out to where the mask has ones
            if nw == "bits":
                raise self.err(line, f"write '{w} the bits of ...' (tools/migrate.py converts old programs)")
            p.i += 3
            p.expect_word("of")
            src = self.place(p, line)
            p.expect_word("using")
            p.accept_words("the")
            p.accept_words("mask")
            mask = p.parse_add()
            dst = src
            if p.accept_store_in():
                dst = self.place(p, line)
            return finish(dst, "pext" if w == "extract" else "pdep", src, mask)
        src_ops = ((("count", "set", "bits"), "popcnt"), (("count", "trailing", "zeros"), "tzcnt"), (("count", "trailing", "zeroes"), "tzcnt"),
                   (("trailing", "zeros"), "tzcnt"), (("trailing", "zeroes"), "tzcnt"),
                   (("count", "leading", "zeros"), "lzcnt"), (("count", "leading", "zeroes"), "lzcnt"),
                   (("leading", "zeros"), "lzcnt"), (("leading", "zeroes"), "lzcnt"),
                   (("isolate", "lowest", "bit"), "lowbit"), (("clear", "lowest", "bit"), "clearlow"), (("reverse", "bytes"), "bswap"))
        for words, op in src_ops:
            k = 1 if (words[0] in ("count", "isolate", "clear", "reverse") and p.is_word("the", 1)) else 0    # 'count the set bits of x'
            if all(p.is_word(x, j + k if j else 0) for j, x in enumerate(words)) and p.is_word("of", len(words) + k):
                if not k:
                    full = words if words[0] in ("count", "isolate", "clear", "reverse") else ("count",) + words
                    new = " ".join((full[0], "the") + full[1:])
                    raise self.err(line, f"write '{new} of ...' (tools/migrate.py converts old programs)")
                p.i += len(words) + k + 1
                src = self.place(p, line)
                dst = src
                if p.accept_store_in():
                    dst = self.place(p, line)
                return finish(dst, op, src, None)
        if w in ("set", "clear", "flip") and nw == "bit" and p.peek(2)[0] != "eof" and not (p.peek(2)[1] == "to"):
            p.i += 2
            n = p.parse_add()
            p.expect_word("of")
            target = self.place(p, line)
            return finish(target, {"set": "setbit", "clear": "clearbit", "flip": "flipbit"}[w], target, n)
        return None

    def make_stmt(self, p, line):
        """make total a global number   /   make scores a global array of numbers   /   make grid a global array with 9 slots
        A global variable lives for the whole program: every function and block can see it, wherever it is made."""
        p.i += 1
        n = p.peek()
        if n[0] != "word" or n[1] in RESERVED or n[1] in ARTICLES:
            raise self.err(line, f"after 'make' put the name: 'make total a global number' (found {p.describe()})")
        name = self.name(p, line)
        art = p.peek()
        if art[0] != "word" or art[1] not in ("a", "an"):
            raise self.err(line, f"say what '{name}' is: 'make {name} a global number'")
        p.i += 1
        if not p.accept_words("global"):
            raise self.err(line, f"'make' is for global variables: 'make {name} {art[1]} global number'. "
                                 f"For an ordinary variable say 'Let a number be called {name}'")
        t = p.peek()
        if t[0] != "word" or t[1] not in TYPE_NAMES:
            raise self.err(line, f"after 'global' I expected a kind of thing: number, string, array, flag, table, pair, triple, quad "
                                 f"or value (like: make {name} a global number)")
        word = t[1]
        if word in PLURAL_TYPE_WORDS:
            raise self.err(line, f"'{art[1]}' goes with ONE thing: say '{art[1]} global {SINGULAR_TYPE[word]}'")
        if art[1] != article_for("global"):
            raise self.err(line, f"it is 'a global {word}': the article goes with 'global', not with '{word}'")
        ty = self.type_spec(p, line)
        slots = None
        if p.accept_words("with"):
            if not (isinstance(ty, tuple) and ty[0] == "list"):
                raise self.err(line, f"only an array can have slots (like: make {name} a global array with 10 slots)")
            slots = p.parse_add()
            if not (p.accept_words("slots") or p.accept_words("slot")):
                raise self.err(line, "expected 'slots' (like: make grid a global array with 10 slots)")
        if p.is_word("to"):
            raise self.err(line, f"making a variable and giving it a value are two statements: 'make {name} a global number' "
                                 f"and then 'set {name} to ...'")
        p.expect_end()
        self.features.add("list" if isinstance(ty, tuple) else "logic")
        return ["let", line, name, ty, slots, "global"]

    def cont(self, p):
        p.no_at = getattr(p, "no_at", 0) + 1
        try:
            return p.parse_postfix()
        finally:
            p.no_at -= 1

    def place(self, p, line, decl_ok=True):
        if not self.simply:
            t = p.peek()
            if t[0] == "word" and t[1] in ("a", "an") and (p.peek(1)[0] == "word" and (p.peek(1)[1] in TYPE_NAMES or p.peek(1)[1] in TUPLE_SIZES or p.peek(1)[1] == "shared"
                                                                     or (p.peek(1)[1] not in RESERVED and p.peek(1)[1] not in ("to", "by", "from", "in", "at", "into", "of", "with", "and", "as")))):
                raise self.err(line, f"'{t[1]}' is for making a new variable, and that is its own statement: "
                                     f"'Let a number be called total', then 'set the total to 0'. Here, name a variable that exists")
        e = p.parse_postfix()
        if e[0] == "fn" and e[1] == "first" and not self.simply:             # set the first of the pair to 9
            e = ["index", e[2][0], ["num", 0.0]]
        if e[0] not in ("var", "attr", "index"):
            raise self.err(line, "this must be a variable (or an item of a list or table) that can hold a value")
        if e[0] == "var":
            if e[1] in RESERVED:
                raise self.err(line, f"'{e[1]}' is a special word and cannot be used as a name")
            if e[1].startswith("__"):
                raise self.err(line, f"names starting with '__' are reserved ('{e[1]}')")
            if self.simply:
                return ["decl", e[1], None, "simply"]
        return e

    def has_to_file(self, p):
        depth = 0
        for k in range(p.i, len(p.t) - 1):
            kind, v, _ = p.t[k]
            if kind == "op" and v in "([":
                depth += 1
            elif kind == "op" and v in ")]":
                depth -= 1
            elif depth == 0 and kind == "word" and v == "to" and p.t[k + 1][0] == "word" and p.t[k + 1][1] == "file":
                return k
        return None

    # -- Zoomy 5: a question line prints its answer ---------------------------------------
    def question(self, p, line):
        """Is x above 3?   Are scores empty?   Does text contain "a"?   What is the largest of scores?
        How many scores are above 80?   How many items are in scores?   How long is name?   Where is 5 in scores?"""
        p.i += 1
        toks = p.t
        verb = p.peek()[1] if p.peek()[0] == "word" else None

        def subject():
            p.no_at = getattr(p, "no_at", 0) + 1
            try:
                s0 = p.i
                p.parse_add()
                return s0, p.i
            finally:
                p.no_at -= 1

        def expect_be():
            if not (p.accept_words("is") or p.accept_words("are")):
                raise self.err(line, "after that, say 'is' or 'are' (like: How many scores are above 80?)")

        W = lambda w: ("word", w, True)
        if verb in ("is", "are"):
            p.i += 1
            s0, s1 = subject()
            new = toks[s0:s1] + [W(verb)] + toks[s1:]
        elif verb in ("does", "do"):
            p.i += 1
            s0, s1 = subject()
            vt = toks[s1]
            new = toks[s0:s1] + [W({"contain": "contains", "start": "starts", "end": "ends"}.get(vt[1], vt[1]))] + toks[s1 + 1:]
        elif verb == "what":
            p.i += 1
            expect_be()
            new = toks[p.i:]
        elif verb == "where":
            p.i += 1
            expect_be()
            new = [W("position"), W("of")] + toks[p.i:]
        elif verb == "how" and p.is_word("many", 1):
            p.i += 2
            s0, s1 = subject()
            expect_be()
            if p.accept_words("in") or p.accept_words("inside"):
                new = [W("length"), W("of")] + toks[p.i:]
            else:
                new = [W("length"), W("of")] + toks[s0:s1] + [W("that"), W("are")] + toks[p.i:]
        elif verb == "how" and p.is_word("long", 1):
            p.i += 2
            expect_be()
            new = [W("length"), W("of")] + toks[p.i:]
        else:
            raise self.err(line, "I can answer: Is/Are ... ?   Does/Do ... contain ... ?   What is ... ?   How many ... ?   How long is ... ?   Where is ... in ... ?")
        p.t, p.i = new, 0
        val = p.parse_or()
        p.expect_end()

        def no_agreement(e):                    # a question is the user's own wording: don't nag about is/are
            if isinstance(e, list) and e:
                if e[0] == "cmp" and len(e) > 4:
                    e[4] = None
                elif e[0] == "is" and len(e) > 4:
                    e[4] = None
                for c in e[1:]:
                    if isinstance(c, list):
                        no_agreement(c)
        no_agreement(val)
        self.features.add("text")
        return ["print", line, True, [["val", val]]]

    # -- simple statements ------------------------------------------------------------
    def simple(self, b, p, w):
        line = b.line
        if w is None:
            e = p.parse_or()
            p.expect_end()
            return ["exprstmt", line, e]
        nxt = p.peek(1)
        nw = nxt[1] if nxt[0] == "word" else None
        if w == "__question":
            return self.question(p, line)
        if w == "warn" and nw == "with":
            p.i += 2
            e = p.parse_or()
            p.expect_end()
            return ["warn", line, e]
        if (not self.simply and w is not None and w.lower() in DECLARE_VERBS and nw in ("a", "an")):
            return self.let_stmt(p, line, w.lower())
        if not self.simply and w is not None and w.lower() == "make" and nxt[0] == "word" and nw not in ("sure", "certain"):
            return self.make_stmt(p, line)
        if w in ARITH_VERBS and nxt[0] != "eof":
            r = self.arith(b, p)
            if r is not None:
                return r
        if w == "convert":
            return self.convert_stmt(b, p)
        if w == "from" and nw == "now":
            return self.numtype_stmt(p, line)
        r = self.vector_stmt(p, line, w, nw)
        if r is not None:
            return r
        r = self.bit_stmt(p, line, w, nw)
        if r is not None:
            return r
        if w == "set" and nxt[0] == "word":
            p.i += 1
            target = self.place(p, line)
            p.expect_word("to")
            val = p.parse_or()
            if not self.simply and p.is_op(","):                       # set the scores to 70, 85, 90
                items = [val]
                while p.accept_op(","):
                    items.append(p.parse_or())
                val = ["list", items, "bare"]
                self.features.add("list")
            p.expect_end()
            return ["set", line, target, val]
        if w in ("add", "subtract") and nxt[0] != "eof":
            p.i += 1
            val = p.parse_or()
            p.expect_word("to" if w == "add" else "from")
            target = self.place(p, line)
            p.expect_end()
            return ["aug", line, "add" if w == "add" else "sub", val, target]
        if w == "add" or w == "append":
            pass
        if w in ("multiply", "divide") and nxt[0] != "eof":
            p.i += 1
            target = self.place(p, line)
            p.expect_word("by")
            val = p.parse_or()
            p.expect_end()
            return ["aug", line, "mul" if w == "multiply" else "div", val, target]
        if w == "calculate":
            p.i += 1
            had_the = False
            if p.is_word("the"):                                 # calculate the absolute value of x ... (also under 'Simply,')
                w1, w2 = (p.peek(1)[1] if p.peek(1)[0] == "word" else None), (p.peek(2)[1] if p.peek(2)[0] == "word" else None)
                if (w1, w2) in OF2_OPS or (w1 in OF_OPS and w2 == "of"):
                    p.i += 1
                    had_the = True
            w1 = p.peek()[1] if p.peek()[0] == "word" else None
            w2 = p.peek(1)[1] if p.peek(1)[0] == "word" else None
            if not had_the and ((w1, w2) in OF2_OPS or (w1 in OF_OPS and w2 == "of")):
                phrase = f"{w1} {w2}" if (w1, w2) in OF2_OPS else w1
                raise self.err(line, f"write 'calculate the {phrase} of ...' (tools/migrate.py converts old programs)")
            e = p.parse_or()
            p.expect_store_in()
            target = self.place(p, line)
            p.expect_end()
            return ["calc", line, e, target]
        if w == "allocate" and nw == "array":
            if not self.simply:
                raise self.err(line, "arrays are made with: Create an array named weights with 10 slots")
            p.i += 2
            name = self.decl(p, line)
            p.expect_word("with")
            n = p.parse_add()
            if not (p.accept_words("slots") or p.accept_words("slot")):
                raise self.err(line, "expected 'slots' (like: allocate array a with 10 slots)")
            p.expect_end()
            return ["alloc", line, name, n]
        if w == "store" and nxt[0] != "eof":
            p.i += 1
            val = p.parse_or()
            p.expect_word("in")
            cont = self.cont(p)
            p.expect_word("at")
            p.accept_words("index")
            key = p.parse_or()
            p.expect_end()
            return ["store", line, cont, key, val]
        if w == "put" and nxt[0] != "eof":
            p.i += 1
            self.features.add("list")
            val = p.parse_or()
            p.expect_word("in")
            cont = self.cont(p)
            p.expect_word("at")
            p.accept_words("index")
            key = p.parse_or()
            p.expect_end()
            return ["store", line, cont, key, val, "put"]
        if w == "load" and nw == "from":
            p.i += 2
            cont = self.cont(p)
            p.expect_word("at")
            p.accept_words("index")
            key = p.parse_or()
            p.expect_word("into")
            target = self.place(p, line)
            p.expect_end()
            return ["load", line, cont, key, target]
        if w == "open" and nw == "the" or w == "open" and nw == "file":
            p.i += 1
            p.accept_words("the")
            p.expect_word("file")
            if p.peek()[0] == "word" and p.peek()[1] == "named":
                p.i += 1
                p.expect_word("by")
                arr = p.parse_or()
                p.expect_word("for")
                p.expect_word("reading")
                p.expect_end()
                self.features.add("file")
                return ["openarr", line, arr]
            path = p.parse_or()
            p.expect_word("for")
            p.expect_word("reading")
            p.expect_end()
            self.features.add("file")
            return ["openf", line, path]
        if w == "move" and nw == "to" and p.peek(2)[0] == "word" and p.peek(2)[1] == "byte":
            p.i += 3
            pos = p.parse_or()
            p.expect_word("of")
            p.expect_word("the")
            p.expect_word("file")
            p.expect_end()
            self.features.add("file")
            return ["seekf", line, pos]
        if w == "close" and nw == "the":
            p.i += 2
            p.expect_word("file")
            p.expect_end()
            return ["closef", line]
        if w == "read":
            p.i += 1
            if p.is_word("file") and p.peek(1)[0] != "eof":
                p.i += 1
                path = p.parse_or()
                p.expect_word("into")
                target = self.place(p, line)
                p.expect_end()
                self.features.add("file")
                return ["readfile", line, path, target]
            if p.is_word("the") and p.is_word("file", 1) and p.is_word("size", 2) and p.is_word("into", 3):
                p.i += 4
                target = self.place(p, line)
                p.expect_end()
                self.features.add("file")
                return ["fsize", line, target]
            if p.is_word("the") and p.is_word("clock", 1) and p.is_word("into", 2):
                p.i += 3
                target = self.place(p, line)
                p.expect_end()
                return ["clock", line, target]
            if p.is_word("the") and p.is_word("core", 1) and p.is_word("count", 2) and p.is_word("into", 3):
                # read the core count into n : how many processor cores this program may run on (at least 1)
                p.i += 4
                target = self.place(p, line)
                p.expect_end()
                return ["clock", line, target, "cores"]
            if p.is_word("line") and p.is_word("into", 1):
                p.i += 2
                target = self.place(p, line)
                p.expect_end()
                self.features.add("text")
                return ["read", line, "line", target]
            kind = "num"
            for art in (("the", "next"), ("a",)):                  # read the next byte into c / read a character into c
                n = len(art)
                if all(p.is_word(x, j) for j, x in enumerate(art)) and (p.is_word("byte", n) or p.is_word("character", n)) and p.is_word("into", n + 1):
                    kind = "byte" if p.is_word("byte", n) else "char"
                    p.i += n + 2
                    target = self.place(p, line)
                    p.expect_end()
                    return ["read", line, kind, target]
            if (p.is_word("char") or p.is_word("byte")) and p.peek(1)[0] == "word":
                raise self.err(line, "write 'read the next byte into c' or 'read the next character into c' (tools/migrate.py converts old programs)")
            target = self.place(p, line)
            p.expect_end()
            return ["read", line, kind, target]
        if w == "tell" and p.is_word("me", 1) and p.is_word("a", 2) and p.is_word("story", 3):
            p.i += 4
            p.expect_end()
            self.features.add("text")
            return ["print", line, True, [["val", ["str", [STORY]]]]]
        if w in ("print", "write"):
            p.i += 1
            if w == "write":
                k = self.has_to_file(p)
                if k is not None:
                    val = p.parse_or()
                    p.i = k + 2
                    path = p.parse_or()
                    p.expect_end()
                    self.features.add("file")
                    return ["writefile", line, "w", val, path]
            items = []
            if p.at_end():
                if w == "write":
                    raise self.err(line, "write what? (write needs something to write)")
                self.features.add("text")
                return ["print", line, True, items]
            while True:
                if p.is_word("char") and p.peek(1)[0] != "eof" and not (p.peek(1)[0] == "op" and p.peek(1)[1] == ","):
                    p.i += 1
                    items.append(["char", p.parse_or()])
                else:
                    items.append(["val", p.parse_or()])
                if p.accept_op(","):
                    continue
                break
            p.expect_end()
            return ["print", line, w == "print", items]
        if w == "append" and nxt[0] != "eof":
            p.i += 1
            k = self.has_to_file(p)
            self.features.add("list")
            val = p.parse_or()
            if k is not None:
                p.i = k + 2
                path = p.parse_or()
                p.expect_end()
                self.features.add("file")
                return ["writefile", line, "a", val, path]
            p.expect_word("to")
            target = p.parse_postfix()
            p.expect_end()
            return ["append", line, val, target]
        if w == "insert" and nxt[0] != "eof":
            p.i += 1
            self.features.add("list")
            val = p.parse_or()
            if not (p.accept_words("into") or p.accept_words("in")):
                raise self.err(line, "expected 'into' (like: insert 5 into numbers at 0)")
            target = self.cont(p)
            p.expect_word("at")
            idx = p.parse_or()
            p.expect_end()
            return ["insert", line, val, target, idx]
        if w == "remove" and nxt[0] != "eof":
            p.i += 1
            self.features.add("list")
            if p.is_word("item") and p.is_word("at", 1):
                p.i += 2
                idx = p.parse_add()
                p.expect_word("from")
                target = p.parse_postfix()
                p.expect_end()
                return ["removeat", line, idx, target]
            val = p.parse_or()
            p.expect_word("from")
            target = p.parse_postfix()
            p.expect_end()
            return ["remove", line, val, target]
        if w == "sort" and nxt[0] != "eof":
            p.i += 1
            self.features.add("list")
            target = p.parse_postfix()
            desc = p.accept_words("descending") or p.accept_words("backwards")
            p.accept_words("ascending")
            p.expect_end()
            return ["sort", line, target, bool(desc)]
        if w in ("reverse", "clear") and nxt[0] != "eof":
            p.i += 1
            self.features.add("list")
            target = p.parse_postfix()
            p.expect_end()
            return [w, line, target]
        if w == "start" and (nxt[0] == "num" or (nxt[0] == "word" and p.peek(2)[1] in ("workers", "worker"))):
            return self.workers_stmt(p, line)
        if w == "wait" and nw == "for" and p.peek(2)[0] == "word" and p.peek(2)[1] in ("the", "workers"):
            p.i += 2
            p.accept_words("the")
            if not (p.accept_words("workers") or p.accept_words("worker")):
                raise self.err(line, "say: wait for the workers")
            p.expect_end()
            return ["waitw", line]
        if w == "wait" and nxt[0] != "eof":
            p.i += 1
            self.features.add("fn")
            e = p.parse_add()
            if not (p.accept_words("seconds") or p.accept_words("second")):
                raise self.err(line, "expected 'seconds' (like: wait 2 seconds)")
            p.expect_end()
            return ["wait", line, e]
        if w == "delete" and nw == "file":
            p.i += 2
            self.features.add("file")
            e = p.parse_or()
            p.expect_end()
            return ["delete", line, e]
        if w == "stop" and nxt[0] == "eof":
            if not self.loop_depth:
                raise self.err(line, "'stop' can only be used inside a loop")
            self.features.add("loop")
            return ["stop", line]
        if w == "skip" and nxt[0] == "eof":
            if not self.loop_depth:
                raise self.err(line, "'skip' can only be used inside a loop")
            self.features.add("loop")
            return ["skip", line]
        if w == "give" and nw == "back":
            if not self.func_depth:
                raise self.err(line, "'give back' can only be used inside a 'define' block")
            p.i += 2
            self.features.add("define")
            e = None if p.at_end() else p.parse_or()
            p.expect_end()
            return ["return", line, e]
        if w == "finish":
            p.i += 1
            e = None
            if p.accept_words("with"):
                e = p.parse_or()
            p.expect_end()
            return ["finish", line, e]
        if w == "fail" and nw == "with":
            p.i += 2
            self.features.add("try")
            e = p.parse_or()
            p.expect_end()
            return ["fail", line, e]
        if w == "check" and nw == "that":
            p.i += 2
            self.features.add("try")
            e = p.parse_or()
            why = None
            if p.accept_words("because"):
                t = p.peek()
                if t[0] != "str" or not all(isinstance(x, str) for x in t[1]):
                    raise self.err(line, "'because' wants the reason as text in quotes (like: because \"total must be positive\")")
                why = "".join(t[1])
                p.i += 1
            p.expect_end()
            return ["check", line, e, why if why is not None else b.text[len("check that"):].strip()]
        if w == "call" and p.is_word("the", 1) and p.is_word("system", 2):
            # call the system with the phone number N [using A and B and ... up to 6 arguments] [and store the answer in x]
            # a raw Linux system call (integer mode); the answer is what the kernel gives back (a negative number is minus the error code)
            p.i += 3
            p.expect_word("with")
            p.accept_words("the")
            p.expect_word("phone")
            p.expect_word("number")
            num = p.parse_add()
            args = []
            if p.accept_words("using"):
                args.append(p.parse_add())
                while p._accept_and():
                    args.append(p.parse_add())
            if len(args) > 6:
                raise self.err(line, "a system call takes at most 6 arguments")
            target = None
            if p.accept_store_in():
                target = self.place(p, line)
            p.expect_end()
            self.features.add("file")
            return ["syscall", line, num, args, target]
        if w == "call":
            e = p.parse_or()
            if p.accept_store_in():
                target = self.place(p, line)
                p.expect_end()
                return ["callstore", line, e, target]
            p.expect_end()
            return ["exprstmt", line, e]
        if w == "run" and nw is not None:
            p.i += 1
            name = self.name(p, line)
            if p.accept_words("with"):
                arg = p.parse_or()
                p.expect_end()
                return ["runwith", line, name, arg]
            p.expect_end()
            return ["run", line, name]
        if w == "use":
            return self.use_stmt(p, line)
        if w == "global" and nxt[0] == "word":
            if not self.simply:
                raise self.err(line, "'global' is not a statement: a function can already change any variable declared outside it. To make a variable that lives for the whole program, wherever it is made, say: make total a global number")
            p.i += 1
            names = [self.name(p, line)]
            while p.accept_op(",") or p.accept_words("and"):
                names.append(self.name(p, line))
            p.expect_end()
            return ["global", line, names]
        if w == "extern" and nw is not None:
            p.i += 1
            name = self.name(p, line)
            p.expect_end()
            return ["extern", line, name]
        if w == "include":
            rest = b.text[len("include"):].strip()
            return ["include", line, rest]
        if w == "pass" and nxt[0] == "eof" or (w == "do" and nw == "nothing"):
            return ["pass", line]
        # a bare expression such as  greet("Bob")
        e = p.parse_or()
        p.expect_end()
        if e[0] != "call":
            raise self.err(line, f"I don't understand '{b.text}'")
        return ["exprstmt", line, e]

    # -- conversational pipelines:  set x to 10 and add 5 and multiply by 2
    def arith(self, b, p):
        line, toks = b.line, p.t
        cuts, depth = [0], 0
        for k, (kind, v, _) in enumerate(toks):
            if kind == "op" and v in "([":
                depth += 1
            elif kind == "op" and v in ")]":
                depth -= 1
            elif (depth == 0 and k > 0 and kind == "word" and v == "and" and toks[k + 1][0] == "word"
                  and toks[k + 1][1] in ARITH_VERBS):
                cuts.append(k)
        cuts.append(len(toks) - 1)
        if len(cuts) == 2 and toks[0][1] == "set":
            return None                                       # a plain 'set': handled by the ordinary path
        out, subject = [], None
        for j in range(len(cuts) - 1):
            lo = cuts[j] + (1 if j else 0)
            seg = toks[lo:cuts[j + 1]] + [("eof", None, False)]
            cp = Parser(seg, self.file, line, self.features, self.structural, self.simply)
            stmts, subject = self.clause(cp, line, subject, first=(j == 0))
            out += stmts
        if len(cuts) > 2:
            self.features.add("pipeline")
        return out if len(out) != 1 else out[0]

    def targets(self, p, line):
        places = [self.place(p, line, decl_ok=False)]
        while p.is_word("and") and p.peek(1)[0] == "word" and p.peek(1)[1] not in ARITH_VERBS | {"by", "to", "from"}:
            p.i += 1
            places.append(self.place(p, line, decl_ok=False))
            self.features.add("multi")
        return places

    def clause(self, p, line, subject, first):
        verb = p.peek()[1]
        p.i += 1
        stmts = []
        if verb == "set":
            target = self.place(p, line)
            p.expect_word("to")
            val = p.parse_or()
            p.expect_end()
            return [["set", line, target, val]], (["var", target[1]] if target[0] == "decl" else target)
        opname = {"add": "add", "subtract": "sub", "multiply": "mul", "divide": "div"}[verb]
        joiner = {"add": "to", "subtract": "from"}.get(verb)
        if joiner:                                            # add VALUE [to TARGETS]
            val = p.parse_add()
            if p.accept_words(joiner):
                targets = self.targets(p, line)
            else:
                targets = self.elided(subject, verb, line)
                self.features.add("pipeline")
        else:                                                 # multiply [TARGETS] by VALUE
            if p.is_word("by"):
                targets = self.elided(subject, verb, line)
                self.features.add("pipeline")
            else:
                targets = self.targets(p, line)
            p.expect_word("by")
            val = p.parse_add()
        p.expect_end()
        for t in targets:
            stmts.append(["aug", line, opname, val, t])
        return stmts, (targets[0] if len(targets) == 1 else None)

    def elided(self, subject, verb, line):
        if subject is None:
            raise self.err(line, f"'{verb}' needs to know what to change: start the line with 'set x to ...', "
                                 f"or name the variable (like: {verb} 5 {'to' if verb == 'add' else 'from' if verb == 'subtract' else 'by'} x)")
        return [subject]

    def convert_stmt(self, b, p):
        line = b.line
        p.i += 1
        self.features.add("convert")
        had_the = p.accept_words("the")                          # convert the number 101 to ASCII ...
        what = p.peek()[1] if p.peek()[0] == "word" else None
        if what in ("character", "number") and not had_the:
            raise self.err(line, f"write 'convert the {what} ...' (tools/migrate.py converts old programs)")
        if what not in ("character", "number"):
            raise self.err(line, "expected: convert the character X to a number and store the result in Y   (or: convert the number X to ASCII and store the result in Y)")
        p.i += 1
        val = p.parse_add()
        p.expect_word("to")
        if what == "character":
            if not (p.accept_words("a", "number") or p.accept_words("number")):
                raise self.err(line, "expected 'to a number'")
        elif not (p.accept_words("ASCII") or p.accept_words("a", "character") or p.accept_words("a", "letter")):
            raise self.err(line, "expected 'to ASCII'")
        p.expect_store_in()
        target = self.place(p, line)
        p.expect_end()
        return ["convert", line, what, val, target]

    def use_stmt(self, p, line):
        p.i += 1
        self.features.add("python")

        def module():
            if not p.accept_words("python"):
                raise self.err(line, "expected python's <library> (like: use python's math)")
            if not p.accept_op("'s"):
                raise self.err(line, "expected 's after python (like: use python's math)")
            parts = []
            while True:
                t = p.peek()
                if t[0] != "word":
                    raise self.err(line, "expected a python library name")
                parts.append(t[1])
                p.i += 1
                if p.is_op(".") and p.peek(1)[0] == "word":
                    p.i += 1
                    continue
                break
            return ".".join(parts)
        if p.is_word("python"):
            mod = module()
            alias = mod.split(".")[0] if "." not in mod else mod.split(".")[-1]
            if p.accept_words("as"):
                alias = self.name(p, line)
            p.expect_end()
            return ["use", line, mod, alias]
        names = []
        while True:
            names.append(self.name(p, line))
            if p.accept_op(",") or p.accept_words("and"):
                continue
            break
        p.expect_word("from")
        mod = module()
        p.expect_end()
        return ["usefrom", line, mod, names]


# =============================================================================
# Program loading (includes) and analysis
# =============================================================================
_DECL_RE = re.compile(r"^(?:let|create|define)\s+(?:a|an)\s+.*?\b(?:called|named|for|as)\s+([A-Za-z_]\w*)\s*$", re.I)
_MAKE_RE = re.compile(r"^make\s+([A-Za-z_]\w*)\s+a\s+global\b", re.I)
_DEFN_RE = re.compile(r"^(?:define|routine)\s+([A-Za-z_]\w*)\b", re.I)
_ALIAS_RE = re.compile(r"^(\s*include\s+.*?)\s+as\s+([A-Za-z_]\w*)\s*$", re.I)


def top_level_names(text, filename="<lib>"):
    """names a file defines at its top level: routines, functions, global and top-level variables (not those of files it includes)"""
    names = set()
    for line in text.split("\n"):
        if not line.strip() or line[0] in " \t":
            continue                                          # only lines that start at the left edge are top level
        try:
            sents = zs.normalize(strip_comment(line))
        except Exception:
            continue
        for depth, sent in sents:
            if depth != 0:
                continue
            t = sent.strip().rstrip(":").strip()
            for rx in (_DECL_RE, _MAKE_RE, _DEFN_RE):
                m = rx.match(t)
                if m:
                    names.add(m.group(1))
    return names


def _map_code(text, fn_code):
    """apply fn_code to the code parts of a program: everything except comments and the literal parts of "text" (the {expressions} inside text count as code)"""
    out, i, n, buf = [], 0, len(text), []
    def flush():
        if buf:
            out.append(fn_code("".join(buf)))
            buf.clear()
    while i < n:
        c = text[i]
        if c == '"':
            flush()
            j, lit, depth = i + 1, ['"'], 0
            while j < n and text[j] != "\n":
                d = text[j]
                if d == "\\" and j + 1 < n:
                    lit.append(text[j:j + 2]); j += 2; continue
                if d == "{" and depth == 0:
                    out.append("".join(lit)); lit = []
                    depth = 1; j += 1; code = []
                    while j < n and depth and text[j] != "\n":
                        if text[j] == "{": depth += 1
                        if text[j] == "}":
                            depth -= 1
                            if depth == 0: break
                        code.append(text[j]); j += 1
                    out.append("{" + fn_code("".join(code)) + "}"); j += 1; depth = 0
                    continue
                lit.append(d); j += 1
                if d == '"':
                    break
            out.append("".join(lit)); i = j
            continue
        if c == "\n":
            buf.append(c)
        else:
            buf.append(c)
        i += 1
    flush()
    return "".join(out)


def rename_words(text, mapping):
    """whole-word renames of names in code (not in comments written as lines of their own, not in text literals)"""
    if not mapping:
        return text
    rx = re.compile(r"(?<![\w'])(" + "|".join(sorted(map(re.escape, mapping), key=len, reverse=True)) + r")(?!\w)")
    out = []
    for line in text.split("\n"):
        if line.strip().startswith("(") and line.strip().endswith(")"):
            out.append(line)                                       # a comment on a line of its own
        else:
            out.append(_map_code(line, lambda c: rx.sub(lambda m: mapping[m.group(1)], c)))
    return "\n".join(out)


def apply_aliases(text, aliases):
    """`m's name` and `m.name` -> `m_name` for every alias m made by `include ... as m`"""
    if not aliases:
        return text
    a = "|".join(map(re.escape, aliases))
    rx = re.compile(r"(?<![\w'])(" + a + r")(?:'s\s+|\.)([A-Za-z_]\w*)")
    out = []
    for line in text.split("\n"):
        if _ALIAS_RE.match(line) or (line.strip().startswith("(") and line.strip().endswith(")")):
            out.append(line)
        else:
            out.append(_map_code(line, lambda c: rx.sub(lambda m: m.group(1) + "_" + m.group(2), c)))
    return "\n".join(out)


def _lib_hint(dirs, rel):
    """'. Did you mean ...' from the library files that do exist"""
    import difflib
    head, _, tail = rel.rpartition("/")
    have = {}
    for base in dirs:
        d = os.path.join(base, head) if head else base
        try:
            for nm in os.listdir(d):
                if nm.lower().endswith((".zmy", ".zmy.txt")):
                    have.setdefault(nm.split(".")[0].lower(), (head + "/" if head else "") + nm.split(".")[0])
        except OSError:
            pass
    near = difflib.get_close_matches(tail.lower(), list(have), n=1, cutoff=0.6)
    return f". Did you mean '{have[near[0]]}'?" if near else ""


def resolve_lib(search_dirs, rel):
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


class Program:
    def __init__(self, filename):
        self.file = filename
        self.features = set()
        self.stmts = []              # top level
        self.included = set()
        self.def_origin = {}
        self.why_not = None                  # (line, kind) of the first statement the native compiler could not take
        self.native_ok = True
        self.ints = False            # Zoomy 5.5: 64-bit integers instead of floats
        self.uns = False             # Zoomy 5.6: unsigned 64-bit integers
        self.big = False             # Zoomy 7: Big Numbers, 1024-bit integers
        self.big_native_ok = False
        self.bd = False              # Zoomy 7: Big Decimals
        self.ints_cli = None         # "int" / "float" / "uint" when --ints / --floats / --unsigned was given
        self.numtype_seen = None     # what the file itself says: "int" / "float" / "uint" (None: nothing)

    # -- loading
    def load(self, path, main_dir=None):
        import zoomy_grammar
        global BIG_MODE, DEC_MODE
        BIG_MODE = DEC_MODE = False
        self.res = zoomy_grammar.Resolver(path)
        main_dir = main_dir or os.path.dirname(os.path.abspath(path))
        self.main_dir = main_dir
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.included.add((os.path.abspath(path), None))
        self.stmts = self._load_text(text, path, os.path.dirname(os.path.abspath(path)))
        self._finish()
        return self

    def load_text(self, text, name="<text>"):
        import zoomy_grammar
        global BIG_MODE, DEC_MODE
        BIG_MODE = DEC_MODE = False
        self.res = zoomy_grammar.Resolver(name)
        self.main_dir = os.getcwd()
        self.stmts = self._load_text(text, name, self.main_dir)
        self._finish()
        return self

    def _load_text(self, text, path, file_dir):
        global BIG_MODE, DEC_MODE
        if self.ints_cli == "bigdec" or re.search(r"(?im)^\s*from now on,?\s+use\s+(?:big\s+decimals?|big\s+decs?|bigdecimals?|bigdecs?)\b", text):
            DEC_MODE = True
        elif self.ints_cli == "big" or re.search(r"(?im)^\s*from now on,?\s+use\s+(?:big|bignums?|bigints?|biginteger|bignumbers?)\b", text):
            BIG_MODE = True
        aliases = [m.group(2) for m in map(_ALIAS_RE.match, text.split("\n")) if m]
        text = apply_aliases(text, aliases)
        front = Front(path, self.features)
        stmts = front.convert(parse_blocks(text, path))
        out = []
        saved = self.res.enter(path, stmts)
        out += self.res.take_init()                  # variables made with `make ... a global ...` start the program
        try:
            first = True
            for st in stmts:
                if st[0] == "numtype":
                    if not first:
                        raise ZoomyError("the kind of numbers must be chosen at the very top of the file, before any other line "
                                         "(the whole program uses one kind): 'from now on, use integers instead of floats'",
                                         path, st[1])
                    want = st[2]
                    if self.numtype_seen is not None and self.numtype_seen != want:
                        raise ZoomyError("two files ask for different kinds of numbers (integers, unsigned integers or floats); "
                                         "a program uses one kind", path, st[1])
                    self.numtype_seen = want
                    continue
                first = False
                if st[0] in ("routine", "define"):
                    seen = self.def_origin.setdefault(st[2], (path, st[1]))
                    if seen != (path, st[1]):
                        if seen[0] == path:
                            raise ZoomyError(f"'{st[2]}' is defined twice (the first one is on line {seen[1]})", path, st[1])
                        raise ZoomyError(f"'{st[2]}' is already defined in {os.path.basename(seen[0])} (line {seen[1]}); "
                                         f"two files cannot both define it - rename one of them", path, st[1])
                if st[0] == "include":
                    out += self._include(st, path, file_dir)
                else:
                    out += self.res.top(st)             # names, scopes and types are settled here (see zoomy_grammar)
        finally:
            self.res.leave(saved)
        return out

    def _include(self, st, path, file_dir):
        spec, line = st[2], st[1]
        alias = None
        am = re.fullmatch(r"(.*?)\s+as\s+([A-Za-z_]\w*)", spec, re.I)
        if am:
            spec, alias = am.group(1).strip(), am.group(2)
        m = re.fullmatch(r"([A-Za-z_]\w*)'s\s+([A-Za-z_]\w*)", spec)
        if m:
            rel = f"{m.group(1)}/{m.group(2)}"
        else:
            m = re.fullmatch(r'"([^"]+)"', spec) or re.fullmatch(r"([\w./]+)", spec)
            if not m:
                raise ZoomyError(f"cannot understand include '{spec}'", path, line)
            rel = m.group(1)
            if rel.endswith(".zmy"):
                rel = rel[:-4]
            rel = rel if '"' in spec else rel.replace('.', '/')
        dirs = [file_dir, self.main_dir, os.path.join(self.main_dir, "zoomy_modules")]
        dirs += [d for d in os.environ.get("ZOOMY_PATH", "").split(os.pathsep) if d]    # Zoomy 8: your own library folders
        dirs.append(HERE)
        dirs = list(dict.fromkeys(dirs))
        found = resolve_lib(dirs, rel)
        if found is None:
            raise ZoomyError(f"cannot find library '{rel}' (looked for {rel}.zmy and {rel}.zmy.txt in: "
                             + ", ".join(d for d in dirs if os.path.isdir(d)) + ")" + _lib_hint(dirs, rel), path, line)
        found = os.path.abspath(found)
        key = (found, alias)
        if key in self.included:
            return []
        self.included.add(key)
        with open(found, encoding="utf-8") as f:
            text = f.read()
        if alias:                                    # Zoomy 8: `include X as m` - the file's own names become m_name, used as `m's name`
            names = top_level_names(text, found)
            text = rename_words(text, {n: f"{alias}_{n}" for n in names})
        return self._load_text(text, found, os.path.dirname(found))

    # -- checks
    def _fold_constants(self):
        """pi, e, tau, c, G ... (see zoomy_consts.py) become plain numbers: whole numbers in integer mode"""
        import zoomy_consts
        for s in all_stmts(self.stmts):
            for e in stmt_exprs(s):
                def fold(x, line=s[1]):
                    if x[0] == "var" and x[1] in zoomy_consts.PY_NAMES:
                        if self.ints:
                            n = zoomy_consts.whole(x[1])
                            if n is None:
                                raise ZoomyError(f"the constant '{zoomy_consts.PY_NAMES[x[1]]}' is too large for 64-bit integers "
                                                 f"(use floats, or work with it as a float)", self.file, line)
                            x[:] = ["num", n]
                        elif self.bd:
                            import fractions
                            x[:] = ["num", fractions.Fraction(zoomy_consts.text(x[1]))]
                        else:
                            x[:] = ["num", zoomy_consts.value(x[1])]
                walk(e, fold)

    def _add_bd_math(self):
        """Zoomy 8: sine, cosine, tangent, arctangent, natural log and exp of a Big Decimal are calls of zoomy_bdmath.zmy
        (written in Zoomy, added to the program), so every backend runs the same steps and agrees bit for bit"""
        found = []
        for s in all_stmts(self.stmts):
            for e in stmt_exprs(s):
                walk(e, lambda x: found.append(x) if x[0] == "fn" and x[1] in BD_MATH else None)
        if not found:
            return
        for x in found:
            x[:] = ["call", ["var", BD_MATH[x[1]]], x[2], []]
        path = os.path.join(HERE, "zoomy_bdmath.zmy")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.stmts = self.stmts + self._load_text(text, path, HERE)

    def _decide_numbers(self):
        """integers or floats: the command line wins over the file; the default is floats"""
        cli = {True: "int", False: "float"}.get(self.ints_cli, self.ints_cli)
        mode = cli if cli is not None else (self.numtype_seen or "float")
        self.ints = mode not in ("float", "bigdec")
        self.uns = mode == "uint"
        self.big = mode == "big"
        self.bd = mode == "bigdec"                  # Zoomy 7: Big Decimals, 1024-bit binary floating point
        if self.bd:
            self._add_bd_math()
        self._fold_constants()
        bitops = []
        for s in all_stmts(self.stmts):
            for e in stmt_exprs(s):
                walk(e, lambda x: bitops.append(s[1]) if x[0] == "bitop" else None)
        lits = []
        for s in all_stmts(self.stmts):
            for e in stmt_exprs(s):
                walk(e, lambda x: lits.append((s[1], x)) if x[0] == "num" else None)
        for line, x in lits:
            if self.bd:
                pass                                       # Big Decimals keep every digit of a literal
            elif not self.ints and type(x[1]) is int:
                x[1] = float(x[1])
            elif self.big and type(x[1]) is int and not -(1 << 1023) <= x[1] < (1 << 1023):
                raise ZoomyError(f"{str(x[1])[:24]}... does not fit in a 1024-bit integer", self.file, line)
            elif self.big:
                pass
            elif self.uns and type(x[1]) is int and not -(1 << 63) <= x[1] < (1 << 64):
                raise ZoomyError(f"{x[1]} does not fit in an unsigned 64-bit integer", self.file, line)
            elif self.ints and not self.uns and type(x[1]) is int and not -(1 << 63) <= x[1] < (1 << 63):
                raise ZoomyError(f"{x[1]} does not fit in a 64-bit integer", self.file, line)
            elif self.uns and type(x[1]) is int and x[1] < 0:
                x[1] &= (1 << 64) - 1                  # a negative literal is its two's complement bit pattern
        if bitops and not self.ints:
            raise ZoomyError("bit operations work on integers: put 'from now on, use integers instead of floats' at the top "
                             "of the file (or build with --ints)", self.file, bitops[0])
        if self.ints:
            bad = []
            for s in all_stmts(self.stmts):
                for e in stmt_exprs(s):
                    walk(e, lambda x: bad.append((s[1], x[1])) if x[0] == "num" and x[1] != x[1] or
                         (x[0] == "num" and x[1] in (float("inf"), float("-inf"))) or
                         (x[0] == "num" and x[1] != int(x[1])) else None)
            if bad:
                raise ZoomyError(f"this program uses integers, but {bad[0][1]!r} is not a whole number "
                                 f"(write 'from now on, use floats instead of integers' at the top to use fractions)",
                                 self.file, bad[0][0])

    def _finish(self):
        self._decide_numbers()
        actions = [s for s in self.stmts if s[0] == "action"]
        top = [s for s in self.stmts if s[0] not in ("action", "routine", "define", "use", "usefrom", "extern")]
        if actions:                                  # variables made before the action are shared with it and with routines
            top = [s for s in top if s[0] not in ("set", "alloc")]
        if len(actions) > 1:
            raise ZoomyError("a program can have only one 'action' block", self.file, actions[1][1])
        if actions and top:
            raise ZoomyError("statements outside 'action start:' cannot be mixed with an 'action' block; "
                             "put them inside it (or remove the 'action' line)", self.file, top[0][1])
        if not actions and not top:
            raise ZoomyError("this program has nothing to run (add an 'action start:' block or some statements)", self.file)
        self.uses_extern = any(s[0] == "extern" for s in self.stmts)
        names = {}
        for s in self.stmts:
            if s[0] in ("routine", "define"):
                if s[2] in names:
                    raise ZoomyError(f"'{s[2]}' is defined twice", self.file, s[1])
                names[s[2]] = s
        self.funcs = names
        self.native_ok = self.native_ok and self._native_analysis() and self._native_block(self.stmts) and self._char_vars_ok()
        self.big_native_ok = (self.big or self.bd) and self.native_ok     # Big Numbers / Big Decimals: may be lowered onto the machine-code / WebAssembly compilers
        if self.big or self.bd:
            self.native_ok = False                                # (the compilers themselves only know 64-bit numbers)

    # -- is the program inside the native (number-only) subset?  Then it compiles to an ELF.
    NATIVE_BIN = {"plus", "minus", "times", "divide", "mod", "pow"}
    NATIVE_FN = {"sqrt", "abs", "floor", "ceil"}
    FLAG_KINDS = ("bool", "cmp", "and", "or", "not")

    def _native_analysis(self):
        """Facts the native check needs: fixed-size arrays, yes/no variables, which functions give a value back, and
        which arrays each function writes.  Returns False when the program mixes things the native compiler cannot keep apart."""
        self.n_arrays, self.n_flags, self.n_writes = {}, set(), {}
        allst = list(all_stmts(self.stmts))
        for s in allst:
            if s[0] == "alloc" and s[3][0] == "num" and s[3][1] == int(s[3][1]) and s[3][1] >= 1:
                if self.n_arrays.get(s[2], s[3][1]) != s[3][1]:
                    return False
                self.n_arrays[s[2]] = int(s[3][1])
        flags, other = set(), set()                             # yes/no names; names given anything else by a non-`set` statement
        sets = [s for s in allst if s[0] == "set" and s[2][0] == "var"]
        for s in allst:
            if s[0] in ("aug", "calc", "load", "read", "convert", "callstore", "foreach", "for", "readfile", "openf", "openarr", "clock", "fsize", "syscall"):
                other.update(assigned_names(s))
            elif s[0] == "define":
                other.update(s[3])
        changed = True                                          # a name is a yes/no name once it is given a yes/no value
        while changed:
            changed = False
            for s in sets:
                if s[2][1] not in flags and self._flag_expr(s[3], flags):
                    flags.add(s[2][1])
                    changed = True
        if flags & other or any(s[2][1] in flags and not self._flag_expr(s[3], flags) for s in sets):
            return False
        self.n_flags = flags
        # which arrays does each function write (directly or through what it calls)?
        direct, calls = {}, {}
        for f in (s for s in allst if s[0] in ("routine", "define")):
            body = f[3] if f[0] == "routine" else f[4]
            w, c = set(), set()
            for st in all_stmts(body):
                if st[0] == "store" and st[2][0] == "var":
                    w.add(st[2][1])
                for pl in ([st[2]] if st[0] == "set" else [st[4]] if st[0] == "aug" else []):
                    if pl[0] == "index" and pl[1][0] == "var":
                        w.add(pl[1][1])
                if st[0] == "run":
                    c.add(st[2])
                for e in stmt_exprs(st):
                    walk(e, lambda x: c.add(x[1][1]) if x[0] == "call" and x[1][0] == "var" else None)
            direct[f[2]], calls[f[2]] = w, c
        self.n_writes = {}
        for name in direct:
            seen, todo, acc = set(), [name], set()
            while todo:
                n = todo.pop()
                if n in seen or n not in direct:
                    continue
                seen.add(n)
                acc |= direct[n]
                todo += list(calls[n])
            self.n_writes[name] = acc
        return True

    def _flag_expr(self, e, flags=None):
        flags = self.n_flags if flags is None else flags
        return e[0] in self.FLAG_KINDS or (e[0] == "var" and e[1] in flags)

    def _returns_value(self, f):
        """a `define` whose body ends with `give back VALUE` (so a call to it can be used as a number)"""
        body = f[4]
        return bool(body) and body[-1][0] == "return" and body[-1][2] is not None and \
            all(s[2] is not None for s in all_stmts(body) if s[0] == "return")

    def _nx(self, e):
        k = e[0]
        if k == "num":
            return True
        if k == "var":
            return e[1] not in self.n_arrays
        if k == "bool":
            return True
        if k in ("cmp", "and", "or", "not"):
            return self._ncond(e)
        if k == "neg":
            return self._nx(e[1])
        if k == "bitop":
            return self._nx(e[2]) and (e[3] is None or self._nx(e[3]))
        if k == "bin":
            return e[1] in self.NATIVE_BIN and self._nx(e[2]) and self._nx(e[3])
        if k == "index":
            return e[1][0] == "var" and e[1][1] in self.n_arrays and self._nx(e[2])
        if k == "call":
            f = self.funcs.get(e[1][1]) if e[1][0] == "var" else None
            return (f is not None and f[0] == "define" and not e[3] and len(e[2]) == len(f[3]) and self._returns_value(f)
                    and all(self._nx(a) and not self._flag_expr(a) for a in e[2]))
        if k == "fn":
            if e[1] in self.NATIVE_FN or (self.bd and e[1] == "round"):
                return self._nx(e[2][0])
            if e[1] == "rem":
                return all(self._nx(a) for a in e[2])
            if e[1] in ("len", "first", "last"):
                return e[2][0][0] == "var" and e[2][0][1] in self.n_arrays
        return False

    def _ncond(self, c):
        k = c[0]
        if k == "cmp":
            return c[1] in ("eq", "ne", "lt", "gt", "ge", "le") and self._nx(c[2]) and self._nx(c[3])
        if k in ("and", "or"):
            return self._ncond(c[1]) and self._ncond(c[2])
        if k == "not":
            return self._ncond(c[1])
        if k == "var":
            return c[1] in self.n_flags
        return k == "bool"

    def _nitem(self, it):
        kind, e = it
        if kind == "char":
            return self._nx(e)
        if e[0] == "str":
            return all(isinstance(p, str) or self._nx(p) for p in e[1])
        return self._nx(e)

    @staticmethod
    def _has_call(e):
        hit = []
        walk(e, lambda x: hit.append(1) if x[0] == "call" else None)
        return bool(hit)

    def _native_block(self, stmts, in_loop=False, in_func=False):
        for s in stmts:
            k = s[0]
            if k == "set":
                if s[2][0] == "var":
                    ok = self._nx(s[3])
                else:
                    ok = s[2][0] == "index" and s[2][1][0] == "var" and s[2][1][1] in self.n_arrays and \
                        self._nx(s[2][2]) and self._nx(s[3]) and not self._flag_expr(s[3])
            elif k == "aug":
                if s[4][0] == "var":
                    ok = self._nx(s[3])
                else:
                    ok = (s[4][0] == "index" and s[4][1][0] == "var" and s[4][1][1] in self.n_arrays and self._nx(s[4][2])
                          and self._nx(s[3]) and not self._has_call(s[4][2]) and not self._has_call(s[3]))
            elif k == "calc":
                ok = s[3][0] == "var" and self._nx(s[2])
            elif k == "convert":
                ok = s[4][0] == "var" and (s[2] == "number" or True) and self._nx(s[3])
            elif k == "alloc":
                ok = s[2] in self.n_arrays
            elif k == "store":
                ok = s[2][0] == "var" and s[2][1] in self.n_arrays and self._nx(s[3]) and self._nx(s[4])
            elif k == "load":
                ok = s[2][0] == "var" and s[2][1] in self.n_arrays and self._nx(s[3]) and s[4][0] == "var"
            elif k == "read":
                ok = s[2] in ("num", "char", "byte") and s[3][0] == "var"
            elif k == "print":
                ok = all(self._nitem(i) for i in s[3])
            elif k == "if":
                ok = (self._ncond(s[2]) and self._native_block(s[3], in_loop, in_func)
                      and (s[4] is None or self._native_block(s[4], in_loop, in_func)))
            elif k == "while":
                ok = self._ncond(s[2]) and self._native_block(s[3], True, in_func)
            elif k == "repeat":
                ok = (s[2] is None or self._nx(s[2])) and self._native_block(s[3], True, in_func)
            elif k == "for":
                ok = (self._nx(s[3]) and self._nx(s[4]) and (s[5] is None or self._nx(s[5]))
                      and self._native_block(s[6], True, in_func))
            elif k == "foreach":
                ok = (s[3][0] == "var" and s[3][1] in self.n_arrays and self._native_block(s[4], True, in_func)
                      and not self._loop_writes(s[4], s[3][1]))
            elif k in ("stop", "skip"):
                ok = in_loop
            elif k == "routine":
                ok = self._native_block(s[3])
            elif k == "define":
                ok = self._native_block(s[4], False, True)
            elif k == "return":
                ok = in_func and s[2] is not None and self._nx(s[2]) and not self._flag_expr(s[2])
            elif k == "exprstmt":
                ok = s[2][0] == "call" and self._nx_call_any(s[2])
            elif k == "callstore":
                ok = s[3][0] == "var" and s[2][0] == "call" and self._nx(s[2])
            elif k == "global" or k == "rterror" or k == "warnmsg":
                ok = True
            elif k == "fail":                         # Zoomy 8: a fixed message is a runtime error in the Big modes' lowering
                ok = (self.big or self.bd) and s[2][0] == "str" and len(s[2][1]) == 1 and isinstance(s[2][1][0], str)
            elif k == "unread":
                ok = self._nx(s[2])
            elif k in ("action", "scope"):
                ok = self._native_block(s[-1] if k == "action" else s[2], in_loop, in_func)
            elif k == "run":
                ok = s[2] in self.funcs and self.funcs[s[2]][0] == "routine"
            elif k == "runwith":
                ok = self._nx(s[3]) and not self.ints
            elif k == "finish":
                ok = s[2] is None or self._nx(s[2])
            elif k == "workers":
                ok = self._nx(s[2]) and s[3][0] == "var"
            elif k == "clock" or k == "fsize":
                ok = s[2][0] == "var"
            elif k == "syscall":
                ok = self.ints and self._nx(s[2]) and all(self._nx(a) for a in s[3]) and (s[4] is None or s[4][0] == "var")
            elif k == "seekf":
                ok = self._nx(s[2])
            elif k == "waitw" or k == "closef":
                ok = True
            elif k == "openf":
                ok = s[2][0] == "str" and len(s[2][1]) == 1 and isinstance(s[2][1][0], str)
            elif k == "openarr":
                ok = s[2][0] == "var"
            elif k in ("extern", "pass"):
                ok = True
            else:
                ok = False
            if not ok:
                if self.why_not is None:                 # the innermost line is found first
                    self.why_not = (s[1], k)
                return False
        return True

    def _nx_call_any(self, e):
        """a call used as a statement: the function need not give a value back"""
        f = self.funcs.get(e[1][1]) if e[1][0] == "var" else None
        return (f is not None and f[0] == "define" and not e[3] and len(e[2]) == len(f[3])
                and all(self._nx(a) and not self._flag_expr(a) for a in e[2]))

    def _loop_writes(self, body, arr):
        """does this loop body (or anything it calls) store into the array being walked?  (Python walks a snapshot of it)"""
        for st in all_stmts(body):
            if st[0] == "store" and st[2][0] == "var" and st[2][1] == arr:
                return True
            for pl in ([st[2]] if st[0] == "set" else [st[4]] if st[0] == "aug" else []):
                if pl[0] == "index" and pl[1][0] == "var" and pl[1][1] == arr:
                    return True
            if st[0] == "run" and arr in self.n_writes.get(st[2], ()):
                return True
            for e in stmt_exprs(st):
                hit = []
                walk(e, lambda x: hit.append(x[1][1]) if x[0] == "call" and x[1][0] == "var" else None)
                if any(arr in self.n_writes.get(h, ()) for h in hit):
                    return True
        return False

    def _char_vars_ok(self):
        """`convert number N to ASCII` gives a character; natively such a variable may only be printed."""
        targets = {s[4][1] for s in all_stmts(self.stmts) if s[0] == "convert" and s[2] == "number"}
        if not targets:
            return True
        for s in all_stmts(self.stmts):
            if s[0] == "convert" and s[2] == "number":
                exprs = [s[3]]
            elif s[0] == "print":
                exprs = []
                for kind, e in s[3]:
                    if kind == "val" and e[0] == "var":
                        continue
                    if kind == "val" and e[0] == "str":
                        exprs += [p for p in e[1] if not isinstance(p, str) and p[0] != "var"]
                        continue
                    exprs.append(e)
            else:
                exprs = stmt_exprs(s)
                if set(assigned_names(s)) & targets:
                    return False
            for e in exprs:
                hit = []
                walk(e, lambda x: hit.append(x) if x[0] == "var" and x[1] in targets else None)
                if hit:
                    return False
        return True


# =============================================================================
# Python code generation
# =============================================================================
FN_TEMPLATES = {
    "len": "_zlen({0})", "upper": "({0}).upper()", "lower": "({0}).lower()", "trim": "({0}).strip()",
    "text": "_zshow({0})", "numfrom": "_znum({0})", "sqrt": "_zsqrt({0})", "abs": "abs({0})",
    "floor": "_zfloor({0})", "ceil": "_zceil({0})", "round": "_zround({0})", "sum": "_zsum({0})",
    "min": "_zextreme(min, {0})", "max": "_zextreme(max, {0})", "sorted": "_zsorted({0})",
    "reversed": "_zreversed({0})", "first": "_zix({0}, 0.0)", "last": "_zlast({0})",
    "keys": "list(({0}).keys())", "values": "list(({0}).values())", "lines": "_zlines({0})",
    "sin": "_zsin({0})", "cos": "_zcos({0})", "tan": "_ztan({0})", "atan": "_zatan({0})",
    "ln": "_zln({0})", "exp": "_zexp({0})", "code": "_zcode({0})", "chr": "_zchar({0})",
    "rem": "_zrem({0}, {1})", "split": "_zsplit({0}, {1})", "join": "_zjoin({0}, {1})",
    "replace": "({2}).replace({0}, {1})", "slice": "_zslice({0}, {1}, {2})", "position": "_zpos({0}, {1})",
    "count": "float(({1}).count({0}))", "format": "_zformat({0}, {1})", "rounded": "_zrounded({0}, {1})",
    "randnum": "_zrandom.random()", "randbetween": "_zrandbetween({0}, {1})", "ask": "_zask({0})",
    "args": "_zargs()", "exists": "_zos.path.exists({0})", "now": "_ztime.time()",
}
BD_FN_TEMPLATES = {"sqrt": "_bd_sqrt({0})", "floor": "_bd_floor({0})", "ceil": "_bd_ceil({0})", "round": "_bd_round({0})",
                   "rem": "_bd_rem({0}, {1})", "first": "_zix({0}, 0)", "count": "(({1}).count({0}))"}
BD_MATH = {"sin": "bdm_sin", "cos": "bdm_cos", "tan": "bdm_tan", "atan": "bdm_atan", "ln": "bdm_ln", "exp": "bdm_exp"}
BD_NO_FN = {"rounded", "format"}
INT_FN_TEMPLATES = {"sqrt": "_zisqrt({0})", "floor": "{0}", "ceil": "{0}", "round": "{0}", "rem": "_zirem({0}, {1})",
                    "numfrom": "_zinum({0})", "first": "_zix({0}, 0)", "count": "(({1}).count({0}))"}
CMP_OPS = {"eq": "==", "ne": "!=", "lt": "<", "gt": ">", "ge": ">=", "le": "<="}
IS_TEMPLATES = {"empty": "_zempty({0})", "none": "({0} is None)",
                "number": "(isinstance({0}, (int, float, _BD)) and not isinstance({0}, bool))",
                "text": "isinstance({0}, str)", "list": "isinstance({0}, (list, tuple))",
                "table": "isinstance({0}, dict)", "bool": "isinstance({0}, bool)"}


def children(e):
    k = e[0]
    if k == "str":
        return [p for p in e[1] if not isinstance(p, str)]
    if k in ("list", "tuple"):
        return list(e[1])
    if k == "table":
        return [x for kv in e[1] for x in kv]
    if k == "bin" or k == "cmp":
        return [e[2], e[3]]
    if k in ("neg", "not"):
        return [e[1]]
    if k == "bitop":
        return [e[2]] + ([e[3]] if e[3] is not None else [])
    if k in ("and", "or"):
        return [e[1], e[2]]
    if k == "is":
        return [e[2]]
    if k == "attr":
        return [e[1]]
    if k == "index":
        return [e[1], e[2]]
    if k == "call":
        return [e[1]] + list(e[2]) + [v for _, v in e[3]]
    if k == "fn":
        return list(e[2])
    if k in ("filter",):
        return [e[1], e[2]]
    if k == "quant":
        return [e[2], e[3]]
    return []


def walk(e, fn):
    fn(e)
    for c in children(e):
        walk(c, fn)


def stmt_exprs(s):
    """Top-level expressions directly inside a statement (not its nested blocks)."""
    k = s[0]
    if k == "set":
        return [s[2], s[3]]
    if k == "aug":
        return [s[3], s[4]]
    if k == "calc":
        return [s[2], s[3]]
    if k == "store":
        return [s[2], s[3], s[4]]
    if k == "load":
        return [s[2], s[3], s[4]]
    if k == "alloc":
        return [s[3]]
    if k == "convert":
        return [s[3], s[4]]
    if k == "read":
        return [s[3]]
    if k == "readfile":
        return [s[2], s[3]]
    if k == "openf" or k == "openarr":
        return [s[2]]
    if k == "closef":
        return []
    if k == "print":
        return [i[1] for i in s[3]]
    if k == "writefile":
        return [s[3], s[4]]
    if k in ("if", "while"):
        return [s[2]]
    if k == "repeat":
        return [s[2]] if s[2] else []
    if k == "foreach":
        return [s[3]]
    if k == "for":
        return [s[3], s[4]] + ([s[5]] if s[5] else [])
    if k == "return":
        return [s[2]] if s[2] else []
    if k == "finish":
        return [s[2]] if s[2] else []
    if k == "clock" or k == "fsize":
        return [s[2]]
    if k == "syscall":
        return [s[2]] + list(s[3])
    if k == "seekf" or k == "unread":
        return [s[2]]
    if k == "workers":
        return [s[2], s[3]]
    if k in ("fail", "warn"):
        return [s[2]]
    if k == "check":
        return [s[2]]
    if k == "exprstmt":
        return [s[2]]
    if k == "callstore":
        return [s[2], s[3]]
    if k == "runwith":
        return [s[3]]
    if k in ("append", "remove"):
        return [s[2], s[3]]
    if k == "removeat":
        return [s[2], s[3]]
    if k == "insert":
        return [s[2], s[3], s[4]]
    if k in ("sort",):
        return [s[2]]
    if k in ("reverse", "clear"):
        return [s[2]]
    if k == "wait" or k == "delete":
        return [s[2]]
    return []


def nested_blocks(s):
    k = s[0]
    if k == "if":
        return [s[3]] + ([s[4]] if s[4] else [])
    if k in ("while", "repeat"):
        return [s[3]]
    if k == "foreach":
        return [s[4]]
    if k == "for":
        return [s[6]]
    if k == "routine":
        return [s[3]]
    if k == "define":
        return [s[4]]
    if k in ("action", "scope"):
        return [s[2]]
    if k == "try":
        out = [s[2]]
        if s[3]:
            out.append(s[3][1])
        if s[5]:
            out.append(s[5])
        return out
    return []


def assigned_names(s):
    """Names this one statement (not its nested blocks) binds."""
    k = s[0]
    out = []

    def place(p):
        if p[0] == "var":
            out.append(p[1])
    if k == "set":
        place(s[2])
    elif k == "aug":
        place(s[4])
    elif k == "calc":
        place(s[3])
    elif k == "load":
        place(s[4])
    elif k == "read":
        place(s[3])
        out.append("input_ok")
    elif k == "readfile":
        place(s[3])
    elif k == "openf" or k == "openarr":
        out.append("input_ok")
    elif k == "callstore":
        place(s[3])
    elif k == "convert":
        place(s[4])
        out.append("input_ok")
    elif k == "alloc":
        out.append(s[2])
    elif k == "workers":
        place(s[3])
    elif k == "clock" or k == "fsize":
        place(s[2])
    elif k == "syscall":
        if s[4] is not None:
            place(s[4])
    elif k in ("foreach", "for"):
        out.append(s[2])
    elif k == "try" and s[3]:
        out.append(s[3][0])
    elif k == "use":
        out.append(s[3])
    elif k == "usefrom":
        out += s[3]
    return out


def all_stmts(stmts):
    for s in stmts:
        yield s
        for b in nested_blocks(s):
            yield from all_stmts(b)


class Gen:
    def __init__(self, prog, warn):
        self.prog, self.warn = prog, warn
        self.ints = getattr(prog, "ints", False)
        self.uns = self.ints and getattr(prog, "uns", False)
        self.bd = getattr(prog, "bd", False)             # Zoomy 7: Big Decimals
        self.lines = []                  # (python text, zoomy line)
        self.ind = 0
        self.funcs = prog.funcs
        self.compat = prog.native_ok
        self.imports = set()
        self.assigned_anywhere = {"input_ok"}
        self.cur_line = 0
        self.local_names = None          # inside 'define': the local names
        self.tmp = 0

    # -- emit
    def add(self, text, line=None):
        self.lines.append(("    " * self.ind + text, line if line is not None else self.cur_line))

    def fresh(self, base):
        self.tmp += 1
        return f"_z{base}{self.tmp}"

    # -- names
    def V(self, name):
        return "z_" + name

    # -- expressions
    def E(self, e):
        k = e[0]
        if k == "num":
            v = e[1]
            if self.bd:
                import fractions
                f = fractions.Fraction(v)
                return f"_bdlit({f.numerator}, {f.denominator})" if f >= 0 else f"(-_bdlit({-f.numerator}, {f.denominator}))"
            if self.ints:
                if self.uns:
                    return str(int(v) & 0xFFFFFFFFFFFFFFFF)
                return str(int(v)) if v >= 0 else f"({int(v)})"
            if v != v:
                return "_NAN"
            if v in (float("inf"), float("-inf")):
                return "_INF" if v > 0 else "(-_INF)"
            return repr(v) if v >= 0 and repr(v)[0] != "-" else f"({v!r})"
        if k == "str":
            parts = e[1]
            if all(isinstance(p, str) for p in parts):
                return repr("".join(parts))
            return "(" + " + ".join(repr(p) if isinstance(p, str) else f"_zshow({self.E(p)})" for p in parts) + ")"
        if k == "bool":
            return "True" if e[1] else "False"
        if k == "none":
            return "None"
        if k == "var":
            n = e[1]
            if n == "pi" and "pi" not in self.assigned_anywhere and "pi" not in self.funcs:
                return "_zmath.pi"
            return self.V(n)
        if k == "list":
            return "[" + ", ".join(self.E(x) for x in e[1]) + "]"
        if k == "tuple":
            return "(" + ", ".join(self.E(x) for x in e[1]) + ("," if len(e[1]) == 1 else "") + ")"
        if k == "table":
            return "{" + ", ".join(f"{self.E(a)}: {self.E(b)}" for a, b in e[1]) + "}"
        if k == "bin":
            op, a, b = e[1], self.E(e[2]), self.E(e[3])
            if self.bd:
                return {"plus": f"({a} + {b})", "minus": f"({a} - {b})", "times": f"({a} * {b})", "divide": f"({a} / {b})",
                        "mod": f"_bd_mod({a}, {b})"}.get(op, f"_bd_pow({a}, {b})")
            if self.ints:
                if op in ("plus", "minus", "times"):
                    return f"_ziw({a} {'+' if op == 'plus' else '-' if op == 'minus' else '*'} {b})"
                return {"divide": f"_zidiv({a}, {b})", "mod": f"_zimod({a}, {b})"}.get(op, f"_zipow({a}, {b})")
            if op == "plus":
                return f"({a} + {b})"
            if op == "minus":
                return f"({a} - {b})"
            if op == "times":
                return f"({a} * {b})"
            if op == "divide":
                return f"_zdiv({a}, {b})"
            if op == "mod":
                return f"_zmod({a}, {b})"
            return f"_zpow({a}, {b})"
        if k == "neg":
            return f"_ziw(-{self.E(e[1])})" if self.ints else f"(-{self.E(e[1])})"
        if k == "bitop":
            return f"_zbit({e[1]!r}, {self.E(e[2])}" + (f", {self.E(e[3])})" if e[3] is not None else ")")
        if k == "not":
            return f"(not {self.E(e[1])})"
        if k == "and":
            return f"({self.E(e[1])} and {self.E(e[2])})"
        if k == "or":
            return f"({self.E(e[1])} or {self.E(e[2])})"
        if k == "cmp":
            op, a, b = e[1], self.E(e[2]), self.E(e[3])
            if op in CMP_OPS:
                return f"({a} {CMP_OPS[op]} {b})"
            if op == "contains":
                return f"_zcontains({a}, {b})"
            if op == "in":
                return f"_zcontains({b}, {a})"
            return f"_z{op}({a}, {b})"            # starts / ends
        if k == "is":
            t = IS_TEMPLATES[e[1]].format(self.E(e[2]))
            return f"(not {t})" if e[3] else t
        if k == "attr":
            return f"_zattr({self.E(e[1])}, {e[2]!r})"
        if k == "index":
            return f"_zix({self.E(e[1])}, {self.E(e[2])})"
        if k == "fn":
            if self.bd and e[1] in BD_NO_FN:
                raise ZoomyError(f"'{e[1]}' is not available with Big Decimals yet (it works on floats)", self.prog.file, self.cur_line)
            tpl = (BD_FN_TEMPLATES.get(e[1]) if self.bd else None) or (INT_FN_TEMPLATES.get(e[1]) if self.ints else None) or FN_TEMPLATES[e[1]]
            return tpl.format(*[self.E(a) for a in e[2]])
        if k == "call":
            return self.call(e)
        if k == "filter":
            v = self.V(e[3])
            return f"[{v} for {v} in {self.E(e[1])} if {self.E(e[2])}]"
        if k == "quant":
            body = f"({self.E(e[3])} for {self.V(e[4])} in {self.E(e[2])})"
            return {"all": f"all{body}", "any": f"any{body}", "none": f"(not any{body})"}[e[1]]
        raise ZoomyError(f"internal error: unknown expression {k}", self.prog.file, self.cur_line)

    def call(self, e):
        f, args, kw = e[1], e[2], e[3]
        a = [self.E(x) for x in args]
        kws = [f"{n}={self.E(v)}" for n, v in kw]
        if f[0] == "var" and f[1] in self.funcs:
            fs = self.funcs[f[1]]
            want = len(fs[3]) if fs[0] == "define" else 0
            if kws:
                raise ZoomyError(f"'{f[1]}' is a Zoomy function; 'named' values are only for Python functions", self.prog.file, self.cur_line)
            if len(a) != want:
                raise ZoomyError(f"'{f[1]}' needs {want} value(s) but is given {len(a)}", self.prog.file, self.cur_line)
            return f"{self.V(f[1])}({', '.join(a)})"
        if f[0] == "var" and f[1] not in self.assigned_anywhere:
            raise ZoomyError(f"I don't know a function called '{f[1]}' (define it, or import it with 'use ... from python's ...')",
                             self.prog.file, self.cur_line)
        return f"_zpy({', '.join([self.E(f)] + a + kws)})"

    # -- places
    def assign(self, place, value):
        k = place[0]
        if k == "var":
            self.add(f"{self.V(place[1])} = {value}")
        elif k == "index":
            self.add(f"_zset({self.E(place[1])}, {self.E(place[2])}, {value})")
        else:
            self.add(f"_zsetattr({self.E(place[1])}, {place[2]!r}, {value})")

    # -- statements
    def block(self, stmts):
        self.ind += 1
        n = len(self.lines)
        for s in stmts:
            self.stmt(s)
        if len(self.lines) == n:
            self.add("pass")
        self.ind -= 1

    def stmt(self, s):
        k = s[0]
        self.cur_line = s[1]
        m = getattr(self, "s_" + k, None)
        if m is None:
            raise ZoomyError(f"'{k}' cannot be used here", self.prog.file, s[1])
        m(s)

    def s_pass(self, s):
        self.add("pass")

    def s_set(self, s):
        self.assign(s[2], self.E(s[3]))

    def s_aug(self, s):
        op, val, place = s[2], self.E(s[3]), s[4]
        cur = self.E(place)
        if self.bd:
            expr = {"add": f"({cur} + {val})", "sub": f"({cur} - {val})", "mul": f"({cur} * {val})", "div": f"({cur} / {val})"}[op]
        elif self.ints:
            expr = {"add": f"_ziw({cur} + {val})", "sub": f"_ziw({cur} - {val})", "mul": f"_ziw({cur} * {val})",
                    "div": f"_zidiv({cur}, {val})"}[op]
        else:
            expr = {"add": f"({cur} + {val})", "sub": f"({cur} - {val})", "mul": f"({cur} * {val})",
                    "div": f"_zdiv({cur}, {val})"}[op]
        self.assign(place, expr)

    def s_calc(self, s):
        self.assign(s[3], self.E(s[2]))

    def s_alloc(self, s):
        self.add(f"{self.V(s[2])} = [{'_BD_ZERO' if self.bd else '0' if self.ints else '0.0'}] * _zcount({self.E(s[3])})")

    def s_store(self, s):
        self.add(f"_zset({self.E(s[2])}, {self.E(s[3])}, {self.E(s[4])})")

    def s_load(self, s):
        self.assign(s[4], f"_zix({self.E(s[2])}, {self.E(s[3])})")

    def s_read(self, s):
        fn = {"num": "_zread_inum" if self.ints else "_bd_read_num" if self.bd else "_zread_num", "char": "_zread_char", "byte": "_zread_byte", "line": "_zread_line"}[s[2]]
        tmp = self.fresh("r")
        self.add(f"{tmp}, z_input_ok = {fn}()")
        self.assign(s[3], tmp)

    def s_openf(self, s):
        self.add(f"z_input_ok = _zopen({self.E(s[2])})")

    def s_openarr(self, s):
        self.add(f"z_input_ok = _zopenarr({self.E(s[2])})")

    def s_closef(self, s):
        self.add("_zclose()")

    def s_readfile(self, s):
        self.assign(s[3], f"_zreadfile({self.E(s[2])})")

    def s_writefile(self, s):
        self.add(f"_zwritefile({self.E(s[4])}, {self.E(s[3])}, {s[2]!r})")

    def s_print(self, s):
        pending = []

        def flush():
            if pending:
                self.add("_zw(" + " + ".join(pending) + ")")
                pending.clear()
        for kind, e in s[3]:
            if kind == "char":
                flush()
                self.add(f"_zwb({self.E(e)})")
            elif e[0] == "str" and all(isinstance(p, str) for p in e[1]):
                pending.append(repr("".join(e[1])))
            elif e[0] == "str":
                pending.append(self.E(e))
            else:
                pending.append(f"_zshow({self.E(e)})")
        if s[2]:
            pending.append("'\\n'")
        flush()

    def s_if(self, s):
        self.add(f"if {self.E(s[2])}:")
        self.block(s[3])
        orelse = s[4]
        while orelse is not None:
            if len(orelse) == 1 and orelse[0][0] == "if" and len(orelse[0]) > 5 and orelse[0][5] == "elif":
                nxt = orelse[0]
                self.cur_line = nxt[1]
                self.add(f"elif {self.E(nxt[2])}:")
                self.block(nxt[3])
                orelse = nxt[4]
            else:
                self.add("else:")
                self.block(orelse)
                break

    def s_while(self, s):
        self.add(f"while {self.E(s[2])}:")
        self.block(s[3])

    def s_repeat(self, s):
        if s[2] is None:
            self.add("while True:")
        else:
            self.add(f"for {self.fresh('i')} in range(_zcount({self.E(s[2])})):")
        self.block(s[3])

    def s_foreach(self, s):
        self.add(f"for {self.V(s[2])} in _ziter({self.E(s[3])}):")
        self.block(s[4])

    def s_for(self, s):
        step = self.E(s[5]) if s[5] else ("1" if self.ints else "1.0")
        self.add(f"for {self.V(s[2])} in {'_zirange' if self.ints else '_bd_range' if self.bd else '_zfrange'}({self.E(s[3])}, {self.E(s[4])}, {step}):")
        self.block(s[6])

    def s_stop(self, s):
        self.add("break")

    def s_skip(self, s):
        self.add("continue")

    def s_return(self, s):
        self.add("return" + (f" {self.E(s[2])}" if s[2] else ""))

    def s_fsize(self, s):
        self.assign(s[2], "_zfsize()")

    def s_seekf(self, s):
        self.add(f"_zseek({self.E(s[2])})")

    def s_syscall(self, s):
        call = f"_zsyscall({self.E(s[2])}" + "".join(", " + self.E(a) for a in s[3]) + ")"
        if s[4] is None:
            self.add(call)
        else:
            self.assign(s[4], call)

    def s_clock(self, s):
        self.assign(s[2], "_zcores()" if len(s) > 3 else "_zclock()")

    def s_workers(self, s):
        # the Python backend has one worker: this program is worker 0
        self.assign(s[3], "0" if self.ints else "0.0")

    def s_waitw(self, s):
        self.add("pass")

    def s_finish(self, s):
        self.add(f"_zexit(_zint64({self.E(s[2])}) & 255)" if s[2] else "_zexit(0)")

    def s_fail(self, s):
        self.add(f"raise ZoomyFailure(_zshow({self.E(s[2])}))")

    def s_warn(self, s):
        self.add(f"_zwarn(_zshow({self.E(s[2])}))")

    def s_check(self, s):
        self.add(f"if not {self.E(s[2])}:")
        self.add(f"    raise ZoomyFailure({'check failed: ' + s[3]!r})")

    def s_exprstmt(self, s):
        self.add(self.E(s[2]))

    def s_callstore(self, s):
        self.assign(s[3], self.E(s[2]))

    def s_run(self, s):
        name = s[2]
        if name not in self.funcs:
            if name in self.prog_externs:
                raise ZoomyError(f"'{name}' is an extern (C) function; those need the native compiler (remove other features)",
                                 self.prog.file, s[1])
            raise ZoomyError(f"I don't know a routine called '{name}'", self.prog.file, s[1])
        f = self.funcs[name]
        if f[0] == "define" and f[3]:
            raise ZoomyError(f"'{name}' needs values; use: call {name} with ...", self.prog.file, s[1])
        self.add(f"{self.V(name)}()")

    def s_runwith(self, s):
        raise ZoomyError("'run NAME with X' calls an extern (C) function and needs the native compiler "
                         "(for Python libraries use: call NAME with X)", self.prog.file, s[1])

    def s_extern(self, s):
        raise ZoomyError("'extern' needs the native compiler (use python's math for Python programs)", self.prog.file, s[1])

    def s_use(self, s):
        self.add(f"import {s[2]} as {self.V(s[3])}")

    def s_usefrom(self, s):
        orig = s[4] if len(s) > 4 else s[3]
        self.add(f"from {s[2]} import " + ", ".join(f"{o} as {self.V(n)}" for o, n in zip(orig, s[3])))

    def s_global(self, s):
        pass

    def s_append(self, s):
        self.add(f"({self.E(s[3])}).append({self.E(s[2])})")

    def s_insert(self, s):
        self.add(f"_zinsert({self.E(s[3])}, {self.E(s[4])}, {self.E(s[2])})")

    def s_remove(self, s):
        self.add(f"_zremove({self.E(s[3])}, {self.E(s[2])})")

    def s_removeat(self, s):
        self.add(f"_zremove_at({self.E(s[3])}, {self.E(s[2])})")

    def s_sort(self, s):
        self.add(f"_zsort({self.E(s[2])}, {s[3]})")

    def s_reverse(self, s):
        self.add(f"({self.E(s[2])}).reverse()")

    def s_clear(self, s):
        self.add(f"({self.E(s[2])}).clear()")

    def s_wait(self, s):
        self.add(f"_ztime.sleep({self.E(s[2])})")

    def s_delete(self, s):
        self.add(f"_zdeletefile({self.E(s[2])})")

    def s_try(self, s):
        if s[3] is None and s[5] is None:
            raise ZoomyError("'try:' needs an 'if it fails:' block (or an 'always:' block) after it", self.prog.file, s[1])
        self.add("try:")
        self.block(s[2])
        if s[3] is not None:
            name, body = s[3]
            self.add("except Exception as _zexc:")
            self.ind += 1
            self.add(f"{self.V(name)} = _znice(_zexc)")
            self.ind -= 1
            self.block_continue(body)
        if s[5] is not None:
            self.add("finally:")
            self.block(s[5])

    def block_continue(self, stmts):          # statements appended to the 'except' body just opened
        self.ind += 1
        for st in stmts:
            self.stmt(st)
        self.ind -= 1

    def s_routine(self, s):
        self.function(s[2], [], s[3], True, s[1])

    def s_define(self, s):
        self.function(s[2], s[3], s[4], False, s[1])

    def s_scope(self, s):
        for st in s[2]:
            self.stmt(st)

    def s_convert(self, s):
        tmp = self.fresh("c")
        if s[2] == "character":
            self.add(f"{tmp}, z_input_ok = _zchar_to_num({self.E(s[3])})")
        else:
            self.add(f"{tmp} = _zchar({self.E(s[3])})")
        self.assign(s[4], tmp)

    def s_action(self, s):
        for st in s[2]:
            self.stmt(st)

    def function(self, name, params, body, is_routine, line):
        self.cur_line = line
        assigned = set()
        declared_global = set()
        for st in all_stmts(body):
            assigned.update(assigned_names(st))
            if st[0] == "global":
                declared_global.update(st[2])
        if is_routine:
            globs = set(assigned)
            self.local_names = None
        else:
            globs = set(declared_global) | ({"input_ok"} & assigned)
        self.add(f"def {self.V(name)}({', '.join(self.V(p) for p in params)}):")
        self.ind += 1
        if globs:
            self.add("global " + ", ".join(sorted(self.V(g) for g in globs)))
        self.ind -= 1
        self.block_continue_func(body)

    def block_continue_func(self, stmts):
        self.ind += 1
        n = len(self.lines)
        for st in stmts:
            self.stmt(st)
        if len(self.lines) == n:
            self.add("pass")
        self.ind -= 1

    # -- whole program
    def generate(self):
        prog = self.prog
        self.prog_externs = {s[2] for s in prog.stmts if s[0] == "extern"}
        for st in all_stmts(prog.stmts):
            self.assigned_anywhere.update(assigned_names(st))
            if st[0] in ("define",):
                self.assigned_anywhere.update(st[3])
        self.assigned_anywhere.update(prog.funcs)
        self._warn_unset()
        header, defs, main = [], [], []
        self.lines = []
        self.ind = 1
        # imports first, then definitions, then the main body
        for st in prog.stmts:
            if st[0] in ("use", "usefrom"):
                self.stmt(st)
        imports = self.lines
        self.lines = []
        for st in prog.stmts:
            if st[0] in ("routine", "define"):
                self.stmt(st)
        defs = self.lines
        self.lines = []
        main_stmts = []
        for st in prog.stmts:
            if st[0] == "action":
                main_stmts += st[2]
            elif st[0] not in ("routine", "define", "use", "usefrom", "extern"):
                main_stmts.append(st)
        for st in main_stmts:
            self.stmt(st)
        main = self.lines
        init = [("    z_input_ok = 0.0", 0)]
        if self.compat:
            used = set()
            for st in all_stmts(prog.stmts):
                for e in stmt_exprs(st):
                    walk(e, lambda x: used.add(x[1]) if x[0] == "var" else None)
                used.update(assigned_names(st))
            used -= set(prog.funcs)
            used.discard("input_ok")
            init += [(f"    {self.V(n)} = 0.0", 0) for n in sorted(used)]
        return init + imports + defs + main

    def _reachable(self):
        main = []
        for st in self.prog.stmts:
            if st[0] == "action":
                main += st[2]
            elif st[0] not in ("routine", "define", "use", "usefrom", "extern"):
                main.append(st)
        seen, todo, out = set(), list(main), list(main)
        while todo:
            st = todo.pop()
            names = []
            if st[0] == "run":
                names.append(st[2])
            for e in stmt_exprs(st):
                walk(e, lambda x: names.append(x[1][1]) if x[0] == "call" and x[1][0] == "var" else None)
            for b in nested_blocks(st):
                todo += b
                out += b
            for n in names:
                if n in self.funcs and n not in seen:
                    seen.add(n)
                    f = self.funcs[n]
                    body = f[3] if f[0] == "routine" else f[4]
                    todo += body
                    out += body
        return out

    def _warn_unset(self):
        reads = {}
        for st in all_stmts(self._reachable()):
            for e in stmt_exprs(st):
                def rec(x, line=st[1]):
                    if x[0] == "var":
                        reads.setdefault(x[1], line)
                walk(e, rec)
        for name, line in sorted(reads.items(), key=lambda kv: kv[1]):
            if name not in self.assigned_anywhere and name not in self.prog.funcs and name != "pi" and name not in ELEM_VARS:
                self.warn(f"{self.prog.file}:{line}: variable '{name}' is used but never given a value")


def compile_python(prog, warn=lambda m: None):
    """-> (python source text, {python line: zoomy line})"""
    gen = Gen(prog, warn)
    body = gen.generate()
    with open(os.path.join(HERE, "zoomy_runtime.py"), encoding="utf-8") as f:
        runtime = f.read().rstrip("\n")
    head = runtime.split("\n")
    lines = list(head)
    lines.append("")
    if getattr(prog, "bd", False):
        lines.append("_zset_bd()")
    if getattr(prog, "ints", False):
        lines.append("_zset_ints(True)" if getattr(prog, "uns", False) else "_zset_ints(False, True)" if getattr(prog, "big", False) else "_zset_ints()")
    lines.append(f"_ZNAME = {os.path.basename(prog.file)!r}")
    lines.append("try:")
    zmap = {}
    # the ZLINES literal is on one line; reserve its position first
    zline_index = len(lines)
    lines.append("")
    # (the try: above is closed by the except below; ZLINES is defined before it, so move it)
    lines.pop()
    lines.pop()
    lines.append("_ZLINES = {}")
    lines.append("try:")
    for text, zl in body:
        lines.append(text)
        if zl:
            zmap[len(lines)] = zl
    if not body:
        lines.append("    pass")
    lines.append("except BaseException as _zexc:")
    lines.append("    _zdie(_zexc, globals(), _ZLINES, _ZNAME)")
    lines.append("_zexit(0)")
    idx = lines.index("_ZLINES = {}")
    lines[idx] = "_ZLINES = " + repr(zmap)
    return "\n".join(lines) + "\n", zmap


def load_program(path, ints=None):
    prog = Program(path)
    prog.ints_cli = ints
    return prog.load(path)
