"""Zoomy 8: `zoomy.py fmt` - one consistent style for Zoomy source.

What it does (and only this):
  * a line that is already plain is kept word for word; it is only re-indented to 4 spaces per level;
  * a line in another voice (`bump x by 3`, `print x if x is 3`, `loop 5 times:`, `Kindly initialise x to 4`, several actions on one line)
    is rewritten as the plain statements the sentence layer reads it as (the same text `--explain` shows);
  * comments stay (a whole-line comment goes with the statement below it, a trailing comment stays at the end of the line);
  * runs of blank lines become one, trailing spaces go, the file ends with one newline.
It never changes what a program does: unless told not to, `format_file` compiles the original and the formatted text and
refuses to produce the result when the generated code differs."""
import os
import re

import zoomy_py
import zoomy_sentence as zs


def _compile(text, filename):
    """the generated Python without line numbers, or the error text - for comparing"""
    try:
        prog = zoomy_py.Program(filename)
        prog.load_text(text, filename)
        src, _ = zoomy_py.compile_python(prog)
        src = re.sub(r"__q\d+", "__q", src)                  # the numbers of the hidden question variables count up per process
        return "ok", "\n".join(l for l in src.splitlines() if not l.startswith(("_ZLINES", "_ZNAME")))
    except zoomy_py.ZoomyError as e:
        return "error", re.sub(r"\bline \d+|:\d+:", "", str(e))
    except Exception as e:                                         # a program the front end cannot take at all
        return "error", type(e).__name__


def _internal(t):
    """sentences the sentence layer hands to later stages in an inner wording (questions, 'must contain' checks): never shown to people"""
    return t.startswith(("__", "check that", "warn with")) or t.endswith(".:")


def format_text(text, filename="program", frozen=(), rewritten=None):
    """the formatted text; raises ZoomyError if the program cannot even be read.
    frozen: first-line numbers of statements that must stay as written; rewritten: a list that collects the first lines that were rewritten"""
    recs = []
    zoomy_py.parse_blocks(text, filename, recs)
    lines = text.expandtabs(4).splitlines() if "\t" in text else text.splitlines()
    raw_lines = text.splitlines()
    by_first = {r[0]: r for r in recs}
    out = []
    stack = []                                   # original indents of the open blocks
    pending_comments = []
    i = 1

    def depth_for(indent):
        while stack and stack[-1] > indent:
            stack.pop()
        if not stack or stack[-1] < indent:
            stack.append(indent)
        return len(stack) - 1

    def flush_comments(depth):
        for c in pending_comments:
            out.append("    " * depth + c)
        pending_comments.clear()

    while i <= len(raw_lines):
        raw = raw_lines[i - 1]
        body = raw.strip()
        if i in by_first:
            first, last, written, sentences = by_first[i]
            ex = raw.expandtabs(4)
            depth = depth_for(len(ex) - len(ex.lstrip()))
            flush_comments(depth)
            # trailing comments of the statement's lines
            trail = []
            for k in range(first, last + 1):
                l = raw_lines[k - 1].rstrip()
                code = zoomy_py.strip_comment(raw_lines[k - 1]).rstrip()
                if len(l) > len(code) and code.strip():
                    trail.append(l[len(code):].strip())
            joined = " ".join(written)
            same = len(sentences) == 1 and sentences[0][1].lower() == joined.lower()
            if same or first in frozen or any(_internal(t) for _, t in sentences):
                # already plain (or not for me to touch): keep the author's words and line breaks
                base = len(raw_lines[first - 1].expandtabs(4)) - len(raw_lines[first - 1].expandtabs(4).lstrip())
                text_out = []
                for k in range(first, last + 1):
                    l = zoomy_py.strip_comment(raw_lines[k - 1]).rstrip().expandtabs(4)
                    if l.strip():
                        text_out.append("    " * depth + " " * max(0, len(l) - len(l.lstrip()) - base) + l.strip())
            else:
                if rewritten is not None:
                    rewritten.append(first)
                text_out = ["    " * (depth + d) + t for d, t in sentences]
                # sentences that start with a word of the source keep a source capital ('Let', 'Create', 'Print')
                if len(sentences) == 1 and written[0].split()[0].lower() == sentences[0][1].split()[0].lower():
                    w0 = written[0].split()[0]
                    text_out[0] = "    " * (depth + sentences[0][0]) + w0 + sentences[0][1][len(w0):]
            if trail:
                text_out[-1] += "    " + " ".join(trail)
            out += text_out
            i = last + 1
            continue
        if not body:
            if out and out[-1] != "":
                out.append("")
            i += 1
            continue
        pending_comments.append(body)                                    # a comment line: goes with the next statement
        i += 1
    # comments at the end of the file
    for c in pending_comments:
        out.append(c)
    while out and out[-1] == "":
        out.pop()
    # comments sit right above their statement, but a blank line that came between them stays above the comments
    return "\n".join(out) + "\n"


def _squash_comment_gaps(text):
    return text


def format_file(path, verify=True):
    """returns (formatted text, problem or None); the problem says why the original must stay as it is"""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        new = format_text(text, os.path.basename(path))
    except zoomy_py.ZoomyError as e:
        return text, f"cannot read the program: {e}"
    if verify:
        before = _compile(text, path)
        if _compile(new, path) != before:
            # some rewrite changes the meaning: find them (halving the set of rewritten statements) and leave those as written
            changed = []
            format_text(text, os.path.basename(path), rewritten=changed)
            good = _safe_rewrites(text, path, before, changed)
            new = format_text(text, os.path.basename(path), frozen=set(changed) - set(good))
            if _compile(new, path) != before:
                return text, "the formatted program would not compile to the same code (not written; this is a bug in 'fmt', please report the file)"
    return new, None


def _safe_rewrites(text, path, before, candidates):
    """the subset of CANDIDATES (first-line numbers) whose rewriting keeps the compiled code"""
    def ok(subset):
        frozen = set(candidates) - set(subset)
        return _compile(format_text(text, os.path.basename(path), frozen=frozen), path) == before
    if not candidates or ok(candidates):
        return list(candidates)
    if len(candidates) == 1:
        return []
    mid = len(candidates) // 2
    left, right = _safe_rewrites(text, path, before, candidates[:mid]), _safe_rewrites(text, path, before, candidates[mid:])
    both = left + right
    return both if ok(both) else left
