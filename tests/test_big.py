#!/usr/bin/env python3
"""Zoomy 7 Big Numbers (`from now on, use Big Numbers instead of floats`): 1024-bit whole numbers that wrap like the other
integer modes.  Random programs are checked against Python's own integers.  (test_big_backends.py runs them on every backend.)"""
import os, random, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Z = os.path.join(ROOT, "zoomy.py")
W = 1024
M = (1 << W) - 1
HEAD = "from now on, use Big Numbers instead of floats\n"


def wrap(x):
    x &= M
    return x - (1 << W) if x >> (W - 1) else x


def tdiv(a, b):
    q = abs(a) // abs(b)
    return wrap(-q if (a < 0) != (b < 0) else q)


def run(text, inp=b"", extra=()):
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "t.zmy")
        open(src, "w").write(text)
        p = subprocess.run([sys.executable, Z, src, "--run", *extra], input=inp, capture_output=True, timeout=120)
        return p.returncode, "\n".join(l for l in p.stdout.decode().splitlines() if not l.startswith("[")) , p.stderr.decode()


def lit(rng):
    return rng.choice([0, 1, 2, 3, 7, 255, 65535, 10 ** 18, 2 ** 64 + 5, 3 ** 200, 10 ** 100 + 7, 2 ** 1022 + 12345, 2 ** 500])


def main():
    fails = 0
    rng = random.Random(2024)
    for n in range(30):
        vals = {v: lit(rng) * rng.choice([1, -1]) for v in "pqr"}
        L = [HEAD] + [f"Let a number be called {v}" for v in "pqr"] + [f"set {v} to {'(0 - ' + str(-x) + ')' if x < 0 else x}" for v, x in vals.items()]
        want = []
        env = {v: wrap(x) for v, x in vals.items()}
        for _ in range(8):
            a, b, c = rng.sample("pqr", 3) if rng.random() < .5 else (rng.choice("pqr"), rng.choice("pqr"), rng.choice("pqr"))
            k = rng.choice(["plus", "minus", "times", "div", "mod", "rem"])
            if k == "plus":
                L.append(f"set {a} to {b} plus {c}"); env[a] = wrap(env[b] + env[c])
            elif k == "minus":
                L.append(f"set {a} to {b} minus {c}"); env[a] = wrap(env[b] - env[c])
            elif k == "times":
                L.append(f"set {a} to {b} times {c}"); env[a] = wrap(env[b] * env[c])
            else:
                d = env[c] if env[c] != 0 else 1
                L.append(f"if {c} is 0:\n    set {c} to 1")
                if env[c] == 0:
                    env[c] = 1
                if k == "div":
                    L.append(f"set {a} to {b} divided by {c}"); env[a] = tdiv(env[b], env[c])
                elif k == "mod":
                    L.append(f"set {a} to {b} mod {c}"); env[a] = wrap(env[b] % env[c])
                else:
                    L.append(f"set {a} to the remainder of {b} divided by {c}"); env[a] = wrap(env[b] - env[c] * tdiv(env[b], env[c]))
        for v in "pqr":
            L.append(f"print {v}")
            want.append(str(env[v]))
        rc, out, err = run("\n".join(L) + "\n")
        if rc or out.split("\n") != want:
            fails += 1
            print("FAIL random", n, rc, err[-200:], "\n", out[:300], "\n", want)
    fixed = [
        ("factorial", HEAD + "Let a number be called f\nset f to 1\nfor i from 1 to 100:\n    multiply f by i\nprint f\n", "93326215443944152681699238856266700490715968264381621468592963895217599993229915608941463976156518286253697920827223758251185210916864000000000000000000000000"),
        ("pow", HEAD + "print 2 ^ 1000\n", str(2 ** 1000)),
        ("wrap", HEAD + "print 2 ^ 1023\nprint 2 ^ 1024\nprint 0 - 2 ^ 1023 - 1\n", f"{-2 ** 1023}\n0\n{2 ** 1023 - 1}"),
        ("hex", HEAD + "print 0xFFFFFFFFFFFFFFFF\nprint 0xFFFFFFFFFFFFFFFFFFFF + 1\n", f"{2 ** 64 - 1}\n{2 ** 80}"),
        ("sqrt", HEAD + "print square root of (10 ^ 100)\n", str(10 ** 50)),
        ("bits", HEAD + "Let a number be called x\nset x to 1\nshift x left by 1000 bits\nprint x\nLet a number be called n\ncount the trailing zeros of x and store the result in n\nprint n\nbitwise not x\nprint x\n", f"{2 ** 1000}\n1000\n{~(2 ** 1000)}"),
        ("loop", HEAD + "Let a number be called t\nfor i from 1 to 5:\n    add 10 ^ 30 to t\nprint t\n", str(5 * 10 ** 30)),
        ("array", HEAD + "Create an array named a with 3 slots\nset item 1 of a to 10 ^ 60\nadd 1 to item 1 of a\nprint item 1 of a\n", str(10 ** 60 + 1)),
        ("old_name", "from now on, use bignum instead of floats\nprint 3 ^ 100\n", str(3 ** 100)),
        ("instead_ints", "from now on, use big integers instead of integers\nprint 3 ^ 100\n", str(3 ** 100)),
    ]
    for name, text, want in fixed:
        rc, out, err = run(text)
        if rc or out != want:
            fails += 1
            print("FAIL", name, rc, err[-200:], repr(out[:200]), "want", repr(want[:200]))
    rc, out, err = run(HEAD + "Let a number be called x\nset x to 5\nprint x / 0\n")
    if rc != 255 or "division by zero" not in err:
        fails += 1; print("FAIL div0", rc, err)
    rc, out, err = run(HEAD + "Let a number be called x\nset x to 1024\nshift x left by x bits\n")
    if rc != 255 or "from 0 to 1023" not in err:
        fails += 1; print("FAIL shift", rc, err)
    rc, out, err = run(HEAD + "Let a number be called x\nread x\nprint x + 1\nread x\nprint x\n", b"123456789012345678901234567890 -5")
    if rc or out != "123456789012345678901234567891\n-5".replace("\n", "\n"):
        fails += 1; print("FAIL read", rc, repr(out), err)
    rc, out, err = run(HEAD + "print 1.5\n")
    if rc == 0:
        fails += 1; print("FAIL fraction accepted")
    rc, out, err = run("print 2 ^ 100\n", extra=["--big"])
    if rc or out != str(2 ** 100):
        fails += 1; print("FAIL --big", rc, out, err)
    print(f"{fails} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
