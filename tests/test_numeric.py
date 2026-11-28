#!/usr/bin/env python3
"""Targeted numeric tests: number printing, NaN/inf comparisons, input parsing.

Each test compiles a Zoomy program and compares its output with the reference semantics in fuzz.py.
    python3 tests/test_numeric.py
"""
import itertools
import math
import os
import random
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import fuzz  # noqa: E402

INF, NAN = float("inf"), float("nan")
failures = 0


def check(name, ok, detail=""):
    global failures
    print(("PASS " if ok else "FAIL ") + name + (("  " + detail) if detail and not ok else ""))
    if not ok:
        failures += 1


def run_program(text, stdin=b""):
    text = "Simply,\n" + "".join(("    " + l if l.strip() else l) for l in text.splitlines(True))     # these programs use the old rules
    with tempfile.TemporaryDirectory() as tmp:
        exe = os.path.join(tmp, "p")
        fuzz.build_pure(text, exe)
        return fuzz.run_bin(exe, stdin)


# ---------------------------------------------------------------------------- 1. number printing
def random_doubles(rng, n):
    vals = []
    specials = [0.0, 1.0, 0.5, 1e6, 1e-6, 1e15, 1e14, 999999999999999.0, 1e16, 123456789.123456789,
                0.9999995, 0.99999949999, 9.9999995, 9.99999949, 99999.9999995, 5e-7, 4.9999999e-7, 1e-5,
                2.5e-6, 1.0000005, 1.0000015, 2.5, 1234567.0000005, 0.1, 0.2, 0.3, 1 / 3, 2 / 3, 1e22, 1e23,
                1.7976931348623157e308, 2.2250738585072014e-308, 5e-324, 4503599627370496.5, 9007199254740993.0]
    for s in specials:
        vals += [s, -s]
    for _ in range(n):
        t = rng.random()
        if t < 0.3:
            vals.append(struct.unpack('<d', struct.pack('<Q', rng.getrandbits(64)))[0])
        elif t < 0.55:
            vals.append(rng.uniform(-1e6, 1e6))
        elif t < 0.7:
            vals.append(rng.randint(-10**9, 10**9) + rng.choice([0, 0.5, 0.25, 0.0000005, 0.9999995]))
        elif t < 0.85:
            vals.append(rng.uniform(-1, 1) * 10 ** rng.randint(-12, 25))
        else:
            vals.append(round(rng.uniform(-100, 100), rng.randint(0, 8)))
    return [v for v in vals if v == v and abs(v) != INF]


def test_print_format():
    rng = random.Random(7)
    vals = random_doubles(rng, 2500)
    lines, want = [], bytearray()
    for v in vals:
        lines.append(f"    print {v!r}")
        want += fuzz.fmt(v) + b"\n"
    # special values built by arithmetic
    lines += ["    set zero to 0.0", "    set one to 1.0", "    set x to one", "    divide x by zero", "    print x",
              "    set y to -1.0", "    divide y by zero", "    print y", "    set z to zero", "    divide z by zero", "    print z",
              "    set nz to -0.0", "    print nz", "    print zero"]
    want += b"inf\n-inf\nnan\n0\n0\n"
    text = "action start:\n" + "\n".join(lines) + "\n"
    out, rc, err = run_program(text)
    ok = out == bytes(want)
    detail = ""
    if not ok:
        got, exp = out.split(b"\n"), bytes(want).split(b"\n")
        for i, (g, e) in enumerate(zip(got, exp)):
            if g != e:
                detail = f"first difference at value #{i}: {vals[i] if i < len(vals) else '?'!r}: got {g!r}, want {e!r}"
                break
    check(f"print format: {len(vals)} values + inf/-inf/nan/-0", ok, detail)


