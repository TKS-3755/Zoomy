#!/usr/bin/env python3
"""Zoomy 7 Big Numbers on every backend: the machine-code (native) and WebAssembly compilers rewrite a Big Numbers program onto
their 64-bit numbers plus the arithmetic library `zoomy_bignum.zmy` (written in Zoomy).  Each program here must give the same
output, exit code and error message on the Python backend (real integers: the reference), native, and WebAssembly (needs node).
Also: random programs, the library's unit test against Python integers, and the refusals."""
import os, random, re, shutil, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Z = os.path.join(ROOT, "zoomy.py")
HOST = os.path.join(ROOT, "zoomy_wasm_host.js")
HEAD = "from now on, use Big Numbers instead of floats\n"
HAVE_NODE = shutil.which("node") is not None
TMP = tempfile.mkdtemp()


def tail(p):
    return [re.sub(r" \([^()]*\.zmy, line \d+\)$", "", l) for l in p.stderr.decode().strip().splitlines()[-1:]]


def run3(name, text, inp=b""):
    src = os.path.join(TMP, name + ".zmy")
    open(src, "w").write(HEAD + text)
    res = {}
    p = subprocess.run([sys.executable, Z, src, "--run"], input=inp, capture_output=True, timeout=300)
    res["python"] = ("\n".join(l for l in p.stdout.decode().splitlines() if not l.startswith("[")), p.returncode, tail(p))
    elf = os.path.join(TMP, name + ".elf")
    r = subprocess.run([sys.executable, Z, src, "--native", "-o", elf], capture_output=True, text=True)
    if r.returncode:
        res["native"] = ("COMPILE " + r.stdout[-300:], -1, [])
    else:
        p = subprocess.run([elf], input=inp, capture_output=True, timeout=300)
        res["native"] = (p.stdout.decode().rstrip("\n"), p.returncode, tail(p))
    if HAVE_NODE:
        wasm = os.path.join(TMP, name + ".wasm")
        r = subprocess.run([sys.executable, Z, src, "--wasm", "-o", wasm], capture_output=True, text=True)
        if r.returncode:
            res["wasm"] = ("COMPILE " + r.stdout[-300:], -1, [])
        else:
            p = subprocess.run(["node", HOST, wasm], input=inp, capture_output=True, timeout=300)
            res["wasm"] = (p.stdout.decode().rstrip("\n"), p.returncode, tail(p))
    return res


def check(name, text, inp=b""):
    r = run3(name, text, inp)
    py = r["python"]
    ok = True
    for b in ("native", "wasm"):
        if b not in r:
            continue
        o = r[b]
        if not (o[0] == py[0].rstrip("\n") and o[1] == py[1] and (py[1] == 0 or o[2] == py[2])):
            ok = False
            print("MISMATCH", name, b, "\n  python:", repr(py[0][:200]), py[1], py[2], "\n  ", b, ":", repr(o[0][:200]), o[1], o[2])
    return ok


