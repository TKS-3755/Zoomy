"""zoomy.py fmt: it must never change what a program does, a second pass must change nothing, and it must do what it says."""
import glob, os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import zoomy_fmt

fails = 0


def check(name, ok, detail=""):
    global fails
    if not ok:
        fails += 1
        print(f"FAIL {name}: {detail}")


MESSY = """(a demo)   
Let a number be called x
Let a number be called total



set x to 1, then show x
Please print x.
print "hi" twenty one times
print "big" if x is above 3     (a trailing comment)
whenever x is at least 5, print "many", otherwise print "few"
as long as x is below 3:
\tdouble x
   (about to subtract)
Take 2 away from x
"""
want = """(a demo)
Let a number be called x
Let a number be called total

set x to 1
print x
print x
repeat 21 times:
    print "hi"
if x is above 3:
    print "big"    (a trailing comment)
if x is at least 5:
    print "many"
otherwise:
    print "few"
while x is below 3:
    multiply x by 2
(about to subtract)
subtract 2 from x
"""
got = zoomy_fmt.format_text(MESSY, "messy.zmy")
check("messy program", got == want, "\n" + got)
check("second pass changes nothing", zoomy_fmt.format_text(got, "messy.zmy") == got)
# the 5 lines that were plain are word for word the same
plain = "Let a number be called x\nset x to 1\nprint x\n    print x    (indented comment)\n"
# a plain statement over several lines keeps its line breaks
multi = "Let a number be called x\nLet a number be called y\nif x is 0 and\n        y is 0:\n    print 1\n"
got = zoomy_fmt.format_text(multi, "m.zmy")
check("multi-line statement kept", "if x is 0 and\n" in got and "y is 0:\n    print 1" in got, got)
check("multi-line statement second pass", zoomy_fmt.format_text(got, "m.zmy") == got, got)

# every program in the repository: formatting keeps the compiled code, and a second pass changes nothing
paths = sorted(glob.glob(os.path.join(ROOT, "examples", "*.zmy")) + glob.glob(os.path.join(ROOT, "nocalc", "*.zmy")) + glob.glob(os.path.join(ROOT, "nodoom", "*.zmy"))
               + glob.glob(os.path.join(ROOT, "examples", "*", "*.zmy")))
for path in paths:
    new, problem = zoomy_fmt.format_file(path)
    check("verified: " + os.path.relpath(path, ROOT), problem is None, problem)
    if problem is None:
        again = zoomy_fmt.format_text(new, os.path.basename(path))
        check("idempotent: " + os.path.relpath(path, ROOT), again == new)

# the command
with tempfile.TemporaryDirectory() as d:
    f = os.path.join(d, "t.zmy")
    open(f, "w").write(MESSY)
    z = [sys.executable, os.path.join(ROOT, "zoomy.py"), "fmt"]
    r = subprocess.run(z + [f, "--check"], capture_output=True, text=True)
    check("--check finds a messy file", r.returncode == 1 and "would be reformatted" in r.stdout, r.stdout)
    r = subprocess.run(z + [f], capture_output=True, text=True)
    check("prints the formatted program", r.returncode == 0 and r.stdout == want, r.stdout)
    check("printing leaves the file alone", open(f).read() == MESSY)
    r = subprocess.run(z + [f, "--diff"], capture_output=True, text=True)
    check("--diff", "+repeat 21 times:" in r.stdout, r.stdout)
    r = subprocess.run(z + [f, "-w"], capture_output=True, text=True)
    check("--write", open(f).read() == want and "formatted" in r.stdout, r.stdout)
    r = subprocess.run(z + [f, "--check"], capture_output=True, text=True)
    check("--check passes after --write", r.returncode == 0, r.stdout)
    bad = os.path.join(d, "bad.zmy")
    open(bad, "w").write("set x to 1 then if\nprint x\n   print y\n")
    r = subprocess.run(z + [bad], capture_output=True, text=True)
    check("a program that cannot be read is refused", r.returncode == 1 and "[Error]" in r.stdout, r.stdout)
print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
