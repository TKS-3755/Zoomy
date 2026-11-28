#!/usr/bin/env python3
"""Zoomy 7: the WebAssembly backend must behave exactly like the native one (output, exit code, error text) on the I/O
programs, random integer programs (signed and unsigned), bit operations and hand-written edge cases.  Needs Node.js."""
import importlib.util, os, random, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
Z = os.path.join(ROOT, "zoomy.py")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 24


def load(name, unsigned=False):
    saved = sys.argv
    sys.argv = ["x", "0", "unsigned"] if unsigned else ["x", "0"]
    try:
        spec = importlib.util.spec_from_file_location(name + ("_u" if unsigned else ""), os.path.join(HERE, name + ".py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    finally:
        sys.argv = saved


def run(cmd, inp=b"", cwd=None):
    return subprocess.run(cmd, input=inp, capture_output=True, timeout=120, cwd=cwd)


def both(tmp, name, text, inp=b""):
    """(native result, wasm result) of the same program; a result is (stdout, exit code, first line of stderr)"""
    src = os.path.join(tmp, name + ".zmy")
    open(src, "w").write(text)
    exe, wasm = os.path.join(tmp, name + ".elf"), os.path.join(tmp, name + ".wasm")
    r = run([sys.executable, Z, src, "--native", "-o", exe])
    if r.returncode:
        return ("native compile failed: " + r.stdout.decode()[-300:],), None
    r = run([sys.executable, Z, src, "--wasm", "-o", wasm])
    if r.returncode:
        return None, ("wasm compile failed: " + r.stdout.decode()[-300:],)
    out = []
    for cmd in ([exe], [shutil.which("node"), os.path.join(ROOT, "zoomy_wasm_host.js"), wasm]):
        p = run(cmd, inp, cwd=tmp)
        out.append((p.stdout, p.returncode, p.stderr.decode(errors="replace").splitlines()[:1]))
    return out[0], out[1]


EDGE = {
"errors_index": "Create an array named arr with 4 slots\nLet a number be called i\nset i to 4\nprint \"before\"\nprint item i of arr\n",
"errors_div": "from now on, use integers instead of floats\nLet a number be called z\nprint \"x\"\nprint 5 / z\n",
"errors_shift": "from now on, use integers instead of floats\nLet a number be called n\nset n to 64\nprint 1\nshift n left by n bits\n",
"errors_step": "Let a number be called s\nfor i from 1 to 3 by s:\n    print i\n",
"errors_count": "Let a number be called n\nset n to -1\nrepeat n times:\n    print 1\n",
"errors_long": "Let a number be called n\nset n to 1e15\nfor i from 1 to n:\n    print i\n",
"errors_deep": "define f with n:\n    give back f(n plus 1) plus 1\nprint f(1)\n",
"recursion": "define fib with n:\n    if n is less than 2:\n        give back n\n    give back fib(n minus 1) plus fib(n minus 2)\nprint fib(22)\n",
"mutual": "define fa with n:\n    if n is 0:\n        give back 0\n    give back fb(n minus 1) plus 1\ndefine fb with n:\n    if n is 0:\n        give back 0\n    give back fa(n minus 1) plus 2\nprint fa(9)\n",
"floats": "Let a number be called x\nfor x from 1 to 40 by 3:\n    print x / 7\n    print x * 1e10 / 3\n    print x / 1e9\nprint 0 - 1 / 3\nprint 1e15\nprint 123456789012345678\nprint 2 ^ 0.5\nprint 10 ^ 3.7\nprint 2 ^ 70\nprint 0.1 + 0.2\nprint 5e-324\nprint square root of 2\nprint 1e300 * 1e300\nprint 0 - 1e300 * 1e300\nprint (1e300 * 1e300) - (1e300 * 1e300)\nprint 7 mod 3\nprint 0 - 7 mod 3\nprint the remainder of (0 - 7) divided by 3\nprint floor of 2.5\nprint ceiling of 2.5\nprint absolute value of 0 - 2.5\n",
"loops": "Let a number be called t\nfor i from 1 to 10:\n    if i is 3:\n        skip\n    if i is 8:\n        stop\n    add i to t\nprint t\nfor i from 10 to 1 by -3:\n    print i\nfor x from 0 to 1 by 0.25:\n    print x\nrepeat 3 times:\n    print \"hi\"\nset t to 0\nrepeat forever:\n    add 1 to t\n    if t is 5:\n        stop\nprint t\nwhile t is above 0:\n    subtract 2 from t\nprint t\n",
"flags_chars": "Let a flag be called f\nset f to 3 is above 2\nprint f\nprint not f\nprint f and 1 is 2\nprint f or 1 is 2\nLet a number be called c\nconvert the character 'a' to a number and store the result in c\nprint c\nprint char 65\nprint \"A\", char 66, char 67\nprint pi\n",
"convert": "Let a number be called d\nLet a number be called c\nread the next character into c\nconvert the character c to a number and store the result in d\nprint d\nprint input_ok\nread the next character into c\nconvert the character c to a number and store the result in d\nprint d\nprint input_ok\n",
"read_nums": "Let a number be called v\nread v\nwhile input_ok is 1:\n    print v\n    read v\nprint \"done\"\n",
"finish": "print \"bye\"\nfinish with 7\nprint \"never\"\n",
"bigout": "for i from 1 to 3000:\n    print i, \" some text to fill the buffer \", i * 3\n",
"routine": "Let a number be called total\nroutine bump:\n    add 5 to total\nrun bump\nrun bump\nprint total\n",
}
EDGE_IN = {"convert": b"7 x", "read_nums": b"12 -3.5 +7 0.25 .5 5. abc 9", }

INTEDGE = {
"int_bits": "from now on, use integers instead of floats\nLet a number be called x\nLet a number be called y\nset x to 12345678901234\nprint popcnt\n".replace("print popcnt\n", "count the set bits of x and store the result in y\nprint y\ncount the trailing zeros of x and store the result in y\nprint y\ncount the leading zeros of x and store the result in y\nprint y\nisolate the lowest bit of x and store the result in y\nprint y\nreverse the bytes of x\nprint x\nrotate x left by 13 bits\nprint x\nrotate x right by 70 bits\nprint x\nset bit 40 of x\nprint x\nclear bit 40 of x\nprint x\nflip bit 63 of x\nprint x\nbitwise not x\nprint x\narithmetic shift x right by 5 bits\nprint x\nlogical shift x right by 5 bits\nprint x\n"),
"int_div": "from now on, use integers instead of floats\nprint 7 / 2\nprint 0 - 7 / 2\nprint 0 - 7 mod 3\nprint 7 mod (0 - 3)\nprint the remainder of (0 - 7) divided by 3\nprint 9223372036854775807 plus 1\nprint (0 - 9223372036854775807 - 1) / (0 - 1)\nprint 3 ^ 40\nprint 2 ^ (0 - 1)\nprint square root of 1000000000000\nprint absolute value of 0 - 5\n",
"int_args": "from now on, use integers instead of floats\nCreate an array named arr with 5 slots\nfor each v in arr:\n    print v\nfor i from 0 to 4:\n    set item i of arr to i * i\nadd 10 to item 2 of arr\nprint item 2 of arr\nprint length of arr\n",
}


def main():
    fails = 0
    if not shutil.which("node"):
        print("Node.js is not installed: skipping the WebAssembly tests")
        print("0 failures")
        return 0
    io = load("test_io55")
    cases = []
    for name, text, inp, want in [("bytes_f", io.BYTES, io.DATA, None), ("bytes_i", io.INT + io.BYTES, io.DATA, None),
                                  ("seek_f", io.SEEK, b"", None), ("seek_i", io.INT + io.SEEK, b"", None),
                                  ("aug_i", io.INT + io.AUG, b"", None), ("aug_f", io.AUG, b"", None),
                                  ("unsigned", io.UNS, b"", io.UNS_WANT),
                                  ("rc_f", io.RC, b"ab x.", None), ("rc_i", io.INT + io.RC, b"ab x.", None)]:
        cases.append((name, text, inp, want))
    for name, text in EDGE.items():
        cases.append((name, text, EDGE_IN.get(name, b""), None))
        if name in ("recursion", "flags_chars", "bigout", "routine", "errors_deep"):
            cases.append((name + "_i", "from now on, use integers instead of floats\n" + text, b"", None))
    for name, text in INTEDGE.items():
        cases.append((name, text, b"", None))
    rng = random.Random(77)
    for unsigned in (False, True):
        cg, ti = load("test_codegen", unsigned), load("test_ints", unsigned)
        for n in range(N):
            cases.append((f"codegen{n}{'u' if unsigned else ''}", cg.program(rng), b"", None))
            cases.append((f"ints{n}{'u' if unsigned else ''}", ti.program(rng), b"", None))
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "f.bin"), "wb").write(b"0123456789ABCDEF")
        for name, text, inp, want in cases:
            nat, wa = both(tmp, name, text, inp)
            if nat is None or wa is None or len(nat) == 1 or len(wa) == 1:
                fails += 1
                print("FAIL", name, nat if nat is None or len(nat) == 1 else "", wa if wa is None or len(wa) == 1 else "")
                continue
            if nat != wa or (want is not None and wa[0].decode() != want):
                fails += 1
                print("FAIL", name, "\n  native:", nat[0][:200], nat[1:], "\n  wasm:  ", wa[0][:200], wa[1:])
    print(f"{fails} failures" if fails else "0 failures")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
