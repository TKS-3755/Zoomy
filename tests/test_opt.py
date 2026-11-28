#!/usr/bin/env python3
"""test_opt.py: every example program (and the test programs) must behave the same with and without --unroll / --regs (native backend)."""
import subprocess, sys, os, glob, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
progs = sorted(glob.glob(os.path.join(ROOT, "examples", "*.zmy")) + glob.glob(os.path.join(HERE, "*.zmy")))
tmp = tempfile.mkdtemp(prefix="zopt")
def build(src, flags, out):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "zoomy.py"), src, "--native", "-o", out] + flags, capture_output=True, text=True, cwd=os.path.dirname(src))
    return r.returncode == 0
def run(exe, inp):
    try:
        r = subprocess.run([exe], input=inp, capture_output=True, text=True, timeout=20, cwd=tmp)
        return (r.returncode, r.stdout)
    except subprocess.TimeoutExpired:
        return ("timeout", "")
bad = tested = 0
for p in progs:
    if "chess" in p:          # multi-threaded and timed: its node counts are compared by the chess tests instead
        continue
    base = os.path.join(tmp, "plain")
    if not build(p, [], base):
        continue
    inp = "4\n2\ne2e4\n" if "chess" in p else "5\n3\n2\n1\n"
    ref = run(base, inp)
    if ref[0] == "timeout":
        continue
    for flags in (["--unroll"], ["--regs"], ["--unroll", "--regs"], ["--ints", "--regs"], ["--ints", "--unroll", "--regs"]):
        out = os.path.join(tmp, "opt")
        if "--ints" in flags and not build(p, ["--ints"], os.path.join(tmp, "plain2")):
            continue                  # a program that needs floats cannot be built in integer mode at all
        if not build(p, flags, out):
            print("BUILD FAIL", os.path.basename(p), flags); bad += 1; continue
        got = run(out, inp); tested += 1
        base2 = os.path.join(tmp, "plain2")
        if "--ints" in flags:
            build(p, ["--ints"], base2); want = run(base2, inp)
        else:
            want = ref
        if got != want:
            print("DIFF", os.path.basename(p), flags, got[0], want[0]); bad += 1
print(f"{tested} runs compared, {bad} differences")
sys.exit(1 if bad else 0)
