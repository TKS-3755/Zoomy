#!/usr/bin/env python3
"""Zoomy 8: sine, cosine, tangent, arctangent, natural log and exp for Big Decimals (zoomy_bdmath.zmy, written in Zoomy).
  1. accuracy: every result against a 420-digit reference computed here with `decimal` (relative error below 1e-270);
  2. the Python, native and WebAssembly backends give identical output;
  3. errors: ln of 0 / a negative number, exp too large."""
import os, sys
from decimal import Decimal as D, getcontext
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import test_big_backends as T
T.HEAD = "from now on, use Big Decimals instead of floats\n"
getcontext().prec = 430
PI = D("3.14159265358979323846264338327950288419716939937510582097494459230781640628620899862803482534211706798214808651328230664709384460955058223172535940812848111745028410270193852110555964462294895493038196")
for _ in range(1):
    # more digits of pi by Machin
    one = 10 ** 440
    def at(n):
        x = one // n; s = x; k = 1; sg = -1
        while x:
            x //= n * n; k += 2; s += sg * (x // k); sg = -sg
        return s
    PI = D(4 * (4 * at(5) - at(239))) / D(one)


def r_sin(x):
    x = x - (2 * PI) * ((x / (2 * PI)).to_integral_value())
    t = s = x
    i = 1
    while abs(t) > D(10) ** -430:
        t = -t * x * x / ((i + 1) * (i + 2)); i += 2; s += t
    return s


def r_cos(x):
    return r_sin(x + PI / 2)


def r_atan(x):
    if x < 0:
        return -r_atan(-x)
    if x > 1:
        return PI / 2 - r_atan(1 / x)
    for _ in range(8):
        x = x / (1 + (1 + x * x).sqrt())
    t = s = x; i = 1
    while abs(t) > D(10) ** -430:
        t = -t * x * x; i += 2; s += t / i
    return s * 256


REF = {"exp": lambda x: x.exp(), "ln": lambda x: x.ln(), "sin": r_sin, "cos": r_cos,
       "tan": lambda x: r_sin(x) / r_cos(x), "atan": r_atan}
WORDS = {"exp": "exp of", "ln": "natural log of", "sin": "sine of", "cos": "cosine of", "tan": "tangent of", "atan": "arctangent of"}
INPUTS = {
    "exp": ["0", "0.5", "1", "-1", "10", "100", "-100", "700", "1e-50", "-0.000001"],
    "ln": ["2", "0.5", "10", "1e100", "1e-100", "1.0000000001", "0.999999", "1e300", "123456.789"],
    "sin": ["0.5", "1", "3", "-2", "100", "1e-20", "1e15", "1.5707963267948966"],
    "cos": ["0.5", "1", "3", "-2", "100", "1e-20", "1e15", "1.5707963267948966"],
    "tan": ["0.5", "1", "-1", "2", "100", "1e-20"],
    "atan": ["0.5", "1", "2", "1e10", "-3", "1e-30", "1e100"],
}


def main():
    fails = 0
    lines, cases = [], []
    for f, xs in INPUTS.items():
        for x in xs:
            cases.append((f, x))
            lines.append(f"print {WORDS[f]} {x}")
    # backends agree
    if not T.check("bdmath_all", "\n".join(lines) + "\n"):
        fails += 1
    # accuracy
    r = T.run3("bdmath_acc", "\n".join(lines) + "\n")["python"]
    outs = r[0].splitlines()
    if len(outs) != len(cases):
        print("FAIL output lines", len(outs), len(cases), r)
        return 1
    for (f, x), out in zip(cases, outs):
        want = REF[f](D(x))
        got = D(out)
        err = abs(got - want) / (abs(want) if want else 1)
        if err > D("1e-100") if len(out.replace("-", "").replace(".", "").lstrip("0")) < 105 else err > D("1e-100"):
            pass
        # the program prints 110 significant digits, so compare at 1e-105
        if err > D("1e-105") and abs(got - want) > D("1e-105"):
            fails += 1
            print("FAIL", f, x, "got", out[:60], "want", str(want)[:60], "err", err)
    # deeper accuracy: subtract the 330-digit reference inside the program (relative error below 1e-270)
    prog = ["Let a number be called t", "Let a number be called w"]
    for f, x in cases:
        want = REF[f](D(x))
        prog.append(f"set t to {WORDS[f]} {x}")
        prog.append(f"set w to {format(want, 'f') if want else '0'}")
        prog.append("set t to t - w")
        prog.append("if t is below 0:")
        prog.append("    set t to 0 - t")
        prog.append("set t to t / absolute value of w" if want else "set t to t")
        prog.append("if t is above 1e-270:")
        prog.append(f'    print "BAD {f} {x} ", t')
    prog.append('print "done"')
    r = T.run3("bdmath_deep", "\n".join(prog) + "\n")["python"]
    if r[0].strip() != "done":
        fails += 1
        print("FAIL deep accuracy:\n", r[0][:600])
    # errors agree on every backend
    for name, text in (("ln0", "print natural log of 0\n"), ("lnneg", "print natural log of -3\n"),
                       ("expbig", "print exp of 2000\n"), ("expsmall", "print exp of -5000\n"),
                       ("tanpi", "print tangent of 1.5\nprint arctangent of 0\nprint sine of 0\n")):
        if not T.check("bdmath_" + name, text):
            fails += 1
    print(f"{fails} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
