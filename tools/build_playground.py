#!/usr/bin/env python3
"""Builds playground.html: one page with the whole Zoomy compiler (the Python backend) inside, run by Pyodide in the browser.
    python3 tools/build_playground.py [out.html] [--pyodide URL]
The page loads Pyodide from a CDN by default (needs a connection the first time); --pyodide can point at your own copy."""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full"
FILES = ["zoomy_py.py", "zoomy_sentence.py", "zoomy_grammar.py", "zoomy_runtime.py", "zoomy_big.py", "zoomy_consts.py",
         "zoomy_fmt.py", "zoomy_suggest.py", "zoomy_bignum.zmy", "zoomy_bigdec.zmy", "zoomy_bdmath.zmy"]
EXAMPLES = ["hello", "fizzbuzz", "factorial", "primes", "temperatures", "wordcount", "guess", "tictactoe", "hangman"]


def build(out, pyodide=PYODIDE):
    sources = {f: open(os.path.join(HERE, f), encoding="utf-8").read() for f in FILES}
    sources["playground_glue.py"] = open(os.path.join(HERE, "tools", "playground_glue.py"), encoding="utf-8").read()
    examples = {}
    for n in EXAMPLES:
        p = os.path.join(HERE, "examples", n + ".zmy")
        if os.path.isfile(p):
            examples[n] = open(p, encoding="utf-8").read()
    page = open(os.path.join(HERE, "tools", "playground_template.html"), encoding="utf-8").read()
    dump = lambda o: json.dumps(o).replace("</", "<\\/")
    page = page.replace("__PYODIDE__", pyodide.rstrip("/")).replace("__SOURCES__", dump(sources)).replace("__EXAMPLES__", dump(examples))
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    return len(page)


if __name__ == "__main__":
    a = sys.argv[1:]
    pyo = PYODIDE
    if "--pyodide" in a:
        i = a.index("--pyodide"); pyo = a[i + 1]; del a[i:i + 2]
    out = a[0] if a else os.path.join(HERE, "playground.html")
    print(f"wrote {out} ({build(out, pyo)} bytes)")
