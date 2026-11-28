#!/usr/bin/env python3
"""Zoomy 7: built-in constants (pi, e, tau, sqrt2, c, G, h, g ...), your own variables of the same names, and `a` / `an` as names."""
import os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Z = os.path.join(ROOT, "zoomy.py")
INT = "from now on, use integers instead of floats\n"
CASES = [
    ("consts", "print pi\nprint e\nprint tau\nprint sqrt2\nprint sqrt3\nprint golden_ratio\nprint phi\nprint speed_of_light\nprint c\nprint G\nprint h\nprint g\nprint standard_gravity\nprint 2 * pi\n",
     "3.141593\n2.718282\n6.283185\n1.414214\n1.732051\n1.618034\n1.618034\n299792458\n299792458\n6.6743e-11\n6.62607e-34\n9.80665\n9.80665\n6.283185\n"),
    ("ints", INT + "print pi\nprint e\nprint tau\nprint sqrt2\nprint c\nprint g\nprint G\nprint light_year\n", "3\n2\n6\n1\n299792458\n9\n0\n9460730472580800\n"),
    ("shadow", "Let a number be called c\nLet a number be called e\nLet a number be called pi\nset c to 5\nset e to 6\nset pi to 7\nprint c + e + pi\n", "18\n"),
    ("inner", "define f with c:\n    give back c * 2\nprint f(4)\nfor g from 1 to 2:\n    print g\nprint g\n", "8\n1\n2\n9.80665\n"),
    ("a_name", "Let a number be called a\nLet a number be called an\nset a to 5\nadd 1 to a\nset an to a * 2\nprint a\nprint \"an is {an}\"\nif a is 6:\n    print \"six\"\n", "6\nan is 12\nsix\n"),
]
BAD = [
    ("assign_pi", "set pi to 3\n", "built-in constant"),
    ("assign_c", "set c to 3\n", "built-in constant"),
    ("big_int", INT + "print avogadro_constant\n", "too large for 64-bit integers"),
    ("article", "Let a number be called the\n", "article"),
]


def run(args, inp=b""):
    return subprocess.run(args, input=inp, capture_output=True, timeout=60)


def main():
    fails = 0
    with tempfile.TemporaryDirectory() as tmp:
        for name, text, want in CASES:
            src = os.path.join(tmp, name + ".zmy")
            open(src, "w").write(text)
            exe = os.path.join(tmp, name)
            r = run([sys.executable, Z, src, "--native", "-o", exe])
            if r.returncode:
                print("FAIL compile", name, r.stdout.decode()[-300:]); fails += 1; continue
            outs = [("native", run([exe]).stdout.decode()), ("python", run([sys.executable, Z, "--python", "--run", src]).stdout.decode().replace("[Success] Python script created: ", ""))]
            for label, out in outs:
                out = "\n".join(l for l in out.splitlines() if not l.startswith("[")) + "\n"
                if out != want:
                    print("FAIL", label, name, repr(out), "want", repr(want)); fails += 1
        for name, text, word in BAD:
            src = os.path.join(tmp, name + ".zmy")
            open(src, "w").write(text)
            r = run([sys.executable, Z, src, "--native", "-o", os.path.join(tmp, name)])
            if r.returncode == 0 or word not in r.stdout.decode():
                print("FAIL should not compile:", name, r.stdout.decode()[-200:]); fails += 1
    print(f"{fails} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
