#!/usr/bin/env python3
"""
Zoomy 5 sentence layer.

Zoomy 5 lets you write instructions the way a manual does. Every feature in this file is an extra way to SAY something
that Zoomy 4 could already do, so this layer rewrites one source statement into one or more plain Zoomy 4 statements
before the old front end sees it.  `normalize(text)` returns [(depth, text), ...]: `depth` 0 is the statement's own level,
depth 1 is a block under the line before it (for example the action under a trailing `if`).

Features handled here (numbers match the Zoomy 5 grammar map):
   1  trailing conditions         print "Fizz" if n mod 3 is 0          (also unless / while / until, either order)
   2  one-line if/then/otherwise  if x is 5 then print "five" otherwise print "other"
   3  more if-words               when, whenever, provided that, only if = if ;  as long as = while
   4  joining statements          set x to 1; print x     set x to 1 then print x     (+ lines ending in , and or then)
   5  filler words                Please print x     First, set x to 1     Finally, print x
   6  sentence style              Print x.   If x is 5:   Print x!
   7  questions (marker only)     Is x above 3?  ->  __question is x above 3   (the Parser does the rest)
  12  contractions                isn't aren't doesn't don't can't it's
  13  prepositions                put 5 into list   put 5 at the end of list   insert 5 before item 2 of list   take 5 from x
  14  verb synonyms               show display say / make sure that / return / continue / increase decrease double halve
  15  phrasal verbs               add up xs   look up "k" in t   round up x   round down x   round off x to 2 places
  16  modals                      x must be at least 0   x should be at least 0   x cannot be 0
  17  counting adverbs            print "hi" twice      add 1 to x 3 times
  21  leading links           And print x.   Also print x.   Then print x.   After that, print x.   (ignored)
  18  conjunction extras          yet = but   not only A but also B = both A and B   (because "message" is in the Front)
  20  number words                repeat three times   set x to twenty one
"""
import re


class SentenceError(Exception):
    pass


# --------------------------------------------------------------------------------------------- scanning helpers
_CHR = re.compile(r"'(?:[^'\\]|\\[nt0\\'])'")


def mask_of(text):
    """True for every character that is inside text "...", a 'c' character, or ( ) / [ ] brackets."""
    n = len(text)
    m = [False] * n
    depth = 0
    i = 0
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                if text[j] == "\\":
                    j += 1
                j += 1
            for k in range(i, min(j + 1, n)):
                m[k] = True
            i = j + 1
            continue
        if c == "'" and not (i > 0 and (text[i - 1].isalnum() or text[i - 1] == "_")):
            mm = _CHR.match(text, i)
            if mm:
                for k in range(i, mm.end()):
                    m[k] = True
                i = mm.end()
                continue
        if c in "([":
            depth += 1
            m[i] = True
        elif c in ")]":
            m[i] = True
            depth = max(0, depth - 1)
        elif depth > 0:
            m[i] = True
        i += 1
    return m


def find_top(rx, text, mask=None, start=0):
    """first match of compiled regex rx that starts outside strings and brackets"""
    mask = mask if mask is not None else mask_of(text)
    for m in rx.finditer(text, start):
        if not mask[m.start()]:
            return m
    return None


def sub_top(pattern, repl, text, flags=re.I):
    """regex substitution that leaves strings and brackets alone; keeps a leading capital letter"""
    rx = re.compile(pattern, flags)
    mask = mask_of(text)
    out, last = [], 0
    for m in rx.finditer(text):
        if mask[m.start()]:
            continue
        r = repl(m) if callable(repl) else m.expand(repl)
        if m.group(0)[:1].isupper() and r[:1].islower():
            r = r[:1].upper() + r[1:]
        out.append(text[last:m.start()])
        out.append(r)
        last = m.end()
    out.append(text[last:])
    return "".join(out)


def split_top(text, sep):
    mask = mask_of(text)
    parts, last = [], 0
    for i, c in enumerate(text):
        if c == sep and not mask[i]:
            parts.append(text[last:i])
            last = i + 1
    parts.append(text[last:])
    return parts


def first_word(text):
    m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)", text)
    return m.group(1).lower() if m else ""


# --------------------------------------------------------------------------------------------- word lists
STMT_VERBS = {"set", "add", "subtract", "multiply", "divide", "print", "write", "append", "insert", "remove", "sort", "reverse",
              "clear", "read", "delete", "store", "load", "put", "calculate", "convert", "call", "run", "wait", "finish", "fail",
              "check", "give", "stop", "skip", "show", "display", "say", "return", "continue", "increase", "decrease", "double",
              "halve", "triple", "take", "warn", "ask", "let", "create", "define", "include", "use", "make", "ensure", "verify"}
# words that may start a line and are written with a capital letter at the start of a sentence
KEYWORDS = STMT_VERBS | {"if", "else", "otherwise", "unless", "until", "while", "repeat", "for", "routine", "action", "try", "always",
                         "when", "whenever", "provided", "only", "as", "global", "extern", "please", "first", "next", "then",
                         "finally", "also", "now", "just", "is", "are", "does", "do", "what", "how", "where"} - {"let", "create", "define"}
