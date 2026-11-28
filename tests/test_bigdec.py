#!/usr/bin/env python3
"""Zoomy 7 Big Decimals: binary floating point with a 1024-bit mantissa, whole and fractional.
  1. the Python reference (`_bd_*` in zoomy_runtime.py) against exact Fractions (every result within 2^-1020);
  2. the Python, native and WebAssembly backends must agree (output, exit code, error message) on hand-written and random programs;
  3. the Big Decimals library `zoomy_bigdec.zmy` (written in Zoomy) against the reference, bit for bit;
  4. the unsupported things are refused with a clear message."""
import os, random, re, shutil, subprocess, sys, tempfile
from fractions import Fraction
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import test_big_backends as T
import zoomy_runtime as zr
Z, TMP = T.Z, T.TMP
T.HEAD = "from now on, use Big Decimals instead of floats\n"

Q={}
Q["basic"]="""Let a number be called x
Let a number be called y
set x to 1 / 3
set y to 2 / 3
print x + y
print x * 3
print x - y
print y / x
print 0.1 + 0.2
print 1 / 7
print 100 / 8
print 0 - 5 / 2
"""
Q["constants"]="""print pi
print planck_constant
print speed_of_light
print elementary_charge
print gravitational_constant
print avogadro_constant
print boltzmann_constant
print planck_constant * speed_of_light
print electron_mass
"""
Q["tiny"]="""Let a number be called t
set t to 0.000000000000000000000000000000000000000000000001
print t
print t * t
print t / 3
set t to 1 / 3
set t to t / 1000000000000000000000000000000
print t
print 1.5e-30 * 2
"""
Q["huge"]="""Let a number be called h
set h to 10 ^ 300
print h
print h * h
print h * 1.5
print 3 ^ 500
print 2 ^ 1000
print 2 ^ 0 - 1
print 2 ^ 0 - 3
"""
Q["roundings"]="""Let a number be called x
for x from 0 - 3 to 3 by 0.5:
    print floor of x
    print ceiling of x
    print round of x
    print x mod 2
    print the remainder of x divided by 2
print 7.5 mod 2
print 0 - 7.5 mod 2
print 7.5 mod (0 - 2)
print the remainder of (0 - 7.5) divided by 2
print square root of 2 * square root of 2
print square root of 16
print square root of 0.25
print square root of 0
"""
Q["loops"]="""Let a number be called x
for x from 0 to 1 by 0.1:
    print x
for x from 1 to 0 by 0 - 0.25:
    print x
for x from 5 to 1:
    print "never"
for x from 0.5 to 2.4:
    print x
Let a number be called n
set n to 0
for x from 0 to 0.3 by 0.1:
    add 1 to n
print n
repeat 2.7 times:
    print "r"
"""
Q["arrays"]="""Create an array named a with 5 slots
Let a number be called i
for i from 0 to 4:
    set item i of a to i / 4
for i from 0 to 4:
    print item i of a
print item 2.9 of a
set item 3.5 of a to 0.125
print item 3 of a
Let a number be called s
set s to 0
for each v in a:
    add v * v to s
print s
print item 0.5 of a
print item 0 - 0.5 of a
"""
Q["funcs"]="""define half with x:
    give back x / 2
define pw with b and n:
    if n is 0:
        give back 1
    give back b * pw(b, n - 1)
define harmonic with n:
    Let a number be called t
    Let a number be called k
    set t to 0
    for k from 1 to n:
        set t to t + 1 / k
    give back t
print half(5)
print pw(1.5, 20)
print harmonic(50)
print half(half(half(1)))
print pw(0.1, 12)
"""
Q["compare"]="""Let a number be called a
Let a number be called b
set a to 0.1 + 0.2
set b to 0.3
if a is b:
    print "equal"
else:
    print "not equal"
if a is below b:
    print "below"
if a is above b:
    print "above"
if 1 / 3 * 3 is 1:
    print "third ok"
if 0 - 1 / 3 is below 0:
    print "neg below"
if 1e-300 is above 0:
    print "tiny positive"
print a - b
"""
Q["newton"]="""Let a number be called x
Let a number be called i
set x to 1
for i from 1 to 12:
    set x to (x + 2 / x) / 2
print x
print x * x
print x - square root of 2
"""
Q["errdiv"]="""Let a number be called z
set z to 0
print 1
print 5 / z
"""
Q["errsqrt"]="""Let a number be called z
set z to 0 - 4
print square root of z
"""
Q["errpow"]="""print 2 ^ 0.5
"""
Q["errlarge"]="""Let a number be called h
set h to 10 ^ 300
print h * h * h * h
"""
Q["errindex"]="""Create an array named a with 3 slots
print item 0 - 1 of a
"""
Q["errcount"]="""repeat 0 - 2 times:
    print "x"
"""
Q["errstep"]="""Let a number be called x
for x from 1 to 5 by 0:
    print x
"""
Q["errlong"]="""Let a number be called x
for x from 1 to 10 ^ 20:
    print x
"""
Q["read"]="""Let a number be called v
Let a number be called w
read v
read w
print v + w
read v
print v
read v
print v
print input_ok
"""
Q["printmix"]="""Let a number be called x
set x to 22 / 7
print "x is " , x , "!"
print x * 100
print 123456789012345678901234567890
print 0.00001
print 100000000000000000000
print 0 - 0.5
print 1 / 1024
print 0.1 * 3
"""
Q["finish"]="""print 1 / 4
finish with 3
"""
Q["whileflag"]="""Let a number be called x
Let a flag be called big
set x to 1
set big to false
while x is below 1000 and not big:
    set x to x * 1.5
    if x is above 500:
        set big to true
print x
print big
"""
Q["chars"]="""Let a number be called c
set c to 65.9
print char c
set c to 66
print char c, "!" 
"""
Q["aug"]="""Let a number be called x
set x to 1
add 0.5 to x
subtract 0.25 from x
multiply x by 3
divide x by 7
print x
"""
Q["nested"]="""Let a number be called x
Let a number be called y
Let a number be called s
set s to 0
for x from 0 to 1 by 0.5:
    for y from 0 to 1 by 0.25:
        set s to s + x * y
print s
"""
Q["input_ok"]="""Let a number be called v
read v
print input_ok + 0.5
"""
Q["zeros"]="""Create an array named a with 3 slots
Let a number be called u
Let a number be called v
print u
print u + 1
print 1 + item 1 of a
print u * 5
print 5 / (u + 2)
print u - 3
print 3 - item 2 of a
print square root of u
print floor of u
print ceiling of u
print round of u
print u mod 3
print 7 mod 3 + u
print the remainder of u divided by 3
print u ^ 3
print 2 ^ u
if u is 0:
    print "zero"
if u is above 0 - 1:
    print "gt"
if item 0 of a is below 0.1:
    print "lt"
set v to u
print v
set v to 0 - u
print v
for v from u to 2:
    print v
print item u of a
repeat u times:
    print "no"
print u / 4
"""
INPUTS={"read":b" 3.25 -0.5 \n  7.125e","errread":b"","input_ok":b"2"}


