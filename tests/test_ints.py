#!/usr/bin/env python3
"""Zoomy 5.5 integer mode: random programs must print the same from the native ELF and the Python backend."""
import os, random, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Z = os.path.join(ROOT, "zoomy.py")
VARS = ["p", "q", "r", "s"]
UNSIGNED = len(sys.argv) > 2 and sys.argv[2] == "unsigned"


def lit(rng):
    return str(rng.choice([0, 1, 2, 3, 7, 10, 63, 255, 1000, 65535, 123456789, 4294967296, 9223372036854775807]))


def expr(rng, d=0):
    if d > 2 or rng.random() < 0.3:
        return rng.choice(VARS) if rng.random() < 0.6 else lit(rng)
    a, b = expr(rng, d + 1), expr(rng, d + 1)
    k = rng.choice(["plus", "minus", "times", "div", "mod", "rem", "pow", "neg", "abs", "sqrt", "cmp", "and"])
    if k in ("plus", "minus", "times"):
        return f"({a} {k} {b})"
    if k == "div":
        return f"({a} divided by (({b} mod 9) plus 10))"
    if k == "mod":
        return f"({a} mod (({b} mod 9) plus 10))"
    if k == "rem":
        return f"(the remainder of {a} divided by (({b} mod 9) plus 10))"
    if k == "pow":
        return f"({a} to the power of ({b} mod 4))"
    if k == "neg":
        return f"(0 minus {a})"
    if k == "abs":
        return f"(absolute value of {a})"
    if k == "sqrt":
        return f"(square root of {a})"
    return f"({a} plus {b})"


def program(rng):
    L = ["from now on, use unsigned integers instead of floats" if UNSIGNED else "from now on, use integers instead of floats"]
    for v in VARS:
        L.append(f"Let a number be called {v}")
        L.append(f"set {v} to {lit(rng)}")
    for _ in range(14):
        v, w = rng.choice(VARS), rng.choice(VARS)
        k = rng.randrange(17)
        n = rng.randrange(64)
        if k == 0:
            L.append(f"set {v} to {expr(rng)}")
        elif k == 1:
            L.append(f"shift {v} left by {n} bits")
        elif k == 2:
            L.append(f"shift {v} right by {n} bits")
        elif k == 3:
            L.append(f"rotate {v} left by {n} bits")
        elif k == 4:
            L.append(f"bitwise {rng.choice(['and', 'or', 'xor'])} {v} with {w}")
        elif k == 5:
            L.append(f"bitwise not {v}")
        elif k == 6:
            L.append(f"count the set bits of {w} and store the result in {v}")
        elif k == 7:
            L.append(f"count the trailing zeros of {w} and store the result in {v}")
        elif k == 8:
            L.append(f"count the leading zeros of {v}")
        elif k == 9:
            L.append(f"{rng.choice(['set', 'clear', 'flip'])} bit {n} of {v}")
        elif k == 10:
            L.append(f"arithmetic shift {v} right by {n} bits")
        elif k == 11:
            L.append(f"reverse the bytes of {v}")
        elif k == 12:
            L.append(f"add {expr(rng)} to {v}")
        elif k == 14:
            L.append(f"logical shift {v} {rng.choice(['left', 'right'])} by {n} bits")
        elif k == 15:
            L.append(f"arithmetic shift {v} {rng.choice(['left', 'right'])} by {n} bits")
        elif k == 16:
            L.append(f"for i from {rng.choice([3, 5])} to {rng.choice([0, 1, 2])} by -1:")
            L.append(f"    add i times {w} to {v}")
        else:
            L.append(f"if {v} is less than {w}:")
            L.append(f"    set {v} to {expr(rng)}")
            L.append("else:")
            L.append(f"    isolate the lowest bit of {v}")
    for i in range(rng.randrange(0, 3)):
        L.append(f"for i from 1 to 3 by {rng.choice([1, 2])}:")
        L.append(f"    add i times {rng.choice(VARS)} to {rng.choice(VARS)}")
    for v in VARS:
        L.append(f"print {v}")
    return "\n".join(L) + "\n"


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60, **kw)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    rng = random.Random(77 if UNSIGNED else 55)
    fails = 0
    with tempfile.TemporaryDirectory() as tmp:
        for t in range(n):
            src = os.path.join(tmp, "t.zmy")
            text = program(rng)
            open(src, "w").write(text)
            exe = os.path.join(tmp, "t.bin")
            r = run([sys.executable, Z, "--native", src, "-o", exe])
            if r.returncode:
                print("COMPILE FAIL", t, r.stdout[-300:]); print(text); fails += 1; continue
            a = run([exe])
            b = run([sys.executable, Z, "--python", "--run", src])
            if (a.stdout, a.returncode) != (b.stdout, b.returncode):
                fails += 1
                print("MISMATCH", t, a.returncode, b.returncode); print(text); print(a.stdout, b.stdout, b.stderr[-200:])
                if fails > 3:
                    break
    print(f"{fails} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