FILLER = ("please", "first", "next", "then", "finally", "also", "now", "just", "okay", "ok",
          # polite and formal
          "kindly", "hereby", "herewith", "henceforth", "thereupon", "thereafter", "subsequently", "furthermore", "moreover",
          "additionally", "lastly", "secondly", "thirdly", "accordingly", "therefore", "consequently", "afterwards", "afterward",
          # chatty
          "alright", "anyway", "anyhow", "basically", "actually", "well", "so", "right", "yo", "hey", "um", "uh", "ahem",
          # old-fashioned
          "prithee", "pray", "verily", "forsooth", "indeed", "hark")
# longer ways to ask: "go ahead and print x", "I would like you to print x", "let's print x", "we shall print x"
FILLER_PHRASES = (r"go\s+ahead\s+and", r"do\s+go\s+ahead\s+and", r"i\s+would\s+like\s+you\s+to", r"i'd\s+like\s+you\s+to", r"i\s+want\s+you\s+to",
                  r"i\s+need\s+you\s+to", r"i\s+would\s+like\s+to", r"i'd\s+like\s+to", r"you\s+(?:should|must|may|can|will|shall)(?:\s+now)?",
                  r"we\s+(?:should|must|shall|will|need\s+to|have\s+to|can)(?:\s+now)?", r"let'?s(?:\s+now)?", r"let\s+us(?:\s+now)?",
                  r"time\s+to", r"next\s+up", r"ok\s+so", r"okay\s+so", r"and\s+now", r"now\s+then", r"so\s+then", r"i\s+pray\s+you", r"if\s+you\s+please",
                  r"would\s+you\s+(?:please\s+)?", r"could\s+you\s+(?:please\s+)?", r"can\s+you\s+(?:please\s+)?", r"do\s+please", r"please\s+do",
                  r"lo\s+and", r"well\s+then", r"on\s+with\s+it", r"here\s+goes")

NUM_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
             "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
             "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
             "eighty": 80, "ninety": 90,
             "naught": 0, "nought": 0, "nil": 0, "zilch": 0, "nada": 0}               # informal and old-fashioned zeros
BIG_WORDS = {"hundred": 100, "thousand": 1000, "million": 1000000}
MULT_WORDS = {"dozen": 12, "score": 20, "gross": 144}                                  # two dozen = 24, three score = 60
NUMBER_WORDS = dict(NUM_WORDS, **BIG_WORDS, **MULT_WORDS)


def number_run(words):
    """['twenty', 'one'] -> 21, ['three', 'hundred'] -> 300, ['one', 'thousand', 'five'] -> 1005; None if it is not a number"""
    total = current = 0
    for w in words:
        w = w.lower()
        if w in NUM_WORDS:
            current += NUM_WORDS[w]
        elif w == "hundred":
            current = (current or 1) * 100
        elif w in MULT_WORDS:
            current = (current or 1) * MULT_WORDS[w]
        elif w in BIG_WORDS:
            total += (current or 1) * BIG_WORDS[w]
            current = 0
        else:
            return None
    return total + current


ORDINAL_WORDS = {"first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth", "last", "no", "any",
                 "every", "each", "the", "this", "that", "another", "which", "what"}

IF_WORDS = r"when|whenever|provided\s+that|only\s+if|if"
# every way to start a condition, and the plain word it means
HEAD_KW = {"if": "if", "when": "if", "whenever": "if", "provided that": "if", "only if": "if", "unless": "unless",
           "until": "until", "while": "while", "as long as": "while",
           # more formal / older / chattier
           "in case": "if", "in the event that": "if", "in the event": "if", "supposing that": "if", "supposing": "if",
           "assuming that": "if", "assuming": "if", "given that": "if", "on condition that": "if", "so long as": "while",
           "for as long as": "while", "whilst": "while", "until such time as": "until", "up until": "until",
           "any time": "if", "anytime": "if", "every time": "if", "each time": "if",
           "seeing that": "if", "considering that": "if", "granted that": "if"}
_COND_WORD = "(" + "|".join(sorted((w.replace(" ", r"\s+") for w in HEAD_KW), key=len, reverse=True)) + ")"
ELSE_WORDS = r"otherwise|else|or\s+else|failing\s+that|contrariwise|alternatively|in\s+any\s+other\s+case|in\s+all\s+other\s+cases|if\s+not\s+so|failing\s+which|or\s+otherwise"
_IF_START = re.compile(r"(?i)^(?:(" + ELSE_WORDS + r")\s*,?\s+)?" + _COND_WORD + r"\b\s*")
_TRAILING = re.compile(r"(?i)\b" + _COND_WORD + r"\b")
_THEN = re.compile(r"(?i)\bthen\b")
_COMMA = re.compile(",")
_ELSE = re.compile(r"(?i)(?:,\s*)?\b(" + ELSE_WORDS + r")\b")


def _kw(word):
    return HEAD_KW[re.sub(r"\s+", " ", word.lower())]


# --------------------------------------------------------------------------------------------- small passes
def _strip_punct(text):
    text = text.rstrip()
    while text.endswith("!") and not text.endswith("!="):
        text = text[:-1].rstrip()
    if text.endswith(".") and not text.endswith("..") and len(text) > 1 and (not text[-2].isdigit() or "." in text.split()[-1][:-1]):
        text = text[:-1].rstrip()
    return text


