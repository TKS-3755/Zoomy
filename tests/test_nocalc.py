#!/usr/bin/env python3
"""Run every NoCalc library routine and compare with Python's math module.
    python3 tests/test_nocalc.py
"""
import math, os, re, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
ZOOMY = os.path.join(ROOT, "zoomy.py")
fails = 0

def run(body):
    body = re.sub(r'^(    print [^"\n]*)$', lambda m: m.group(1).replace(", ", ', " ", '), body, flags=re.M)
    text = ("include nocalc's creation\ninclude nocalc's statistics\ninclude nocalc's linalg\n"
            "include nocalc's math\ninclude nocalc's ufuncs\n\nLet a number be called v\n\naction start:\n" + body)
    with tempfile.TemporaryDirectory() as t:
        src, exe = os.path.join(t, "t.zmy"), os.path.join(t, "t")
        open(src, "w").write(text)
        if os.environ.get("ZOOMY_BACKEND") == "python":
            r = subprocess.run([sys.executable, ZOOMY, src, "--python", "--run"], capture_output=True, text=True, timeout=60)
            if "[Error]" in r.stdout: raise SystemExit(r.stdout)
            return r.stdout.split()
        r = subprocess.run([sys.executable, ZOOMY, src, "-o", exe], capture_output=True, text=True)
        if r.returncode: raise SystemExit(r.stderr)
        return subprocess.run([exe], capture_output=True, text=True, timeout=20).stdout.split()

def check(name, got, want, tol=1e-5):
    global fails
    g = [float(x) for x in got]
    ok = len(g) == len(want) and all(abs(a-b) <= tol*max(1, abs(b)) for a, b in zip(g, want))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  got {g} want {want}"))
    fails += not ok

def arr(name, vals):
    s = ""
    for i, v in enumerate(vals):
        s += f"    store {v!r} in {name} at index {float(i)!r}\n"
    return s

A = [3.5, -1.25, 8.0, 0.5, 2.0, -7.75]; B = [1.0, 2.0, -3.0, 4.0, 0.25, 6.0]; n = len(A)
mean = sum(A)/n; var = sum((x-mean)**2 for x in A)/n
head = arr("arr", A) + arr("arr2", B) + f"    set size to {float(n)!r}\n"
check("sum/mean/variance/std", run(head + "    run mean\n    run variance\n    run std_dev\n    print sum_result, mean_val, var_result, std_result\n"),
      [sum(A), mean, var, math.sqrt(var)])
check("min/max/ptp", run(head + "    run find_min\n    run find_max\n    run ptp\n    print min_val, max_val, ptp_val\n"), [min(A), max(A), max(A)-min(A)])
check("dot/norm/distance", run(head + "    run dot_product\n    run vector_norm\n    run euclidean_distance\n    print dot_result, norm_result, dist_result\n"),
      [sum(a*b for a, b in zip(A, B)), math.sqrt(sum(a*a for a in A)), math.sqrt(sum((a-b)**2 for a, b in zip(A, B)))])
check("zeros/ones/fill/linspace", run("    set size to 5.0\n    set fill_value to 7.0\n    run fill\n"
      "    set start to 2.0\n    set end to 3.0\n    run linspace\n    run sum\n    print sum_result\n    run ones\n    run sum\n    print sum_result\n    run zeros\n    run sum\n    print sum_result\n"),
      [12.5, 5.0, 0.0])
check("linspace size 1 (no NaN)", run("    set size to 1.0\n    set start to 4.0\n    set end to 9.0\n    run linspace\n    load from arr at index 0.0 into v\n    print v\n"), [4.0])
xs = [0.0, 0.5, 1.0, -1.0, 2.0, 3.0, -3.0, 3.14159, 7.0, -10.0, 100.0, 12345.678]
for fn, name, var in ((math.sin, "sin_taylor", "sin_val"), (math.cos, "cos_taylor", "cos_val")):
    body = "".join(f"    set x to {x!r}\n    run {name}\n    print {var}\n" for x in xs)
    check(name, run(body), [fn(x) for x in xs], 1e-6)
body = "".join(f"    set x to {x!r}\n    run tan_taylor\n    print tan_val\n" for x in [0.0, 0.5, 1.0, -1.0])
check("tan_taylor", run(body), [math.tan(x) for x in [0.0, 0.5, 1.0, -1.0]], 1e-5)
ps = [(2.0, 10.0), (2.0, -3.0), (-3.0, 3.0), (5.0, 0.0), (1.5, 4.0), (10.0, 20.0)]
check("power (incl. negative exponents)", run("".join(f"    set base to {b!r}\n    set exponent to {e!r}\n    run power\n    print result\n" for b, e in ps)),
      [b**e for b, e in ps], 1e-6)
ls = [1.0, 2.0, 10.0, 0.5, 0.001, 123456.0, 1e10, 1e-8, 3.0]
check("float_ln / float_log10", run("".join(f"    set log_input to {x!r}\n    run float_ln\n    print log_val\n    run float_log10\n    print log10_val\n" for x in ls)),
      [v for x in ls for v in (math.log(x), math.log10(x))], 1e-6)
out = run("    set log_input to 0.0\n    run float_ln\n    print log_val\n")
ok = out == ["nan"]; print(("PASS " if ok else "FAIL ") + "float_ln(0) is nan"); fails += not ok
uh = arr("arr", A) + arr("arr2", B) + f"    set size to {float(n)!r}\n"
for fnm, f in (("add_arrays", lambda a, b: a+b), ("subtract_arrays", lambda a, b: a-b), ("multiply_arrays", lambda a, b: a*b), ("divide_arrays", lambda a, b: a/b)):
    body = uh + f"    run {fnm}\n" + "".join(f"    load from result_arr at index {float(i)!r} into v\n    print v\n" for i in range(n))
    check(fnm, run(body), [f(a, b) for a, b in zip(A, B)])
body = uh + "    run absolute_array\n" + "".join(f"    load from arr at index {float(i)!r} into v\n    print v\n" for i in range(n))
check("absolute_array", run(body), [abs(a) for a in A])
print(f"\n{fails} failure(s)"); sys.exit(1 if fails else 0)
