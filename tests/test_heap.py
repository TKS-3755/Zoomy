"""text, lists and tables in the native compiler: every program in tests/heap_cases is built natively and by the
Python backend (the reference); the output and the exit code must be the same.  The native build must really happen
(no quiet fallback), so a program the rewrite cannot take fails here."""
import glob, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Z = [sys.executable, os.path.join(HERE, "zoomy.py")]
fails = 0
def check(name, ok, info=""):
    global fails
    if not ok:
        fails += 1
        print("FAIL", name, str(info)[:600])
cases = sorted(glob.glob(os.path.join(HERE, "tests", "heap_cases", "*.zmy")))
quick = "--quick" in sys.argv
with tempfile.TemporaryDirectory() as d:
    for path in cases:
        name = os.path.basename(path)[:-4]
        inp = path[:-4] + ".in"
        data = open(inp, "rb").read() if os.path.exists(inp) else b""
        ref = subprocess.run(Z + [path, "--python", "--run"], input=data, capture_output=True, cwd=d, env={**os.environ, "ZOOMY_NO_HEAP": "1"})
        exe = os.path.join(d, name)
        want = b"\n".join(l for l in ref.stdout.split(b"\n") if not l.startswith(b"[Success]"))
        # the second round collects garbage at every safe point of the top level code (ZOOMY_GC_STRESS)
        for stress in ((False,) if quick else (False, True)):
            tag = name + (" (collect at every safe point)" if stress else "")
            b = subprocess.run(Z + [path, "--native", "-o", exe], capture_output=True, text=True, cwd=d,
                               env={**os.environ, **({"ZOOMY_GC_STRESS": "1"} if stress else {})})
            if "[Success]" not in b.stdout:
                check(tag + " builds natively", False, b.stdout + b.stderr)
                continue
            out = subprocess.run([exe], input=data, capture_output=True, cwd=d)
            check(tag + " output", out.stdout == want, "native %r\npython %r" % (out.stdout[-300:], want[-300:]))
            check(tag + " exit code", out.returncode == ref.returncode, (out.returncode, ref.returncode, out.stderr))
print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