_CONTR = [(r"\bisn't\b", "is not"), (r"\baren't\b", "are not"), (r"\bdoesn't\b", "does not"), (r"\bdon't\b", "do not"),
          (r"\bmustn't\b", "must not"), (r"\bshouldn't\b", "should not"), (r"\bcan't\b", "cannot"), (r"\bit's\b", "it is")]


_COMPARE_VOICES = [
    (r"\b(?:does\s+not|doesn't)\s+exceed\b|\bnever\s+exceeds\b|\bis\s+not\s+(?:any\s+)?(?:greater|bigger|larger|higher|more)\s+than\b|\bis\s+no\s+(?:greater|bigger|larger|higher)\s+than\b", "is at most"),
    (r"\bis\s+not\s+(?:any\s+)?(?:less|smaller|lower|fewer)\s+than\b|\bis\s+no\s+(?:smaller|lower|less|fewer)\s+than\b", "is at least"),
    (r"\bis\s+(?:strictly\s+)?greater\s+than\s+or\s+equal\s+to\b|\bis\s+not\s+below\b|\bhas\s+(?:reached|hit)\b|\breaches\b|\bis\s+up\s+to\b", "is at least"),
    (r"\bis\s+(?:strictly\s+)?less\s+than\s+or\s+equal\s+to\b|\bis\s+not\s+above\b", "is at most"),
    (r"\bexceeds\b", "is above"),
    (r"\b(?:falls|is)\s+short\s+of\b", "is below"),
    (r"\bdiffers\s+from\b|\bis\s+unequal\s+to\b|\bis\s+not\s+equal\s+to\b|\bis\s+not\s+the\s+same\s+as\b|\bis\s+not\s+identical\s+to\b", "is not"),
    (r"\bequals\b|\bis\s+(?:exactly|precisely|just|identical\s+to|equivalent\s+to|exactly\s+equal\s+to)\b", "is"),
]


def _comparisons(text):
    """other ways to compare: exceeds, falls short of, differs from, is no greater than, has reached ..."""
    if not re.search(r"(?i)exceed|short\s+of|differs|equals|reach|\bhas\s+hit|no\s+(?:greater|bigger|larger|higher|smaller|lower|less|fewer)|not\s+(?:any\s+)?(?:greater|bigger|larger|higher|more|less|smaller|lower|fewer|below|above|equal|the\s+same|identical)|greater\s+than\s+or|less\s+than\s+or|exactly|precisely|\bjust\b|identical|equivalent|unequal|up\s+to", text):
        return text
    for pat, rep_ in _COMPARE_VOICES:
        text = sub_top(pat, rep_, text)
    return text


def _contractions(text):
    if "'" not in text:
        return text
    for pat, rep in _CONTR:
        text = sub_top(pat, rep, text)
    return text


def _fillers(text):
    rx = re.compile(r"(?i)^(" + "|".join(re.escape(f) if f.endswith(",") else f for f in FILLER) + "|" + "|".join(FILLER_PHRASES) + r")(?:\b|(?<=,))\s*,?\s*(.*)$")
    while True:
        m = rx.match(text)
        if not m or not m.group(2):
            return text
        rest = m.group(2)
        if m.group(1).lower() == "so" and re.match(r"(?i)long\s+as\b", rest):          # "so long as" is a condition
            return text
        if m.group(1).lower() == "next" and re.fullmatch(r"(?i)(one|please|one\s+please)[.!]?", rest.strip()):
            return text                                                              # "next one" means skip
        if rest[0] in "('=" or first_word(rest) in ("is", "are", "of", "at", "to", "contains", "contain", "does", "do"):
            return text
        text = rest


_LEAD = re.compile(r"(?i)^(?:and|also|then|after\s+that)\b[\s,]*")


def strip_lead(text):
    """'And', 'Also', 'Then' and 'After that,' at the start of a sentence only link it to the one before: they are ignored"""
    while True:
        text = text.strip()
        m = _LEAD.match(text)
        if not m or not text[m.end():].strip():
            return text
        text = text[m.end():]


def _finalize(text):
    m = re.match(r"([A-Za-z]+)", text)
    if m and m.group(1)[0].isupper() and m.group(1).lower() in KEYWORDS:
        return m.group(1).lower() + text[m.end():]
    return text


# --------------------------------------------------------------------------------------------- questions (feature 7)
def _question(text):
    if not text.endswith("?"):
        return None
    q = text[:-1].strip()
    if first_word(q) not in ("is", "are", "does", "do", "what", "how", "where"):
        raise SentenceError("a question line starts with is, are, does, do, what, how many, how long or where "
                            "(like: Is total above 5?)")
    return [(0, "__question " + q[:1].lower() + q[1:])]


# --------------------------------------------------------------------------------------------- headers (feature 3)
_LOOP_HEADS = [
    # loop 5 times: / iterate 5 times: / do this 5 times: / go around 5 times:
    (r"(?:loop|iterate|cycle|go\s+around|go\s+round|do\s+(?:this|that|the\s+following|the\s+next\s+bit|it))\s+(.+?)\s+times", r"repeat \1 times"),
    (r"(?:loop|iterate|cycle)\s+(?:forever|endlessly)|keep\s+(?:going|on)\s+forever|go\s+on\s+forever", "repeat forever"),
    # go through each score in scores: / loop over each ...
    (r"(?:go\s+through|loop\s+(?:over|through)|iterate\s+(?:over|through)|walk\s+through|run\s+through|step\s+through|work\s+through)\s+(?:each|every)\s+(.+)", r"for each \1"),
    (r"for\s+every\s+(\w+\s+in\s+.+)", r"for each \1"),
]


