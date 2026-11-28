"""importing other .zmy files: search path, relative paths, include-once (so cycles are fine), clash and not-found messages"""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Z = [sys.executable, os.path.join(HERE, "zoomy.py")]
fails = 0
def check(name, ok, info=""):
    global fails
    if not ok:
        fails += 1
        print("FAIL", name, info)
def w(d, rel, text):
    p = os.path.join(d, rel); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w").write(text)
def run(d, main, env=None, args=("--run",)):
    e = dict(os.environ); e.pop("ZOOMY_PATH", None); e.update(env or {})
    r = subprocess.run(Z + [main] + list(args), capture_output=True, text=True, cwd=d, env=e)
    return r.stdout
with tempfile.TemporaryDirectory() as d:
    w(d, "lib/shapes.zmy", "include shared\ndefine area_square with s:\n    give back s * s\n")
    w(d, "lib/shared.zmy", "include shapes\ndefine twice with v:\n    give back v * 2\n")
    w(d, "zoomy_modules/mine.zmy", "define triple with v:\n    give back v * 3\n")
    w(d, "sub/inner.zmy", 'include "../lib/shapes.zmy"\n')
    w(d, "lib/other.zmy", "define twice with v:\n    give back v * 3\n")
    w(d, "main.zmy", 'include shapes\ninclude mine\ninclude "sub/inner.zmy"\nprint area_square(4)\nprint twice(5)\nprint triple(2)\n')
    out = run(d, "main.zmy", {"ZOOMY_PATH": os.path.join(d, "lib")})
    check("search path, zoomy_modules, relative include, cycle", out.split()[-3:] == ["16", "10", "6"], out)
    out = run(d, "main.zmy")
    check("not found without the path", "cannot find library 'shapes'" in out and "ZOOMY" not in out, out)
    w(d, "bad.zmy", "include shaps\n")
    out = run(d, "bad.zmy", {"ZOOMY_PATH": os.path.join(d, "lib")})
    check("Did you mean a library", "Did you mean 'shapes'" in out, out)
    w(d, "clash.zmy", "include shared\ninclude other\nprint twice(5)\n")
    out = run(d, "clash.zmy", {"ZOOMY_PATH": os.path.join(d, "lib")})
    check("clash names both files", "other.zmy:1" in out and "already defined in shared.zmy (line 2)" in out, out)
    w(d, "dup.zmy", "define a with v:\n    give back v\ndefine a with v:\n    give back v\nprint a(1)\n")
    out = run(d, "dup.zmy")
    check("same file twice", "'a' is defined twice (the first one is on line 1)" in out, out)
    # namespaces: include X as m -> m's name
    w(d, "lib/geo.zmy", "Let a number be called scale\ndefine area with w and h:\n    Let a number be called r\n    set r to w * h\n    give back r * scale\ndefine twice with v:\n    give back v * 2\n")
    w(d, "ns.zmy", 'include geo as g\ninclude other as o\nLet a number be called area\nset area to 7\nset g_scale to 2\nprint g\'s area(3, 4)\nprint o.twice(5)\nprint g.twice(5)\nprint area\nprint "in text: {g\'s twice(2)}"\n')
    for extra in ([], ["--python"]):
        out = run(d, "ns.zmy", {"ZOOMY_PATH": os.path.join(d, "lib")}, ["--run"] + extra)
        check("namespaces " + " ".join(extra), out.split("\n")[-6:-1] == ["24", "15", "10", "7", "in text: 4"], out)
    w(d, "ns2.zmy", "include geo as g\ninclude geo\nprint twice(2)\nprint g's twice(2)\n")
    out = run(d, "ns2.zmy", {"ZOOMY_PATH": os.path.join(d, "lib")})
    check("same file plain and as an alias", out.split()[-2:] == ["4", "4"], out)
print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