P={}
P["fact"]="""define fact with n:
    if n is less than 2:
        give back 1
    give back n * fact(n - 1)
print fact(30)
print fact(170)
Let a number be called i
for i from 1 to 5:
    print i, " ", fact(i * 10)
"""
P["fib"]="""define fib with n:
    if n is less than 2:
        give back n
    give back fib(n - 1) + fib(n - 2)
print fib(18)
Let a number be called a
Let a number be called b
Let a number be called t
set a to 0
set b to 1
Let a number be called k
for k from 1 to 300:
    set t to a + b
    set a to b
    set b to t
print a
"""
P["arrays"]="""Create an array named arr with 5 slots
Let a number be called i
Let a number be called s
for i from 0 to 4:
    set item i of arr to i * 100000000000000000000
add 7 to item 2 of arr
for each v in arr:
    add v to s
print s
print length of arr
print the first of arr
print the last of arr
store 5 in arr at index 1
load from arr at index 4 into s
print s
print item 1 of arr
"""
P["routine"]="""Let a number be called acc
Let a number be called n
routine fact:
    if n is greater than 1:
        multiply acc by n
        subtract 1 from n
        run fact
set n to 40
set acc to 1
run fact
print "40! = ", acc
"""
P["loops"]="""Let a number be called t
Let a number be called i
for i from 10 to 1 by -3:
    print i
for i from 1 to 10:
    if i is 3:
        skip
    if i is 8:
        stop
    add i to t
print t
repeat 3 times:
    print "hi"
set t to 0
repeat forever:
    add 1 to t
    if t is 5:
        stop
while t is above 0:
    subtract 2 from t
print t
print i
"""
P["flags"]="""Let a flag be called f
Let a number be called x
set x to 5
set f to x is above 3 and x is below 10
print f
print not f
set f to x is 2 or x * x is 25
print f
if x is 5 and f:
    print "yes"
else if x is 6:
    print "no"
while x is above 0 and x is not 2:
    subtract 1 from x
print x
"""
P["bits"]="""Let a number be called x
Let a number be called y
set x to 255
shift x left by 100 bits
print x
shift x right by 90 bits
print x
set y to 0 - 1
shift y right by 1000 bits
print y
arithmetic shift y right by 3 bits
print y
rotate x left by 1020 bits
print x
bitwise and x with 0xF0
print x
bitwise or x with 1
bitwise xor x with 3
print x
bitwise not x
print x
count the set bits of x and store the result in y
print y
set y to 0
count the leading zeros of y
print y
set y to 12
count the trailing zeros of y
print y
set bit 700 of y
print y
clear bit 700 of y
flip bit 2 of y
print y
isolate the lowest bit of y
print y
reverse the bytes of y
print y
"""
P["errdiv"]="""Let a number be called z
print "a"
print 5 / z
print "never"
"""
P["errmod"]="""Let a number be called z
print 5 mod z
"""
P["errshift"]="""Let a number be called n
set n to 1024
print 1
shift n left by n bits
"""
P["errshift2"]="""Let a number be called n
set n to 0 - 1
print 1
set bit n of n
"""
P["errindex"]="""Create an array named arr with 4 slots
Let a number be called i
set i to 4
print "before"
print item i of arr
"""
P["errindex2"]="""Create an array named arr with 4 slots
Let a number be called i
set i to 0 - 1
print item i of arr
"""
P["errstep"]="""Let a number be called s
for i from 1 to 3 by s:
    print i
"""
P["errcount"]="""Let a number be called n
set n to -1
repeat n times:
    print 1
"""
P["read"]="""Let a number be called v
Let a number be called s
read v
while input_ok is 1:
    print v
    add v to s
    read v
print "sum ", s
"""
P["chars"]="""Let a number be called c
Let a number be called d
read the next character into c
convert the character c to a number and store the result in d
print d
print input_ok
print char 65
print "A", char 66
read the next byte into c
print c
"""
P["calls"]="""define twice with x:
    give back x + x
define add3 with a and b and c:
    give back a + b + c
define sq with x:
    give back x * x
Let a number be called r
set r to add3(twice(3), sq(twice(4)), add3(1, 2, sq(10)))
print r
call twice with 21 and store the result in r
print r
call sq with r
print twice(sq(2 ^ 70))
"""
P["pow"]="""print 2 ^ 1023
print 3 ^ 500
print (0 - 2) ^ 1023
print 2 ^ 1024
print 2 ^ 0 - 1
print 7 ^ (0 - 1)
print 1 ^ (0 - 5)
print (0 - 1) ^ (0 - 5)
print square root of 10 ^ 100
print square root of 0 - 4
print the absolute value of 0 - 12345678901234567890123
print the remainder of (0 - 17) divided by 5
print (0 - 17) mod 5
print (0 - 17) / 5
print 17 mod (0 - 5)
"""
P["lits"]="""print 0xFFFFFFFFFFFFFFFF
print 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
print 123456789012345678901234567890123456789012345678901234567890
print 0 - 123456789012345678901234567890
print 1000000000 * 1000000000 * 1000000000 * 1000000000
print 9223372036854775807 + 1
print 0 - 9223372036854775807 - 2
"""
P["wrap"]="""Let a number be called x
set x to 2 ^ 1023
print x
print x - 1
print x + x
print 0 - x
print x * 2
print x / (0 - 1)
"""
P["finish"]="""print "bye"
Let a number be called c
set c to 7
finish with c
print "never"
"""
P["cmp"]="""Let a number be called a
Let a number be called b
set a to 2 ^ 600
set b to 0 - a
if a is above b:
    print "gt"
if b is below a:
    print "lt"
if a is 2 ^ 600:
    print "eq"
if a is not b:
    print "ne"
if a is at least a:
    print "ge"
if b is at most b:
    print "le"
if b is at least 1:
    print "bad"
"""
P["nested"]="""Create an array named g with 6 slots
Let a number be called i
Let a number be called j
Let a number be called t
for i from 0 to 5:
    for j from 0 to 5:
        if i * j is above 6:
            skip
        add i * j to t
        set item j of g to item j of g + i
print t
for each v in g:
    print v
"""
P["deep"]="""define f with n:
    if n is 0:
        give back 0
    give back f(n - 1) + 1
print f(300)
"""
P["input_ok"]="""Let a number be called v
read v
print input_ok
read v
print input_ok
print v
read v
print v
"""
P["condcall"]="""Let a number be called n
define bump:
    add 1 to n
    give back n
Let a flag be called f
set n to 0
if n is 1 and bump() is 1:
    print "no"
print n
if n is 0 and bump() is 1:
    print "yes"
print n
if n is 7 or bump() is 2:
    print "or"
print n
set f to bump() is 3 and bump() is 9
print f, " ", n
set n to 0
while bump() is below 5 and n is below 100:
    print n
print n
"""
P["perf"]="""Let a number be called x
Let a number be called i
set x to 1
for i from 1 to 3000:
    set x to (x * 6364136223846793005 + 1442695040888963407) mod (2 ^ 1000 + 7)
print x
"""
P["whileflag"]="""Let a number be called i
Let a flag be called done
set i to 1
while not done:
    set i to i * 3
    if i is above 1000000000000000000000000:
        set done to yes
print i
"""
P["globals"]="""Let a number be called total
define addto with x:
    add x to total
    give back total
define loc with x:
    Let a number be called total
    set total to x * 2
    give back total
set total to 5
print addto(10)
print loc(4)
print total
"""
P["twod"]="""Create an array named a2 with 3 slots
Let a number be called i
set i to 2
set item i of a2 to 77
set item i - 1 of a2 to item i of a2 + 1
print item 1 of a2
print item 2 of a2
print item 0 of a2
"""


