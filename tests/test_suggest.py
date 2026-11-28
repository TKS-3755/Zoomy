"""whole-sentence suggestions: 'Did you mean this sentence: ...' appears only when the repaired line really reads"""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Z = [sys.executable, os.path.join(HERE, "zoomy.py")]
fails = 0
def check(name, ok, info=""):
    global fails
    if not ok:
        fails += 1
        print("FAIL", name, info)
HEAD = "Let a number be called x\nLet a number be called n\nset x to 5\nset n to 1\n"
CASES = [
    ("repeat 3 time:\n    print x\n", "repeat 3 times:"),
    ("while x is less than 9\n    add 1 to x\n", "while x is less than 9:"),
    ("add 1 x\n", "add 1 to x"),
    ("prnt x\n", "print x"),
    ("if x is 5\n    print x\n", "if x is 5:"),
    ("set x 7\n", "set x to 7"),
    ("print x please now\n", None),          # reads already or has no repair: never a made-up suggestion
    ("blorp zibble quux\n", None),           # nothing close: say nothing rather than guess
]
with tempfile.TemporaryDirectory() as d:
    for i, (body, want) in enumerate(CASES):
        p = os.path.join(d, f"t{i}.zmy")
        open(p, "w").write(HEAD + body)
        r = subprocess.run(Z + [p, "--python"], capture_output=True, text=True, cwd=d)
        out = r.stdout
        got = None
        for l in out.splitlines():
            if "Did you mean this sentence:" in l:
                got = l.split("Did you mean this sentence:", 1)[1].strip()
        if want is None:
            check(f"no guess for {body!r}", got is None, out)
        else:
            check(f"suggest for {body!r}", got == want, out)
print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