def _header(h):
    m = re.match(r"(?i)^(?:" + ELSE_WORDS + r")$", h.strip())
    if m:
        return "otherwise"
    m = re.match(r"(?i)^(?:" + ELSE_WORDS + r")\s+" + _COND_WORD + r"\b\s*", h)
    if m:
        return "else " + _kw(m.group(1)) + " " + h[m.end():]
    m = re.match(r"(?i)^keep\s+(?:going|on|at\s+it)\s+(.+)$", h)         # keep going while x is below 3
    if m and re.match(_COND_WORD, m.group(1), re.I):
        h = m.group(1)
    m = re.match(r"(?i)^" + _COND_WORD + r"\b\s*", h)
    if m:
        return _kw(m.group(1)) + " " + h[m.end():]
    for pat, rep_ in _LOOP_HEADS:
        m = re.fullmatch(pat, h.strip(), re.I)
        if m:
            return m.expand(rep_)
    return h


# --------------------------------------------------------------------------------------------- statements
def _indent(lines, n=1):
    return [(d + n, t) for d, t in lines]


def _split_joiners(text):
    """set x to 1 then print x  /  ..., and then ...  /  ..., so ...  /  ..., and print x"""
    verbs = "|".join(sorted(STMT_VERBS, key=len, reverse=True))
    rx = re.compile(r"(?i)(?:,\s*)?(?:\band\s+)?\b(?:then|so(?!\s+long\s+as\b)|after\s+that)\b|,\s*and\b(?=\s+(?:" + verbs + r")\b)")
    mask = mask_of(text)
    pieces, last = [], 0
    for m in rx.finditer(text):
        if mask[m.start()] or m.start() == 0:
            continue
        pieces.append(text[last:m.start()])
        last = m.end()
    pieces.append(text[last:])
    return [p.strip(" ,") for p in pieces if p.strip(" ,")]


def _body(text):
    lines = []
    for piece in _split_joiners(text):
        lines += _simple(piece)
    return lines


def _statement(text):
    m = _IF_START.match(text)
    if m:
        return _inline_if(text)
    m = re.match(r"(?i)^(" + ELSE_WORDS + r")\b\s*,?\s*(.+)$", text)
    if m:
        return [(0, "otherwise:")] + _indent(_body(m.group(2)))
    return _body(text)


def _inline_if(text):
    m = _IF_START.match(text)
    lead = "else " if m.group(1) else ""
    kw = _kw(m.group(2))
    rest = text[m.end():]
    mask = mask_of(rest)
    t = find_top(_THEN, rest, mask)
    c = find_top(_COMMA, rest, mask)
    if t and (not c or t.start() < c.start()):
        cond, body = rest[:t.start()].rstrip(" ,"), rest[t.end():]
    elif c:
        cond, body = rest[:c.start()], re.sub(r"(?i)^\s*then\b\s*", "", rest[c.end():])
    else:
        raise SentenceError(f"this '{m.group(2).lower()}' line needs a ':' at the end, or 'then' with the action on the same line "
                            f"(like: {m.group(2).lower()} x is 5 then print \"five\")")
    if not cond.strip() or not body.strip():
        raise SentenceError(f"this '{m.group(2).lower()}' line needs both a condition and an action")
    return _if_lines(lead, kw, cond.strip(), body)


def _if_lines(lead, kw, cond, body):
    bmask = mask_of(body)
    e = find_top(_ELSE, body, bmask)
    then_part, else_part = (body[:e.start()], body[e.end():].strip(" ,")) if e else (body, "")
    lines = [(0, f"{lead}{kw} {cond}:")] + _indent(_body(then_part))
    if else_part:
        if _IF_START.match(else_part) and not _IF_START.match(else_part).group(1):
            lines += _inline_if("else " + else_part)
        else:
            lines += [(0, "otherwise:")] + _indent(_body(else_part))
    return lines


