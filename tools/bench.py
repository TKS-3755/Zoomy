#!/usr/bin/env python3
"""Small native-speed benchmarks (integer mode): python3 tools/bench.py
Zoomy 8 looked for easy wins here (constant folding, inlining small functions) and found the native compiler already
folds constant sub-expressions and makes calls cheap, so no extra pass was added; these numbers are the baseline to beat."""
import os, subprocess, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROGS = {
 "constants in a hot loop (400M rounds)": """Let a number be called i
Let a number be called s
set s to 0
for i from 1 to 400000000:
    Structurally,
        set s to (s + (2 * 3 + 4) * 7) mod 1000003
print s
""",
 "small function, 300M calls + fib(38)": """define fib with n:
    if n is less than 2:
        give back n
    give back fib(n - 1) + fib(n - 2)
define sq with v:
    give back v * v + 1
Let a number be called i
Let a number be called s
set s to 0
for i from 1 to 300000000:
    set s to s + sq(i)
print s
print fib(38)
""",
}
with tempfile.TemporaryDirectory() as d:
    for name, text in PROGS.items():
        src, exe = os.path.join(d, "b.zmy"), os.path.join(d, "b")
        open(src, "w").write(text)
        subprocess.run([sys.executable, os.path.join(ROOT, "zoomy.py"), src, "--ints", "--regs", "-o", exe], capture_output=True, check=True, cwd=d)
        t = time.time(); subprocess.run([exe], capture_output=True, cwd=d); print(f"{time.time() - t:6.2f} s  {name}")
