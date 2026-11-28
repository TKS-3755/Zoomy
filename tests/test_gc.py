"""the garbage collector of the native heap: a loop that builds millions of short texts must finish in bounded memory
where the same program without the collector (ZOOMY_NO_GC=1) runs out of heap, and live data must survive collections."""
import os, resource, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Z = [sys.executable, os.path.join(HERE, "zoomy.py")]
fails = 0
def check(name, ok, info=""):
    global fails
    if not ok:
        fails += 1
        print("FAIL", name, str(info)[:500])
CHURN = """Let a string be called s
Let a number be called i
Let a number be called total
set total to 0
for i from 1 to 14000000:
    set s to "step {i} of the run"
    add length of s to total
print total
"""
LIVE = """Create an array named keep
Let a string be called s
Let a number be called i
Let a number be called total
set total to 0
for i from 1 to 1500000:
    set s to "item {i} of the run"
    if i mod 5000 is 0:
        append s to keep
    add length of s to total
print total
print length of keep
print the first of keep
print the last of keep
"""
def build(path, name, env=None):
    exe = os.path.join(os.path.dirname(path), name)
    b = subprocess.run(Z + [path, "--native", "-o", exe], capture_output=True, text=True, env={**os.environ, **(env or {})})
    check(name + " builds natively", "[Success]" in b.stdout, b.stdout + b.stderr)
    return exe
def run(exe):
    before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    p = subprocess.run([exe], capture_output=True, text=True)
    return p, resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
with tempfile.TemporaryDirectory() as d:
    src = os.path.join(d, "churn.zmy"); open(src, "w").write(CHURN)
    p, rss = run(build(src, "churn"))
    check("churn finishes", p.returncode == 0 and p.stdout.strip() == "324888897", (p.returncode, p.stdout, p.stderr))
    check("churn memory stays bounded", rss < 700 * 1024, rss // 1024)
    p, _ = run(build(src, "churn_nogc", {"ZOOMY_NO_GC": "1"}))
    check("without the collector the heap fills up", p.returncode != 0 and "out of memory" in p.stderr, (p.returncode, p.stderr))
    src = os.path.join(d, "live.zmy"); open(src, "w").write(LIVE)
    for stress in (False, True):
        env = {"ZOOMY_GC_STRESS": "1"} if stress else {}
        ref = subprocess.run(Z + [src, "--python", "--run"], capture_output=True, text=True, env={**os.environ, "ZOOMY_NO_HEAP": "1"})
        want = "\n".join(l for l in ref.stdout.split("\n") if not l.startswith("[Success]")).strip()
        p, _ = run(build(src, "live", env))
        check("live data survives (%s)" % ("collect at every safe point" if stress else "normal"), p.returncode == 0 and p.stdout.strip() == want, (p.stdout, want))
print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
