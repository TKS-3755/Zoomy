"""'And', 'Also', 'Then' and 'After that,' at the start of a sentence are ignored (also before block headers)."""
import os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PLAIN = """Let a number be called x
Let a number be called y
set x to 1
set y to 2
print x
print y
if x is 1:
    print "one"
    print "still"
otherwise:
    print "no"
simply,
    set z to 3
    print z
structurally,
    Let a number be called w
    set w to 4
    print w
while x is below 3:
    add 1 to x
    print x
set y to 5, then print y
"""
LEADS = ["And ", "Also ", "Then ", "After that, ", "and also ", "Also, then "]


def decorate(text):
    out, n = [], 0
    for line in text.splitlines():
        body = line.lstrip()
        if body and not body.startswith(("otherwise", "Let ")) or body.startswith("Let "):
            ind = line[:len(line) - len(body)]
            out.append(ind + LEADS[n % len(LEADS)] + body)
            n += 1
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def run(src, backend):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.zmy")
        open(p, "w").write(src)
        env = dict(os.environ, ZOOMY_BACKEND=backend)
        r = subprocess.run([sys.executable, os.path.join(ROOT, "zoomy.py"), p, "--run"], capture_output=True, text=True, env=env, cwd=d)
        return r.returncode, "\n".join(l for l in r.stdout.splitlines() if not l.startswith("[Success]"))


fails = 0
for backend in ("native", "python"):
    a, b = run(PLAIN, backend), run(decorate(PLAIN), backend)
    if a != b or a[0] != 0:
        fails += 1
        print("FAIL", backend, a, b)
print(f"{fails} failure(s)" if fails else "0 failures")