INPUTS = {"read": b"12 -34\n 5 99999999999999999999999 x", "chars": b"  7q", "input_ok": b"-17 abc"}


def random_program(rng):
    """a few Big Number variables pushed through random arithmetic, bit operations, a function and a loop"""
    def lit():
        v = rng.choice([0, 1, 2, 3, 7, 255, 10 ** 18, 2 ** 64 + 5, 3 ** 200, 10 ** 100 + 7, 2 ** 1022 + 12345, 2 ** 500])
        v *= rng.choice([1, -1])
        return f"(0 - {-v})" if v < 0 else str(v)
    L = ["define mix with u and v:", "    give back (u * 31 + v) mod 1000000007"] if rng.random() < .5 else []
    L += [f"Let a number be called {v}" for v in "pqr"] + [f"set {v} to {lit()}" for v in "pqr"]
    for _ in range(14):
        a, b, c = (rng.choice("pqr") for _ in range(3))
        k = rng.choice(["+", "-", "*", "/", "mod", "rem", "and", "or", "xor", "shl", "shr", "sar", "rol", "ror", "pow", "mix", "neg", "sqrt", "abs", "cnt", "swap", "cmp"])
        if k in ("/", "mod", "rem"):
            L.append(f"if {c} is 0:\n    set {c} to 3")
        if k in "+-*":
            L.append(f"set {a} to {b} {k} {c}")
        elif k == "/":
            L.append(f"set {a} to {b} divided by {c}")
        elif k == "mod":
            L.append(f"set {a} to {b} mod {c}")
        elif k == "rem":
            L.append(f"set {a} to the remainder of {b} divided by {c}")
        elif k in ("and", "or", "xor"):
            L.append(f"set {a} to {b}\nbitwise {k} {a} with {c}")
        elif k in ("shl", "shr", "sar"):
            word = {"shl": "shift {a} left", "shr": "shift {a} right", "sar": "arithmetic shift {a} right"}[k].format(a=a)
            L.append(f"set {a} to {b}\n{word} by {rng.randint(0, 1023)} bits")
        elif k in ("rol", "ror"):
            L.append(f"set {a} to {b}\nrotate {a} {'left' if k == 'rol' else 'right'} by {rng.randint(0, 2000)} bits")
        elif k == "pow":
            L.append(f"set {a} to {b} ^ {rng.randint(0, 40)}")
        elif k == "mix":
            if L and L[0].startswith("define"):
                L.append(f"set {a} to mix({b}, {c})")
        elif k == "neg":
            L.append(f"set {a} to 0 - {b}")
        elif k == "sqrt":
            L.append(f"set {a} to square root of {b}")
        elif k == "abs":
            L.append(f"set {a} to the absolute value of {b} mod 1000003 + {c}")
        elif k == "cnt":
            L.append(f"count the set bits of {b} and store the result in {a}")
        elif k == "swap":
            L.append(f"set {a} to {b}\nreverse the bytes of {a}")
        else:
            L.append(f"if {b} is above {c}:\n    set {a} to {b} - {c}\nelse:\n    set {a} to {c} - {b}")
    L += [f"print {v}" for v in "pqr"]
    return "\n".join(L) + "\n"