# ---------------------------------------------------------------------------- 2. comparisons
def test_comparisons():
    vals = {"nan": ("zero", "divide"), }
    names = ["nan", "inf", "ninf", "zero", "nzero", "one", "mone", "half"]
    pyvals = {"nan": NAN, "inf": INF, "ninf": -INF, "zero": 0.0, "nzero": -0.0, "one": 1.0, "mone": -1.0, "half": 0.5}
    ops = [None, "not", "less than", "greater than", "at least", "at most"]
    lines = ["    set zero to 0.0", "    set one to 1.0",
             "    set nan to zero", "    divide nan by zero",
             "    set inf to one", "    divide inf by zero",
             "    set ninf to -1.0", "    divide ninf by zero",
             "    set nzero to -0.0", "    set mone to -1.0", "    set half to 0.5"]
    want = bytearray()
    for a, b in itertools.product(names, names):
        for op in ops:
            cond = f"{a} is {op + ' ' if op else ''}{b}"
            lines += [f"    if {cond}:", '        write "T"', "    else:", '        write "F"']
            x, y = pyvals[a], pyvals[b]
            res = {None: x == y, "not": x != y, "less than": x < y, "greater than": x > y,
                   "at least": x >= y, "at most": x <= y}[op]
            want += b"T" if res else b"F"
    text = "action start:\n" + "\n".join(lines) + "\n"
    out, rc, err = run_program(text)
    n = len(names) ** 2 * len(ops)
    detail = ""
    if out != bytes(want):
        i = next((i for i, (g, e) in enumerate(zip(out, want)) if g != e), -1)
        a, b = divmod(i // len(ops), len(names))
        detail = f"first difference: {names[a]} {ops[i % len(ops)]} {names[b]}"
    check(f"comparisons: {n} combinations of nan/inf/-inf/0/-0/1/-1/0.5 x 6 operators (if/else)", out == bytes(want), detail)

    # the same table through `while` (separate tiny programs: the body prints T and exits, otherwise F is printed)
    setup = lines[:11]
    bad = []
    for a, b in itertools.product(names, names):
        for op in ops:
            cond = f"{a} is {op + ' ' if op else ''}{b}"
            text = "action start:\n" + "\n".join(setup) + f"\n    while {cond}:\n        write \"T\"\n        finish\n    write \"F\"\n"
            out, rc, err = run_program(text)
            x, y = pyvals[a], pyvals[b]
            res = {None: x == y, "not": x != y, "less than": x < y, "greater than": x > y,
                   "at least": x >= y, "at most": x <= y}[op]
            if out != (b"T" if res else b"F"):
                bad.append(cond)
    check(f"comparisons: {n} combinations through while", not bad, f"first failures: {bad[:5]}")


# ---------------------------------------------------------------------------- 3. input parsing
def test_read():
    inputs = [b"12 -3.5 +7 0.25", b"  \n\t 42\n", b"abc 5", b"x1.5", b".5 5. -", b"1e3", b"3.14.15", b"99999999999 1.2345678901234567",
              b"+-4 007 -0 0", b"", b" ", b"-.5", b"12abc34", b"0.1 0.2 0.3", b"123456789012345678901234567890", b"-", b"+ 3"]
    for data in inputs:
        n = 6
        lines = []
        want = bytearray()
        st = fuzz.Stdin(data)
        for i in range(n):
            lines += [f"    read x{i}", f'    print x{i}, " ok=", input_ok']
            x, ok = st.read_f64()
            want += fuzz.fmt(x) + b" ok=" + fuzz.fmt(float(ok)) + b"\n"
        lines += ["    read the next character into c", '    print char c, " ", c, " ", input_ok']
        c, ok = st.read_char()
        want += bytes([int(c)]) + b" " + fuzz.fmt(c) + b" " + fuzz.fmt(float(ok)) + b"\n"
        out, rc, err = run_program("action start:\n" + "\n".join(lines) + "\n", data)
        check(f"read parsing {data!r}", out == bytes(want), f"got {out!r} want {bytes(want)!r}")


if __name__ == "__main__":
    test_print_format()
    test_comparisons()
    test_read()
    print(f"\n{failures} failure(s)")
    sys.exit(1 if failures else 0)