def _simple(text):
    text = text.strip()
    if not text:
        return []
    # a trailing condition: print "Fizz" if number mod 3 is 0   (either order of clauses)
    if not _IF_START.match(text):
        mask = mask_of(text)
        for m in _TRAILING.finditer(text):
            if mask[m.start()] or m.start() == 0:
                continue
            core, kw, cond = text[:m.start()].rstrip(" ,"), _kw(m.group(1)), text[m.end():].strip()
            if not core or not cond:
                break
            if re.match(r"(?i)(let|create|define)\s+(?:a|an)\s", core):
                break
            return _trailing(core, kw, cond)
    # counting adverbs: print "hi" twice / add 1 to x 3 times
    # a count of several words: print "hi" twenty one times / add 1 to x three hundred times
    m = re.match(r"(?is)^(?P<head>.*\S)\s+times$", text)
    if m:
        head = m.group("head")
        first, end = None, len(head)
        for t in reversed(list(re.finditer(r"[A-Za-z]+", head))):
            if t.end() != end or t.group().lower() not in NUMBER_WORDS:
                break
            first, end = t, t.start() - 1
            while end >= 0 and head[end] in " \t-":
                end -= 1
            end += 1
        if first is not None and head[first.start():].count(" ") + head[first.start():].count("-") >= 1:
            core = head[:first.start()].rstrip(" \t-")
            count = number_run(re.split(r"[\s-]+", head[first.start():]))
            if count is not None and core and (first_word(core) in KEYWORDS or _register(core) is not None) and not mask_of(text)[first.start()]:
                return [(0, f"repeat {count} times:")] + _indent(_simple(core))
    m = re.match(r"(?is)^(?P<core>.+?)\s+(?:(?P<w>once|twice)|(?P<n>[\w.]+)\s+times)$", text)
    if m and not mask_of(text)[m.start("w") if m.group("w") else m.start("n")] and (first_word(m.group("core")) in KEYWORDS or _register(m.group("core")) is not None):
        core = m.group("core")
        count = {"once": 1, "twice": 2}.get((m.group("w") or "").lower()) if m.group("w") else m.group("n")
        if count == 1:
            return _simple(core)
        return [(0, f"repeat {count} times:")] + _indent(_simple(core))
    # modals: x must be at least 0 / x should be ... / x cannot be 0
    mod = _modal(text)
    if mod is not None:
        return mod
    return [(0, _finalize(_phrasal(_verbs(text))))]


def _trailing(core, kw, cond):
    """core <kw> cond [, otherwise ...]"""
    mask = mask_of(cond)
    e = find_top(_ELSE, cond, mask)
    if e:
        c, else_part = cond[:e.start()].strip(" ,"), cond[e.end():].strip(" ,")
        lines = [(0, f"{kw} {c}:")] + _indent(_simple(core))
        if _IF_START.match(else_part):
            lines += _inline_if("else " + else_part)
        else:
            lines += [(0, "otherwise:")] + _indent(_body(else_part))
        return lines
    return [(0, f"{kw} {cond}:")] + _indent(_simple(core))


# --------------------------------------------------------------------------------------------- modals (feature 16)
_MODAL = re.compile(r"(?i)\b(must|should|cannot)\b")


def _modal(text):
    if first_word(text) in ("print", "write", "show", "display", "say", "fail", "check", "warn", "set", "add", "put", "ask"):
        return None
    mask = mask_of(text)
    m = find_top(_MODAL, text, mask)
    if not m or m.start() == 0:
        return None
    subject, modal, rest = text[:m.start()].strip(), m.group(1).lower(), text[m.end():].strip()
    neg = modal == "cannot"
    if re.match(r"(?i)^not\b", rest):
        neg, rest = True, rest[3:].strip()
    mm = re.match(r"(?i)^(be|contain|contains|start with|starts with|end with|ends with)\b\s*(.*)$", rest)
    if not mm or not subject:
        raise SentenceError(f"after '{modal}' I expected 'be' or 'contain' or 'start with' or 'end with' "
                            f"(like: {subject or 'total'} {modal} be at least 0)")
    verb = {"be": "is", "contain": "contains", "contains": "contains", "start with": "starts with", "starts with": "starts with",
            "end with": "ends with", "ends with": "ends with"}[mm.group(1).lower()]
    tail = mm.group(2).strip()
    if verb == "is":
        cond = f"{subject} is {'not ' if neg else ''}{tail}"
    else:
        cond = f"{'not ' if neg else ''}({subject} {verb} {tail})"
    sentence = " ".join(text.split()).replace("\\", "\\\\").replace('"', '\\"').replace("{", "\\{")
    if modal == "should":
        return [(0, f"unless {cond}:"), (1, f'warn with "{sentence}"')]
    return [(0, f'check that {cond} because "{sentence}"')]


