"""Raw system calls and files opened by a name held in an array: native and Python backends must agree."""
import subprocess, sys, os, tempfile
here = os.path.dirname(os.path.abspath(__file__)); root = os.path.dirname(here)
def run(src, backend):
    d = tempfile.mkdtemp()
    out = os.path.join(d, "p" + (".py" if backend == "py" else ""))
    subprocess.run([sys.executable, os.path.join(root, "zoomy.py"), os.path.join(here, src), "-o", out], check=True, capture_output=True)
    cmd = [sys.executable, out] if backend == "py" else [out]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=here).stdout.split()
bad = 0
for src in ("openarr_demo.zmy", "sys_demo.zmy"):
    a, b = run(src, "native"), run(src, "py")
    if a != b:
        bad += 1; print("DIFF", src, a, b)
print("test_sys:", "ALL OK" if not bad else "FAILED")
sys.exit(bad)
