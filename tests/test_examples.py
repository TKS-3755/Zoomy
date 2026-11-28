#!/usr/bin/env python3
"""Every program in examples/ must compile, and the interactive ones must play a scripted session without a runtime error."""
import glob, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
ZOOMY = os.path.join(ROOT, "zoomy.py")

# example -> (stdin, text that must appear in the output)
RUNS = {
    "apex-z_chess.zmy": ("4\n2\ne2e4\ng1f3\nd2d4\nq\n", "APEX-Z plays:"),
    "hangman.zmy": ("a\ne\ni\no\nu\nr\ns\nt\nn\nl\nm\nq\nq\nq\nq\n", "Games played:"),
    "Explaining_Batch_Gradient_Descent_for_Simple_Linear_Regression_in_Zoomy.zmy": ("", "the computer predicts you will score: 7.82"),
    "zoomy5_manual.zmy": ("", "all clear"),
    "primes.zmy": ("", "gcd(84, 36) = 12"),
    "hello.zmy": ("", ""),
    "factorial.zmy": ("5\n", ""),
}
fails = 0
for path in sorted(glob.glob(os.path.join(ROOT, "examples", "*.zmy"))):
    name = os.path.basename(path)
    with tempfile.TemporaryDirectory() as t:
        exe = os.path.join(t, "prog")
        b = subprocess.run([sys.executable, ZOOMY, path, "-o", exe], capture_output=True, text=True)
        ok, why = b.returncode == 0 and "[Success]" in b.stdout, b.stdout.strip()[:200] + b.stderr.strip()[:200]
        if ok and name in RUNS:
            stdin, want = RUNS[name]
            cmd = [sys.executable, exe] if "Python program" in b.stdout else [exe]
            try:
                r = subprocess.run(cmd, input=stdin.encode(), capture_output=True, timeout=120, cwd=t)
                out = r.stdout.decode(errors="replace") + r.stderr.decode(errors="replace")
                ok = "runtime error" not in out and "Traceback" not in out and want in out
                why = out[-300:]
            except subprocess.TimeoutExpired:
                ok, why = False, "timed out"
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails += 1
        print("   ", why)
print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