# --------------------------------------------------------------------------------------------- verbs (features 13, 14)
def _verbs(text):
    r = _register(text)
    if r is not None:
        text = r
    fw = first_word(text)
    low = text
    t = text
    if fw in ("show", "display", "say"):
        t = re.sub(r"(?i)^\s*(show|display|say)\b", "print", t, count=1)
    elif re.match(r"(?i)^\s*(make\s+sure|ensure|verify)\b", t):
        t = re.sub(r"(?i)^\s*(make\s+sure|ensure|verify)\b(\s+that\b)?", "check that", t, count=1)
    elif fw == "return":
        t = re.sub(r"(?i)^\s*return\b", "give back", t, count=1)
    elif fw == "continue":
        t = "skip"
    elif re.match(r"(?i)^\s*move\s+on\s*$", t):
        t = "skip"
    elif fw in ("increase", "decrease"):
        m = re.match(r"(?i)^\s*(increase|decrease)\s+(.+?)\s+by\s+(.+)$", t)
        if m:
            t = f"{'add' if m.group(1).lower() == 'increase' else 'subtract'} {m.group(3)} {'to' if m.group(1).lower() == 'increase' else 'from'} {m.group(2)}"
        else:
            m = re.match(r"(?i)^\s*(increase|decrease)\s+(.+)$", t)
            if m:
                t = f"{'add' if m.group(1).lower() == 'increase' else 'subtract'} 1 {'to' if m.group(1).lower() == 'increase' else 'from'} {m.group(2)}"
    elif fw in ("double", "halve", "triple"):
        m = re.match(r"(?i)^\s*(double|halve|triple)\s+(.+)$", t)
        if m:
            w = m.group(1).lower()
            t = {"double": f"multiply {m.group(2)} by 2", "triple": f"multiply {m.group(2)} by 3", "halve": f"divide {m.group(2)} by 2"}[w]
    elif fw == "take":
        t = re.sub(r"(?i)^\s*take\s+(.+?)\s+(?:away\s+from|out\s+of|from)\s+(.+)$", r"subtract \1 from \2", t, count=1)
    elif fw == "put":
        m = re.match(r"(?i)^\s*put\s+(.+?)\s+at\s+the\s+(end|back)\s+of\s+(.+)$", t)
        if m:
            t = f"append {m.group(1)} to {m.group(3)}"
        else:
            m = re.match(r"(?i)^\s*put\s+(.+?)\s+at\s+the\s+(start|beginning|front)\s+of\s+(.+)$", t)
            if m:
                t = f"insert {m.group(1)} into {m.group(3)} at 0"
            else:
                t = sub_top(r"\binto\b", "in", t)
    elif fw == "insert":
        m = re.match(r"(?i)^\s*insert\s+(.+?)\s+at\s+the\s+(end|back)\s+of\s+(.+)$", t)
        if m:
            t = f"append {m.group(1)} to {m.group(3)}"
        else:
            m = re.match(r"(?i)^\s*insert\s+(.+?)\s+at\s+the\s+(start|beginning|front)\s+of\s+(.+)$", t)
            if m:
                t = f"insert {m.group(1)} into {m.group(3)} at 0"
            else:
                m = re.match(r"(?i)^\s*insert\s+(.+?)\s+(before|after)\s+(?:item\s+)?(.+?)\s+of\s+(?:the\s+)?(.+)$", t)
                if m:
                    idx = m.group(3) if m.group(2).lower() == "before" else f"({m.group(3)}) + 1"
                    t = f"insert {m.group(1)} into {m.group(4)} at {idx}"
    elif fw in ("add", "append"):
        t = sub_top(r"\bonto\b", "to", t)
    elif fw == "remove":
        t = sub_top(r"\bout\s+of\b", "from", t)
    return t


# --------------------------------------------------------------------------------------------- registers (feature 22)
# The same action can be asked for in many voices.  Each rule: (voice, pattern, plain wording, what it is)
#   informal = chatty / slang,  formal = official / technical,  old = old-fashioned
_NAME = r"([A-Za-z_]\w*(?:\s+of\s+[A-Za-z_]\w*)?|item\s+\S+\s+of\s+\S+)"
_GUARD = {"is", "are", "of", "at", "contains", "contain", "does", "do", "and", "or", "=", "'s"}


def _w(*words):
    return "(?:" + "|".join(w.replace(" ", r"\s+") for w in sorted(words, key=len, reverse=True)) + ")"


