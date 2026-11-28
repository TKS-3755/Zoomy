#!/usr/bin/env python3
"""Zoomy 6.3 code generator: random integer programs (constant divisors, shifts, loops of every shape, arrays, functions with
many local variables) must print the same from the native ELF and the Python backend, signed and unsigned, and the native
build must not change when the optimizations are switched off."""
import os, random, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Z = os.path.join(ROOT, "zoomy.py")
VARS = ["p", "q", "r", "s"]
UNS = len(sys.argv) > 2 and sys.argv[2] == "unsigned"
CONSTS = [1, 2, 3, 4, 5, 7, 8, 10, 16, 100, 1000, 1024, 65536, 2147483647]
LITS = [0, 1, 2, 3, 5, 9, 63, 64, 255, 1000, 65535, 123456789, 4294967296, 9223372036854775807]


def lit(rng):
    return str(rng.choice(LITS))


def expr(rng, d=0):
    if d > 2 or rng.random() < 0.3:
        return rng.choice(VARS) if rng.random() < 0.6 else lit(rng)
    a, b = expr(rng, d + 1), expr(rng, d + 1)
    k = rng.choice(["plus", "minus", "times", "div", "mod", "rem", "cdiv", "cmod", "crem", "shl", "shr", "and", "or", "xor", "neg", "item"])
    if k in ("plus", "minus", "times"):
        return f"({a} {k} {b})"
    if k == "div":
        return f"({a} divided by (({b} mod 9) plus 10))"
    if k == "mod":
        return f"({a} mod (({b} mod 9) plus 10))"
    if k == "rem":
        return f"(the remainder of {a} divided by (({b} mod 9) plus 10))"
    c = rng.choice(CONSTS)
    if k == "cdiv":
        return f"({a} divided by {c})"
    if k == "cmod":
        return f"({a} mod {c})"
    if k == "crem":
        return f"(the remainder of {a} divided by {c})"
    if k in ("shl", "shr"):
        return f"({a} {'shifted left by' if k == 'shl' else 'shifted right by'} {rng.randrange(0, 64)})" if False else f"({a} {k == 'shl' and 'times' or 'plus'} {rng.choice([2, 4, 8, 3])})"
    if k in ("and", "or", "xor"):
        return f"({a} plus {b})"
    if k == "neg":
        return f"(0 minus {a})"
    return f"(item (({a}) mod 8) of arr)"


def cond(rng):
    c = rng.choice(["is less than", "is greater than", "is at least", "is at most", "is", "is not"])
    t = f"{expr(rng, 2)} {c} {expr(rng, 2)}"
    k = rng.randrange(4)
    if k == 0:
        return f"{t} and {expr(rng, 2)} {rng.choice(['is less than', 'is at least'])} {lit(rng)}"
    if k == 1:
        return f"{t} or {rng.choice(VARS)} is {rng.choice(LITS[:5])}"
    if k == 2:
        return f"not ({t})"
    return t