def random_program(rng):
    """a few Big Decimals pushed through random arithmetic, rounding, a function, an array and a loop"""
    def lit():
        v = rng.choice(["0", "1", "2", "3", "0.5", "0.1", "7.25", "1e-30", "123456789.123456789", "10 ^ 40", "1 / 3", "2 / 7", "0.000001", "1e100", "99999999999999999999.5", "planck_constant", "pi", "speed_of_light"])
        return f"(0 - {v})" if rng.random() < .3 else v
    L = ["define mix with u and v:", "    give back (u * 3.5 + v) / 7"] if rng.random() < .5 else []
    L += [f"Let a number be called {v}" for v in "pqr"] + [f"set {v} to {lit()}" for v in "pqr"]
    L += ["Create an array named arr with 4 slots", "Let a number be called i"]
    for _ in range(14):
        a, b, c = (rng.choice("pqr") for _ in range(3))
        k = rng.choice(["+", "-", "*", "/", "mod", "rem", "pow", "mix", "neg", "sqrt", "abs", "floor", "ceil", "round", "cmp", "arr", "loop", "scale"])
        if k in ("/", "mod", "rem"):
            L.append(f"if {c} is 0:\n    set {c} to 3")
        if k == "sqrt":
            L.append(f"set {a} to square root of (absolute value of {b})")
        elif k in "+-*":
            L.append(f"set {a} to {b} {k} {c}")
        elif k == "/":
            L.append(f"set {a} to {b} divided by {c}")
        elif k == "mod":
            L.append(f"set {a} to {b} mod {c}")
        elif k == "rem":
            L.append(f"set {a} to the remainder of {b} divided by {c}")
        elif k == "pow":
            L.append(f"set {a} to {b} ^ {rng.randint(0, 12)}")
        elif k == "mix":
            if L and L[0].startswith("define"):
                L.append(f"set {a} to mix({b}, {c})")
        elif k == "neg":
            L.append(f"set {a} to 0 - {b}")
        elif k == "abs":
            L.append(f"set {a} to the absolute value of {b} + {c}")
        elif k in ("floor", "ceil", "round"):
            L.append(f"set {a} to {({'floor': 'floor', 'ceil': 'ceiling', 'round': 'round'})[k]} of {b}")
        elif k == "arr":
            L.append(f"set item {b} mod 4 of arr to {c}\nset {a} to item {c} mod 4 of arr")
        elif k == "loop":
            L.append(f"for i from {rng.choice(['0', '0.5', '1'])} to {rng.choice(['2', '3.3', '1.25'])} by {rng.choice(['1', '0.5', '0.3', '0.1'])}:\n    set {a} to {a} + i * {b}")
        elif k == "scale":
            L.append(f"set {a} to {b} / 1000000000000 / 1000000000000 / 1000000000000")
        else:
            L.append(f"if {b} is above {c}:\n    set {a} to {b} - {c}\nelse:\n    set {a} to {c} - {b}")
    L += [f"print {v}" for v in "pqr"]
    return "\n".join(L) + "\n"