REGISTER = [
    # printing
    ("informal", r"^(?:shout|yell|holler|blurt(?:\s+out)?|spit(?:\s+out)?|toss\s+out|call\s+out|put\s+out)\s+(.+)$", r"print \1", "print"),
    ("informal", r"^(?:show\s+me|let\s+me\s+see|lemme\s+see|lemme\s+look\s+at|let\s+me\s+look\s+at|print\s+out)\s+(.+)$", r"print \1", "print"),
    ("formal", r"^" + _w("output", "emit", "report", "announce", "present", "state", "echo", "render", "indicate", "communicate", "list out") + r"\s+(.+)$", r"print \1", "print"),
    ("old", r"^" + _w("behold", "lo and behold", "proclaim", "utter", "recite", "declare", "pronounce", "hear ye", "make known", "let it be known that", "hark") + r"\s*,?\s+(.+)$", r"print \1", "print"),
    # setting a value
    ("formal", r"^(?:assign|designate)\s+" + _NAME + r"\s+the\s+value\s+(?:of\s+)?(.+)$", r"set \1 to \2", "set"),
    ("formal", r"^(?:initiali[sz]e|reset)\s+" + _NAME + r"\s+to\s+(.+)$", r"set \1 to \2", "set"),
    ("formal", r"^(?:let|make)\s+(?!.*\b(?:called|named)\b)" + _NAME + r"\s+(?:be|equal|equals|become)\s+(.+)$", r"set \1 to \2", "set"),
    ("informal", r"^(?:stash|stick|chuck|shove|dump|park|toss|throw|slot|plop|pop)\s+(.+?)\s+(?:in|into|inside)\s+" + _NAME + r"\s*$", r"set \2 to \1", "set"),
    ("informal", r"^(?:stash|stick|chuck|shove|dump|park|toss|throw|slot|plop|pop)\s+(.+?)\s+(?:in|into|inside)\s+(.+?\s+at\s+.+)$", r"put \1 in \2", "put"),
    ("old", r"^" + _NAME + r"\s+(?:shall\s+(?:be|become)|will\s+(?:be|become)|should\s+(?:now\s+)?be|must\s+(?:now\s+)?be|becomes|doth\s+become|is\s+now|is\s+hereby|is\s+henceforth|now\s+is|gets)\s+(.+)$", r"set \1 to \2", "set"),
    # arithmetic
    ("informal", r"^(?:bump|up|pump\s+up|crank\s+up|ratchet\s+up)\s+(.+)$", r"increase \1", "increase"),
    ("formal", r"^(?:increment|augment|raise|elevate|escalate)\s+(.+)$", r"increase \1", "increase"),
    ("informal", r"^tack\s+(.+?)\s+on(?:to)?\s+(.+)$", r"add \1 to \2", "add"),
    ("informal", r"^tack\s+on\s+(.+?)\s+to\s+(.+)$", r"add \1 to \2", "add"),
    ("formal", r"^(?:decrement|diminish|reduce|lower|lessen|deplete|curtail)\s+(.+)$", r"decrease \1", "decrease"),
    ("formal", r"^deduct\s+(.+)$", r"subtract \1", "subtract"),
    ("informal", r"^(?:knock|shave|chip|trim|lop|scrape)\s+(.+?)\s+off(?:\s+of)?\s+(.+)$", r"subtract \1 from \2", "subtract"),
    ("informal", r"^take\s+(.+?)\s+off(?:\s+of)?\s+(.+)$", r"subtract \1 from \2", "subtract"),
    ("formal", r"^(?:scale|magnify|amplify)\s+(.+?)\s+by\s+(.+)$", r"multiply \1 by \2", "multiply"),
    ("informal", r"^square\s+([A-Za-z_]\w*)\s*$", r"multiply \1 by \1", "multiply"),
    # leaving loops and the program, giving answers back
    ("informal", r"^(?:bail(?:\s+out)?|break(?:\s+out)?(?:\s+of\s+(?:the|this)\s+loop)?|get\s+out|bust\s+out|cut\s+it\s+out|quit\s+(?:the|this)\s+loop|stop\s+looping)\s*$", "stop", "stop"),
    ("formal", r"^(?:cease|terminate|discontinue|exit|leave|abandon)\s+(?:the|this)\s+(?:loop|iteration|repetition)\s*$", "stop", "stop"),
    ("informal", r"^(?:carry\s+on|next\s+one|next\s+please|keep\s+going|go\s+on|on\s+we\s+go)\s*$", "skip", "skip"),
    ("formal", r"^(?:proceed|advance|go|jump|move|hop)\s+(?:on\s+)?to\s+the\s+next(?:\s+(?:one|item|round|iteration|repetition|turn|step))?\s*$", "skip", "skip"),
    ("informal", r"^(?:call\s+it\s+a\s+day|wrap\s+(?:it\s+)?up|that'?s\s+all(?:,?\s+folks)?|that\s+is\s+all|we\s+are\s+done|we're\s+done|pack\s+it\s+in|bow\s+out|bail\s+out\s+of\s+everything)\s*$", "finish", "finish"),
    ("formal", r"^(?:exit|quit|terminate|conclude|halt|end)\s*(?:the\s+program|the\s+run)?\s*$", "finish", "finish"),
    ("formal", r"^(?:exit|quit|terminate|conclude|halt|end|wrap\s+up|bow\s+out)\s+(?:the\s+program\s+)?with\s+(.+)$", r"finish with \1", "finish"),
    ("formal", r"^(?:hand\s+back|send\s+back|yield|produce|answer\s+with|come\s+back\s+with|respond\s+with|reply\s+with|result\s+in)\s+(.+)$", r"give back \1", "give back"),
    ("informal", r"^(?:throw\s+back|toss\s+back|chuck\s+back|gimme\s+back)\s+(.+)$", r"give back \1", "give back"),
    ("old", r"^(?:render\s+unto\s+me|return\s+thou|bestow)\s+(.+)$", r"give back \1", "give back"),
]
_REGISTER = [(v, re.compile(p, re.I), r, plain) for v, p, r, plain in REGISTER]
VOICE_VERBS = {"shout", "yell", "holler", "blurt", "spit", "toss", "call", "put", "show", "let", "lemme", "output", "emit", "report",
               "announce", "present", "state", "echo", "render", "indicate", "communicate", "list", "behold", "lo", "proclaim", "utter",
               "recite", "declare", "pronounce", "hear", "make", "hark", "assign", "designate", "initialise", "initialize", "reset",
               "stash", "stick", "chuck", "shove", "dump", "park", "throw", "slot", "plop", "pop", "bump", "up", "pump", "crank",
               "ratchet", "increment", "augment", "raise", "elevate", "escalate", "tack", "decrement", "diminish", "reduce", "lower",
               "lessen", "deplete", "curtail", "deduct", "knock", "shave", "chip", "trim", "lop", "scrape", "scale", "magnify",
               "amplify", "square", "bail", "break", "get", "bust", "cut", "quit", "stop", "cease", "terminate", "discontinue", "exit",
               "leave", "abandon", "carry", "next", "keep", "go", "on", "proceed", "advance", "jump", "move", "hop", "wrap", "that",
               "we", "pack", "bow", "conclude", "halt", "end", "hand", "send", "yield", "produce", "answer", "come", "respond", "reply",
               "result", "return", "bestow", "pretty"}
