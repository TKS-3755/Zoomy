"""Zoomy 6.2 wording: the older phrasings are errors, and the migrator turns them into the new ones."""
import os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
import migrate as mg

OLD = """from now on, use integers instead of floats
Let a number be called x
Let a number be called y
Let a number be called c
set x to 0b101100
calculate absolute value of x store in y
print y
calculate square root of 49 store in y
print y
count set bits of x store in y
print y
trailing zeros of x store in y
print y
isolate lowest bit of x store in y
print y
reverse bytes of x store in y
print y
extract bits of x using mask 0b1100 store in y
print y
deposit bits of x using mask 0b1100 store in y
print y
convert character '7' to a number and store in y
print y
set y to absolute value of -5
print y
print "calculate absolute value of x store in y"
"""
fails = 0
def build_run(src):
    d = tempfile.mkdtemp()
    f = os.path.join(d, "t.zmy"); open(f, "w").write(src)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "zoomy.py"), f, "--native", "-o", os.path.join(d, "t")], capture_output=True, text=True)
    if r.returncode: return "BUILD FAIL " + r.stdout + r.stderr
    return subprocess.run([os.path.join(d, "t")], capture_output=True, text=True).stdout

new, _ = mg.migrate(OLD, "t.zmy", wording_only=True)
again, _ = mg.migrate(new, "t.zmy", wording_only=True)
for name, ok in [("idempotent", again == new),
                 ("article added", "calculate the absolute value of x and store the result in y" in new),
                 ("string untouched", 'print "calculate absolute value of x store in y"' in new),
                 ("migrated program builds", "BUILD FAIL" not in build_run(new))]:
    print(("ok   " if ok else "FAIL ") + name); fails += (not ok)
for line in [l for l in OLD.split("\n") if l and not l.startswith(("from", "Let", "set", "print"))] + ["read byte c", "read char c", "set y to 1\ncalculate x plus 1 store in y"]:
    src = "from now on, use integers instead of floats\nLet a number be called x\nLet a number be called y\nLet a number be called c\n" + line + "\n"
    out = build_run(src)
    ok = out.startswith("BUILD FAIL")
    print(("ok   " if ok else "FAIL ") + "old wording is an error: " + line.split("\n")[-1]); fails += (not ok)
print("%d failure(s)" % fails if fails else "0 failures")
sys.exit(1 if fails else 0)