def reference_vs_fractions(rng):
    """the Python reference: every result is the exact answer cut to 1024 bits (relative error below 2^-1020)"""
    def val(x):
        return Fraction(x.m) * Fraction(2) ** x.e * (-1 if x.s else 1) if x.m else Fraction(0)

    def rnd():
        k = rng.random()
        if k < .1:
            return zr._BD_ZERO
        if k < .4:
            return zr._bd_from_fraction(rng.randint(-10 ** 12, 10 ** 12), rng.randint(1, 10 ** 9))
        return zr._BD(rng.randint(0, 1), rng.getrandbits(1023) | (1 << 1023), rng.choice([-1500, -1100, -1030, -1023, -5, 0, 40, 100]) + rng.randint(-2, 2))
    bad = 0
    for _ in range(400):
        a, b = rnd(), rnd()
        fa, fb = val(a), val(b)
        for name, f, ex in (("add", zr._bd_add, fa + fb), ("mul", zr._bd_mul, fa * fb), ("div", zr._bd_div, fa / fb if fb else None)):
            if ex is None:
                continue
            try:
                r = val(f(a, b))
            except zr.ZoomyRuntimeError:
                continue
            if abs(r - ex) > abs(ex) / 2 ** 1020 and not (abs(ex) < Fraction(1, 2 ** 3000)):
                bad += 1
                print("FAIL reference", name)
        fl = zr._bd_floor(a)
        import math
        if val(fl) != math.floor(fa) or val(zr._bd_ceil(a)) != math.ceil(fa) or val(zr._bd_trunc(a)) != math.trunc(fa):
            bad += 1
            print("FAIL reference rounding")
        if fa > 0:
            r = val(zr._bd_sqrt(a))
            if abs(r * r - fa) > fa / 2 ** 1018:
                bad += 1
                print("FAIL reference sqrt")
    for text, want in (("0.1", "0.1"), ("1e-3", None), ("0.000123", "0.000123"), ("3.14159", "3.14159"), ("123456789.987654321", "123456789.987654321")):
        if want and zr._bd_str(zr._bdlit(*Fraction(text).as_integer_ratio())) != want:
            bad += 1
            print("FAIL printing", text)
    return bad


