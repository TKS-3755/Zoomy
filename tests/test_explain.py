"""--explain (how each line was read) and --trace (each line as it runs, with the variables it changed)."""
import os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = 0


def zoomy(src, *flags):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.zmy")
        open(p, "w").write(src)
        r = subprocess.run([sys.executable, os.path.join(ROOT, "zoomy.py"), p, *flags], capture_output=True, text=True, timeout=120)
        return r.returncode, r.stdout, r.stderr


def check(name, ok, detail=""):
    global fails
    if not ok:
        fails += 1
        print(f"FAIL {name}: {detail}")


EXPLAIN = """(a demo)
Let a number be called x
set x to 1, then show x
Please print x.
print "hi" twenty one times
print "big" if x is above 3
whenever x is at least 5, print "many", otherwise print "few"
as long as x is below 3:
    double x
Take 2 away from x
"""
rc, out, _ = zoomy(EXPLAIN, "--explain")
check("explain exit code", rc == 0, rc)
for want in ("= Let a number be called x", "I read this as:", "print x", "'Please' is only a polite or chatty opening", "'show' means 'print'",
             "repeat 21 times:", "'twenty one' is read as the number 21", "if x is above 3:", "puts the action under that condition",
             "'whenever' means 'if'", "'as long as' means 'while'",
             "multiply x by 2", "subtract 2 from x", "(a demo)", "statement line(s)"):
    check("explain: " + want, want in out, out)
# a line that is already plain is not explained; a broken line still gets the lines before it
rc, out, _ = zoomy("set x to 1\nprint x\n", "--explain")
check("explain plain", "I read this as" not in out and "2 already plain" in out, out)
rc, out, _ = zoomy("Let a number be called x\nif x is 5\n", "--explain")
check("explain error", "[Error]" in out and "= Let a number be called x" in out, out)

TRACE = """Let a number be called total
Let a number be called i
set total to 0
for i from 1 to 3:
    add i to total
define sq with n:
    give back n * n
print sq(total)
print "done"
"""
rc, out, _ = zoomy(TRACE, "--trace")
check("trace exit", rc == 0, rc)
lines = out.splitlines()
for want in ("[line 1] Let a number be called total", "[line 5] add i to total", "      total = 1", "      total = 3", "      total = 6", "      i = 2",
             "[line 8] print sq(total)", "        n = 6", "36", "done"):
    check("trace: " + want, want in lines or any(want in l for l in lines), out)
check("trace: a define is not a step", not any("[line 6]" in l for l in lines), out)
check("trace: output order", lines.index("36") < lines.index("done"), out)
rc, out, _ = zoomy(TRACE, "--trace=3")
check("trace limit", "[trace stopped after 3 steps" in out and "done" in out, out)
rc, out, _ = zoomy('Let a number be called x\nset x to 1\nfinish with 3\n', "--trace")
check("trace exit code", rc == 3, rc)
rc, out, _ = zoomy('print 1\nfail with "boom"\n', "--trace")
check("trace runtime error", rc != 0, rc)
rc, out, err = zoomy('Let a number be called x\nset x to "a"\n', "--trace")
check("trace compile error", rc == 1 and "[Error]" in out, out)
print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
