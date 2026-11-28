#!/usr/bin/env python3
"""test_vector.py: 'vector ...' statements give the same numbers natively (AVX2) and in the Python backend."""
import subprocess, sys, os, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
src = os.path.join(HERE, "vec_demo.zmy"); tmp = tempfile.mkdtemp(prefix="zvec")
z = lambda *a: subprocess.run([sys.executable, os.path.join(ROOT, "zoomy.py")] + list(a), capture_output=True, text=True, cwd=tmp)
n = os.path.join(tmp, "nat"); py = os.path.join(tmp, "p.py")
assert z(src, "--native", "-o", n).returncode == 0
assert z(src, "-o", py).returncode == 0
a = subprocess.run([n], capture_output=True, text=True).stdout
b = subprocess.run([sys.executable, py], capture_output=True, text=True).stdout
asm = z(src, "--native", "--asm").stdout
ok = a == b and a.strip() != "" and "vpaddq" in asm
print("vector test:", "ok" if ok else "FAILED"); sys.exit(0 if ok else 1)