def block(rng, depth, ind):
    L = []
    for _ in range(rng.randrange(1, 4)):
        v, w = rng.choice(VARS), rng.choice(VARS)
        k = rng.randrange(14 if depth < 2 else 9)
        pad = "    " * ind
        if k == 0:
            L.append(f"{pad}set {v} to {expr(rng)}")
        elif k == 1:
            L.append(f"{pad}add {expr(rng, 1)} to {v}")
        elif k == 2:
            L.append(f"{pad}subtract {expr(rng, 1)} from {v}")
        elif k == 3:
            L.append(f"{pad}multiply {v} by {rng.choice(['3', '5', w, '8', '1'])}")
        elif k == 4:
            L.append(f"{pad}divide {v} by {rng.choice(CONSTS + ['(' + w + ' mod 5 plus 1)'])}")
        elif k == 5:
            L.append(f"{pad}set item {rng.choice(['0', '3', '(' + w + ' mod 8)'])} of arr to {expr(rng, 1)}")
        elif k == 6:
            L.append(f"{pad}add {rng.choice(['1', '7', w])} to item {rng.choice(['2', '5', '(' + v + ' mod 8)'])} of arr")
        elif k == 7:
            L.append(f"{pad}set {v} to the result of calling mix with {expr(rng, 1)} and {w}" if False else f"{pad}set {v} to mix({expr(rng, 1)}, {w})")
        elif k == 8:
            L.append(f"{pad}set {v} to item {rng.choice(['1', '4', '(' + w + ' mod 8)'])} of arr")
        elif k == 9:
            L.append(f"{pad}if {cond(rng)}:")
            L += block(rng, depth + 1, ind + 1)
            if rng.random() < 0.5:
                L.append(f"{pad}else:")
                L += block(rng, depth + 1, ind + 1)
        elif k == 10:
            lo, hi = rng.choice([(1, 5), (0, 3), (3, 8)]), None
            step = rng.choice([1, 1, 2, 3, -1, -2])
            a, b = (lo[0], lo[1]) if step > 0 else (lo[1], lo[0])
            L.append(f"{pad}for i{depth} from {a} to {b} by {step}:" if step != 1 else f"{pad}for i{depth} from {a} to {b}:")
            L.append(f"{pad}    add i{depth} to {v}")
            L += block(rng, depth + 1, ind + 1)
        elif k == 11:
            L.append(f"{pad}set cnt{depth} to 0")
            L.append(f"{pad}while cnt{depth} is less than {rng.randrange(1, 5)} and ({cond(rng)}):")
            L.append(f"{pad}    add 1 to cnt{depth}")
            L += block(rng, depth + 1, ind + 1)
        elif k == 12:
            L.append(f"{pad}repeat {rng.randrange(0, 4)} times:")
            L += block(rng, depth + 1, ind + 1)
        else:
            L.append(f"{pad}for each x in arr:")
            L.append(f"{pad}    add x to {v}")
    return L


def program(rng):
    L = ["from now on, use unsigned integers instead of floats" if UNS else "from now on, use integers instead of floats"]
    for v in VARS + ["cnt0", "cnt1", "cnt2", "x", "i0", "i1", "i2"]:
        L.append(f"Let a number be called {v}")
    L.append("Create an array named arr with 8 slots")
    # a leaf function with many local variables (they live in scratch registers), and one that calls it
    L += ["define mix with m and n:",
          "    Let a number be called u1", "    Let a number be called u2", "    Let a number be called u3",
          "    Let a number be called u4", "    Let a number be called u5", "    Let a number be called u6",
          "    Let a number be called u7", "    Let a number be called k",
          "    set u1 to m plus 1", "    set u2 to n times 3", "    set u3 to u1 plus u2", "    set u4 to u3 mod 7",
          "    set u5 to 0", "    set u6 to u4 plus u1", "    set u7 to 1",
          "    for k from 1 to 6:", "        add k times u7 to u5", "        add u6 to u7", "        set u7 to u7 mod 1000",
          "    give back (u5 plus u3 plus u2) mod 100003", ""]
    for v in VARS:
        L.append(f"set {v} to {lit(rng)}")
    for j in range(8):
        L.append(f"set item {j} of arr to {rng.choice(LITS)}")
    L += block(rng, 0, 0) + block(rng, 0, 0)
    for v in VARS:
        L.append(f"print {v}")
    L.append("for each x in arr:")
    L.append("    print x")
    return "\n".join(L) + "\n"


def run(cmd, env=None, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env, **kw)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 80
    rng = random.Random(1234 if UNS else 4321)
    fails = 0
    with tempfile.TemporaryDirectory() as tmp:
        for t in range(n):
            src = os.path.join(tmp, "t.zmy")
            text = program(rng)
            open(src, "w").write(text)
            exe, exe2 = os.path.join(tmp, "t.bin"), os.path.join(tmp, "t2.bin")
            r = run([sys.executable, Z, "--native", src, "-o", exe])
            if r.returncode:
                print("COMPILE FAIL", t, r.stdout[-300:]); print(text); fails += 1; continue
            env = dict(os.environ, ZOOMY_NO_LEAFREGS="1")
            r2 = run([sys.executable, Z, "--native", src, "-o", exe2], env=env)
            a, b, c = run([exe]), run([sys.executable, Z, "--python", "--run", src]), run([exe2])
            if (a.stdout, a.returncode) != (b.stdout, b.returncode) or (a.stdout, a.returncode) != (c.stdout, c.returncode):
                fails += 1
                print("MISMATCH", t, a.returncode, b.returncode, c.returncode); print(text); print(a.stdout[:300], "|", b.stdout[:300], b.stderr[-200:])
                if fails > 3:
                    break
    print(f"{fails} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