def unit_test_library():
    """the library on its own, in unsigned 64-bit mode, against Python's integers (a short run; unit2 in the repo's history has more)"""
    lib = open(os.path.join(ROOT, "zoomy_bignum.zmy")).read().replace("call bn_unread with c", "set c to c").replace('fail with "division by zero"', "finish with 99")
    M = (1 << 1024) - 1

    def limbs(v):
        v &= M
        return [(v >> (32 * i)) & 0xFFFFFFFF for i in range(32)]

    def sg(x):
        x &= M
        return x - (1 << 1024) if x >> 1023 else x
    rng = random.Random(11)
    body, want = [], []
    for n in range(25):
        a = sg(rng.getrandbits(rng.choice([8, 32, 64, 300, 1024])) * rng.choice([1, -1]))
        b = sg(rng.getrandbits(rng.choice([8, 32, 64, 300, 1024])) * rng.choice([1, -1])) or 7
        for off, v in ((320, a), (352, b)):
            body.append(f"call bn_zero with {off}\n" + "".join(f"set item {off + i} of bn to {l}\n" for i, l in enumerate(limbs(v)) if l))
        for op, val in (("add", a + b), ("sub", a - b), ("mul", a * b)):
            body.append(f"call bn_{op} with 384 and 320 and 352\ncall bn_print with 384\nprint \"\"\n")
            want.append(str(sg(val)))
        q = abs(a) // abs(b)
        q = -q if (a < 0) != (b < 0) else q
        body.append("call bn_div with 384 and 320 and 352\ncall bn_print with 384\nprint \"\"\n")
        want.append(str(sg(q)))
        body.append("call bn_mod with 384 and 320 and 352\ncall bn_print with 384\nprint \"\"\n")
        want.append(str(a % b))
    src = os.path.join(TMP, "unit.zmy")
    open(src, "w").write("from now on, use unsigned integers instead of floats\n" + lib + "\n" + "".join(body))
    elf = os.path.join(TMP, "unit.elf")
    r = subprocess.run([sys.executable, Z, src, "--native", "-o", elf], capture_output=True, text=True)
    if r.returncode:
        print("FAIL library did not compile", r.stdout[-300:])
        return 1
    out = subprocess.run([elf], capture_output=True, timeout=120).stdout.decode().split("\n")[:-1]
    if out != want:
        print("FAIL library unit test", sum(1 for x, y in zip(out, want) if x != y), "differences")
        return 1
    return 0


def main():
    fails = 0
    names = sys.argv[1:] or list(P)
    for n in names:
        if not check(n, P[n], INPUTS.get(n, b"")):
            fails += 1
    rng = random.Random(77)
    for n in range(int(os.environ.get("BIG_RANDOM", "12"))):
        if not check(f"rand{n}", random_program(rng)):
            fails += 1
    fails += unit_test_library()
    # what the native and WebAssembly compilers cannot take is refused with a clear message, not miscompiled
    src = os.path.join(TMP, "bad.zmy")
    open(src, "w").write(HEAD + 'Let a string be called s\nset s to "hi"\nprint s\n')
    for flag in ("--native", "--wasm"):
        r = subprocess.run([sys.executable, Z, src, flag, "-o", os.path.join(TMP, "o")], capture_output=True, timeout=60)
        if r.returncode == 0 or b"Big Numbers" not in r.stdout:
            fails += 1
            print("FAIL should refuse", flag, r.stdout)
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"{fails} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