def unit_test_library(rounds=14):
    """the library `zoomy_bigdec.zmy` on its own (unsigned 64-bit mode), bit for bit against the reference"""
    lib = open(os.path.join(ROOT, "zoomy_bigdec.zmy")).read().replace("call bd_unread with c", "set c to c")
    lib = re.sub(r'fail with "[^"]*"', "finish with 99", lib)
    rng = random.Random(5)
    A, B, D = 2000, 2040, 2080

    def limbs(v, n):
        return [(v >> (32 * i)) & 0xFFFFFFFF for i in range(n)]

    def setbd(off, x):
        s = f"call w_zero with {off} and 34\n"
        s += "".join(f"set item {off + i} of bn to {l}\n" for i, l in enumerate(limbs(x.m, 32)) if l)
        return s + f"set item {off + 32} of bn to {x.e + 4294967296}\nset item {off + 33} of bn to {x.s}\n"

    def dump(off):
        return f"for ii from 0 to 33:\n    set jj to {off} + ii\n    set c to item jj of bn\n    print c\n"

    def want(x):
        return [str(l) for l in limbs(x.m, 32)] + [str(x.e + 4294967296 if x.m else 4294967296), str(x.s if x.m else 0)]

    def rbd():
        k = rng.random()
        if k < .05:
            return zr._BD_ZERO
        if k < .3:
            return zr._bd_from_int(rng.randint(-10 ** rng.randint(1, 30), 10 ** rng.randint(1, 30)))
        if k < .5:
            return zr._bd_from_fraction(rng.randint(-10 ** 9, 10 ** 9), rng.randint(1, 10 ** 6))
        return zr._BD(rng.randint(0, 1), rng.getrandbits(1023) | (1 << 1023),
                      rng.choice([-1024, -1023, -1000, -2000, -1100, -1030, -5, 0, 3, 10, 300, 900, -2500]) + rng.randint(-3, 3))
    body, W = ["Let a number be called ii\nLet a number be called jj\nLet a number be called c\n"], []
    for _ in range(rounds):
        a = rbd()
        b = zr._BD(rng.randint(0, 1), a.m ^ rng.getrandbits(rng.choice([3, 100, 900])), a.e + rng.randint(-2, 2)) if a.m and rng.random() < .4 else rbd()
        body.append(setbd(A, a) + setbd(B, b))
        for nm, f in (("bd_add", zr._bd_add), ("bd_sub", lambda x, y: zr._bd_add(x, zr._bd_neg(y))), ("bd_mul", zr._bd_mul),
                      ("bd_div", zr._bd_div), ("bd_mod", zr._bd_mod), ("bd_rem", zr._bd_rem)):
            try:
                r = f(a, b)
            except Exception:
                continue
            body.append(f"call {nm} with {D} and {A} and {B}\n" + dump(D))
            W += want(r)
        body.append(f"set c to bd_cmp({A}, {B})\nprint c\n")
        W.append(str(zr._bd_cmp(a, b) + 1))
        for nm, f in (("bd_floor", zr._bd_floor), ("bd_ceil", zr._bd_ceil), ("bd_trunc", zr._bd_trunc), ("bd_round", zr._bd_round), ("bd_neg", zr._bd_neg)):
            body.append(f"call {nm} with {D} and {A}\n" + dump(D))
            W += want(f(a))
        if a.s == 0 or a.m == 0:
            body.append(f"call bd_sqrt with {D} and {A}\n" + dump(D))
            W += want(zr._bd_sqrt(a))
        e = rng.randint(-6, 30)
        try:
            r = zr._bd_pow(a, zr._bd_from_int(e))
            body.append(setbd(B, zr._bd_from_int(e)) + f"call bd_pow with {D} and {A} and {B}\n" + dump(D))
            W += want(r)
        except Exception:
            pass
    src = os.path.join(TMP, "bdunit.zmy")
    open(src, "w").write("from now on, use unsigned integers instead of floats\n" + lib + "\n" + "".join(body))
    elf = os.path.join(TMP, "bdunit.elf")
    r = subprocess.run([sys.executable, Z, src, "--native", "-o", elf], capture_output=True, text=True)
    if r.returncode:
        print("FAIL the Big Decimals library did not compile", r.stdout[-300:])
        return 1
    out = subprocess.run([elf], capture_output=True, timeout=300).stdout.decode()
    got = out.split()
    if got != W:
        print("FAIL Big Decimals library unit test:", sum(1 for x, y in zip(got, W) if x != y), "differences,", len(got), "outputs for", len(W), "expected")
        return 1
    return 0


def main():
    fails = 0
    names = sys.argv[1:] or list(Q)
    rng = random.Random(21)
    fails += 1 if reference_vs_fractions(rng) else 0
    for n in names:
        if not T.check("bd_" + n, Q[n], INPUTS.get(n, b"")):
            fails += 1
    # programs of the integer test that make sense for fractions too: the answers are the same on every backend
    for n in ("fact", "fib", "arrays", "routine", "loops", "flags", "errdiv", "errindex", "errstep", "errcount", "read", "nested", "deep", "condcall", "whileflag", "globals", "twod"):
        if not T.check("bdi_" + n, T.P[n], T.INPUTS.get(n, b"")):
            fails += 1
    prng = random.Random(1234)
    for n in range(int(os.environ.get("BIGDEC_RANDOM", "12"))):
        if not T.check(f"bdrand{n}", random_program(prng)):
            fails += 1
    fails += unit_test_library(int(os.environ.get("BIGDEC_UNIT", "14")))
    # what Big Decimals cannot do is refused with a clear message
    for fn in ("rounded 1.234 to 2 places",):
        src = os.path.join(TMP, "bad.zmy")
        open(src, "w").write(T.HEAD + f"print {fn}\n")
        r = subprocess.run([sys.executable, Z, src, "--run"], capture_output=True, timeout=60)
        if r.returncode == 0 or b"Big Decimals" not in (r.stdout + r.stderr):
            fails += 1
            print("FAIL should refuse:", fn, (r.stdout + r.stderr)[-200:])
    src = os.path.join(TMP, "bad2.zmy")
    open(src, "w").write(T.HEAD + 'Let a string be called s\nset s to "hi"\nprint s\n')
    for flag in ("--native", "--wasm"):
        r = subprocess.run([sys.executable, Z, src, flag, "-o", os.path.join(TMP, "o")], capture_output=True, timeout=60)
        if r.returncode == 0 or b"Big Decimals" not in r.stdout:
            fails += 1
            print("FAIL should refuse", flag, r.stdout)
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"{fails} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