VOICE_STARTS = {"shout", "yell", "holler", "blurt", "spit", "output", "emit", "report", "announce", "present", "echo", "indicate",
                "communicate", "behold", "proclaim", "utter", "recite", "declare", "pronounce", "hark", "assign", "designate",
                "initialise", "initialize", "stash", "stick", "chuck", "shove", "dump", "park", "slot", "plop", "bump", "increment",
                "augment", "elevate", "escalate", "tack", "decrement", "diminish", "reduce", "lessen", "deplete", "curtail", "deduct",
                "knock", "chip", "lop", "scrape", "scale", "magnify", "amplify", "square", "bail", "bust", "cease", "discontinue",
                "abandon", "conclude", "halt", "hop", "yield", "produce", "respond", "reply"}


# words that can start one of the statements above (also after ', and ...' and before a trailing 'twice' / 'if ...')
VOICE_STARTS |= {"lo", "hear", "shave", "trim", "reset", "raise", "lower", "state", "list", "render", "pump", "crank", "ratchet", "pop",
                 "toss", "throw", "spit", "wrap", "pack", "bow", "quit", "exit", "leave", "terminate", "end", "carry", "proceed", "advance",
                 "come", "send", "hand", "answer", "result", "bestow", "pronounce", "hark", "lessen", "deduct", "knock", "square", "scale"}
STMT_VERBS.update(VOICE_STARTS)
KEYWORDS.update(VOICE_STARTS)


def _register(text):
    """one action in another voice -> the plain sentence; None when the text is already plain"""
    fw = first_word(text)
    nxt = text.split(None, 1)[1].split(None, 1)[0].lower() if len(text.split(None, 1)) > 1 else ""
    variable_like = (nxt in _GUARD and fw not in ("we", "that", "call", "wrap", "pack", "bow", "lo")) or nxt.startswith(("=", "(", "'"))
    for voice, rx, repl, plain in _REGISTER:
        if variable_like and not rx.pattern.startswith("^" + _NAME):
            continue                                     # 'report is 5', 'state of x' : the word is a variable
        m = rx.match(text.strip())
        if m:
            return m.expand(repl) if "\\" in repl else repl
    return None


def register_note(text):
    """for --explain: 'bump' is an informal way to say 'increase'  (None if the text is not in another voice)"""
    t = text.strip()
    for voice, rx, repl, plain in _REGISTER:
        m = rx.match(t)
        if m:
            groups = m.regs[1:]
            if not groups:
                phrase = t
            elif groups[0][0] > 0:
                phrase = t[:groups[0][0]].strip(" ,")
            elif len(groups) > 1:
                phrase = t[groups[0][1]:groups[1][0]].strip()
            else:
                phrase = t[groups[0][1]:].strip()
            say = {"informal": "an informal way", "formal": "a formal way", "old": "an old-fashioned way"}[voice]
            return f"'{phrase}' is {say} to say '{plain}'"
    return None


# --------------------------------------------------------------------------------------------- phrasal verbs (feature 15)
def _phrasal(text):
    t = text
    t = sub_top(r"\badd\s+up\b(?=\s+\S)", "sum of", t) if first_word(t) != "add" else (
        re.sub(r"(?i)^(\s*)add\s+up\s+(.+)$", r"\1print sum of \2", t))
    t = sub_top(r"\blook\s+up\s+(\"[^\"]*\"|[\w.]+)\s+in\s+(?:the\s+)?(\w+)", r"\2 at \1", t)
    t = sub_top(r"\blook\s+(\"[^\"]*\"|[\w.]+)\s+up\s+in\s+(?:the\s+)?(\w+)", r"\2 at \1", t)
    t = sub_top(r"\bround\s+up\b", "ceiling of", t)
    t = sub_top(r"\bround\s+down\b", "floor of", t)
    t = sub_top(r"\bround\s+off\s+(\S+)\s+to\s+(\S+)\s+places?\b", r"rounded \1 to \2 places", t)
    t = sub_top(r"\bround\s+off\b", "round of", t)
    return t


# --------------------------------------------------------------------------------------------- the entry points
def _sentence(text):
    text = strip_lead(_strip_punct(strip_lead(text)))
    if not text:
        return []
    text = _contractions(text)
    text = _fillers(text)
    if not text:
        return []
    text = _comparisons(text)
    q = _question(text)
    if q is not None:
        return q
    text = sub_top(r"\byet\b", "but", text)
    if re.search(r"(?i)\bnot\s+only\b", text):
        text = sub_top(r"\bnot\s+only\b", "both", text)
        text = sub_top(r"\bbut\s+also\b", "and", text)
    if text.endswith(":"):
        return [(0, _finalize(_header(text[:-1].strip()) + ":"))]
    return _statement(text)


_BLOCK_HEAD = re.compile(r"(?i)(structurally|simply),")


def normalize(stmt):
    """one source statement -> [(depth, text), ...]"""
    stmt = strip_lead(stmt)
    if _BLOCK_HEAD.fullmatch(stmt):
        return [(0, stmt)]
    out = []
    for seg in split_top(stmt, ";"):
        seg = seg.strip()
        if seg:
            out += _sentence(seg)
    return out


def needs_continuation(stmt):
    """a line that ends in a comma, 'and', 'or' or 'then' goes on the next line"""
    s = strip_lead(stmt)
    if not s or s.endswith(":") or _BLOCK_HEAD.fullmatch(s):
        return False
    return s.endswith(",") or re.search(r"(?i)\b(and|or|then)$", s) is not None
