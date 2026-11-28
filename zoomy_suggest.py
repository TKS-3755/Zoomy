"""Whole-sentence suggestions: when a line cannot be read, try small repairs of that one line
(a misspelt keyword, a missing little word, a stray word, a missing colon) and offer one only if the
program then gets past that line.  The compiler itself is the judge, so a suggestion is never a guess
that does not read."""
import difflib
import os
import re
import time

import zoomy_py

WORDS = ["set", "add", "subtract", "multiply", "divide", "print", "write", "append", "insert", "remove", "sort", "reverse",
         "clear", "read", "delete", "store", "show", "display", "say", "return", "continue", "increase", "decrease", "double",
         "halve", "give", "stop", "skip", "finish", "define", "repeat", "while", "until", "for", "each", "from", "otherwise",
         "else", "unless", "if", "then", "times", "with", "back", "called", "named", "slots", "into", "than", "equal", "greater",
         "less", "global", "include", "make", "create", "let", "check", "ask", "wait", "call", "to", "by", "in"]
LITTLE = ["to", "by", "from", "in", "with", "as", "times", "then", "and", "the", "is", "of", "called", "named", "back"]
HEADS = ("if", "while", "for", "repeat", "define", "otherwise", "else", "unless", "until", "when", "whenever", "try", "always", "routine", "action")
MAX_TRIES = 400
MAX_SECONDS = 3.0          # every try re-reads the whole program, so a big program gets fewer tries, never a long wait


def _gate(lines, idx, new, filename, bad_line):
    """does the program read past this line once line idx is replaced?"""
    trial = lines[:idx] + [new] + lines[idx + 1:]
    try:
        prog = zoomy_py.Program(filename)
        prog.load_text("\n".join(trial) + "\n", filename)
        zoomy_py.compile_python(prog)
        return True
    except zoomy_py.ZoomyError as e:
        return e.line is not None and e.line != bad_line      # an error elsewhere is a later stage, not this line
    except Exception:
        return False


def _edits(body, names):
    """candidate rewrites of one line body (no indentation), cheapest first"""
    m = re.match(r"^(.*?)([.:!?]*)$", body, re.S)
    core, tail = m.group(1), m.group(2)
    words = core.split(" ")
    out = []

    def add(ws, t=tail):
        s = " ".join(ws) + t
        if s != body and s not in out:
            out.append(s)

    first = words[0].lower() if words else ""
    # 1. a misspelt keyword
    for i, w in enumerate(words):
        lw = w.lower()
        if len(lw) < 3 or lw in WORDS or lw in names or not lw.isalpha():
            continue
        for c in difflib.get_close_matches(lw, WORDS, n=2, cutoff=0.75):
            add(words[:i] + [c] + words[i + 1:])
    # 2. a missing or extra colon on a block header
    if first in HEADS:
        add(words, ":")
    elif tail == ":":
        add(words, "")
    # 3. a missing little word
    for i in range(1, len(words) + 1):
        for l in LITTLE:
            add(words[:i] + [l] + words[i:])
    # 4. a stray word
    if len(words) > 1:
        for i in range(len(words)):
            add(words[:i] + words[i + 1:])
    # 5. a typo together with a colon
    typo = list(out[:3])
    for t in typo:
        mm = re.match(r"^(.*?)([.:!?]*)$", t, re.S)
        if mm.group(1).split(" ")[0].lower() in HEADS and mm.group(2) != ":":
            add(mm.group(1).split(" "), ":")
    return out


def suggest(text, filename, err):
    """a whole replacement line for the line the error points at, or None"""
    line = getattr(err, "line", None)
    if not line:
        return None
    lines = text.splitlines()
    if not 1 <= line <= len(lines):
        return None
    raw = lines[line - 1]
    body = raw.strip()
    if not body or body.startswith(("#", "//")):
        return None
    indent = raw[:len(raw) - len(raw.lstrip())]
    names = {w.lower() for i, l in enumerate(lines) if i != line - 1 for w in re.findall(r"[A-Za-z_]+", l)}   # words used elsewhere may be names
    tries = 0
    t_end = time.time() + MAX_SECONDS
    for cand in _edits(body, names):
        tries += 1
        if tries > MAX_TRIES or time.time() > t_end:
            break
        if _gate(lines, line - 1, indent + cand, filename, line):
            return cand
    return None


def hint(path_or_text, err, is_text=False):
    """the 'Did you mean' line to print under an error message, or ''"""
    try:
        if is_text:
            text, filename = path_or_text, "<text>"
        else:
            if not os.path.isfile(path_or_text):
                return ""
            with open(path_or_text, encoding="utf-8") as f:
                text = f.read()
            filename = path_or_text
        if getattr(err, "file", None) and os.path.abspath(err.file) != os.path.abspath(filename):
            return ""                                    # the error is in an included file
        if "Did you mean" in str(err):
            return ""
        s = suggest(text, filename, err)
        return f"        Did you mean this sentence: {s}" if s else ""
    except Exception:
        return ""
