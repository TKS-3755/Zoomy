#!/usr/bin/env python3
"""Zoomy 5.5: `read byte` (raw bytes, whitespace kept, 0..255) and `read the clock into x` (milliseconds)."""
import os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Z = os.path.join(ROOT, "zoomy.py")
DATA = b"AB \n\xff\x00Z"
BYTES = "Let a number be called c\nLet a number be called n\nread the next byte into c\nwhile input_ok is 1:\n    print c\n    add 1 to n\n    read the next byte into c\nprint n\n"
CLOCK = ("Let a number be called t0\nLet a number be called t1\nLet a number be called x\nread the clock into t0\n"
         "for i from 1 to 20000000:\n    add 1 to x\nread the clock into t1\nprint (t1 - t0) is at least 1\nprint (t1 - t0) is less than 20000\n")
RC = "Let a number be called c\nread the next character into c\nwhile input_ok is 1:\n    print c\n    if c is 'x':\n        print \"found x\"\n    read the next character into c\n"
INT = "from now on, use integers instead of floats\n"
WANT = "65\n66\n32\n10\n255\n0\n90\n7\n"

SEEK = ("Let a number be called sz\nLet a number be called c\nopen the file \"f.bin\" for reading\nread the file size into sz\nprint sz\n"
        "move to byte 10 of the file\nread the next byte into c\nprint c\nmove to byte (sz - 1) of the file\nread the next byte into c\nprint c\nread the next byte into c\nprint input_ok\n"
        "move to byte 0 of the file\nread the next byte into c\nprint c\n")

AUG = ("Create an array named w with 10 slots\nfor f from 0 to 7:\n    add 1 to item (f + 1) of w\n    add f * 3 to item f of w\n"
       "    subtract 2 to item (f + 2) of w\n    multiply item (f + 1) of w by 3\n"
       "for i from 0 to 9:\n    print item i of w\n")
AUG = AUG.replace("    subtract 2 to item (f + 2) of w\n    multiply item (f + 1) of w by 3\n", "    subtract 2 from item (f + 2) of w\n")

UNS = 'from now on, use unsigned integers instead of floats\nLet a number be called x\nLet a number be called y\nLet a number be called z\nset x to 9223372036854775808\nset y to 1\nif x is greater than y:\n    print "big is greater"\nif y is less than x:\n    print "small is less"\nprint x\nset z to 18446744073709551615\nprint z\nprint z / 10\nprint z mod 1000\nprint the remainder of z divided by 7\nprint z plus 1\nprint 0 minus 1\nset x to 1\nshift x left by 63 bits\nprint x\nlogical shift x right by 63 bits\nprint x\nset x to 9223372036854775808\narithmetic shift x right by 62 bits\nprint x\nset x to 1\nlogical shift x left by 63 bits\narithmetic shift x left by 0 bits\nprint x\nprint square root of 18446744073709551615\nprint absolute value of z\nfor i from 3 to 0 by -1:\n    print i\nfor i from 18446744073709551614 to 18446744073709551615:\n    print i\nprint -1\n'
UNS_WANT = 'big is greater\nsmall is less\n9223372036854775808\n18446744073709551615\n1844674407370955161\n615\n1\n0\n18446744073709551615\n9223372036854775808\n1\n18446744073709551614\n9223372036854775808\n4294967295\n18446744073709551615\n3\n2\n1\n0\n18446744073709551614\n18446744073709551615\n18446744073709551615\n'

def run(args, inp=b"", cwd=None):
    return subprocess.run(args, input=inp, capture_output=True, timeout=60, cwd=cwd)

def main():
    fails = 0
    with tempfile.TemporaryDirectory() as tmp:
        for name, text, inp, want in [("bytes_f", BYTES, DATA, WANT), ("bytes_i", INT + BYTES, DATA, WANT),
                                      ("seek_f", SEEK, b"", "16\n65\n70\n0\n48\n"), ("seek_i", INT + SEEK, b"", "16\n65\n70\n0\n48\n"),
                                      ("augidx_i", INT + AUG, b"", None), ("augidx_f", AUG, b"", None),
                                      ("unsigned", UNS, b"", UNS_WANT),
                                      ("readchar_f", RC, b"ab x.", "97\n98\n120\nfound x\n46\n"), ("readchar_i", INT + RC, b"ab x.", "97\n98\n120\nfound x\n46\n"),
                                      ("clock_f", CLOCK, b"", "yes\nyes\n"), ("clock_i", INT + CLOCK, b"", "yes\nyes\n")]:
            open(os.path.join(tmp, "f.bin"), "wb").write(b"0123456789ABCDEF")
            src = os.path.join(tmp, name + ".zmy"); open(src, "w").write(text)
            exe = os.path.join(tmp, name)
            r = run([sys.executable, Z, src, "--native", "-o", exe])
            if r.returncode: print("FAIL compile", name, r.stdout[-300:]); fails += 1; continue
            out = run([exe], inp, cwd=tmp).stdout.decode()
            if want is None:                                   # no fixed answer: native must agree with the Python backend
                want = run([sys.executable, Z, "--python", "--run", src], inp, cwd=tmp).stdout.decode()
                if not want: print("FAIL python produced nothing", name); fails += 1
            if out != want: print("FAIL native", name, repr(out)); fails += 1
            out = run([sys.executable, Z, "--python", "--run", src], inp, cwd=tmp).stdout.decode()
            if out != want: print("FAIL python", name, repr(out)); fails += 1
    print(f"{fails} failure(s)")
    return 1 if fails else 0

if __name__ == "__main__":
    sys.exit(main())
