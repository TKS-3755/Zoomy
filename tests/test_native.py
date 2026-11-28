#!/usr/bin/env python3
"""Programs that must compile to a native ELF (not the Python backend) and give the expected output."""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)

CASES = [
("pipeline", 'set x to 10 and add 5 and multiply by 2\nprint x', "", "30\n", 0),
("pipeline divide by itself", 'set x to 10 and divide by x\nprint x', "", "1\n", 0),
("multi target", 'set x to 6 and set y to 3 and divide x and y by 3\nprint x, " ", y\nadd 1 to x and y\nprint x, " ", y', "", "2 1\n3 2\n", 0),
("conversational vs structural", 'set a to 10 + 5 * 2\nStructurally,\n    set b to 10 + 5 * 2\n    set c to (0.5 × 9.8 × 5 ^ 2) + 60\nprint a, " ", b, " ", c', "", "30 20 182.5\n", 0),
("convert character", "convert the character '7' to a number and store the result in n\nprint n, \" \", input_ok\nconvert the character 'x' to a number and store the result in n\nprint n, \" \", input_ok", "", "7 1\nnan 0\n", 0),
("convert the number to ASCII prints the letter", "convert the number 101 to ASCII and store the result in s\nprint s, s\nprint \"[{s}]\"", "", "ee\n[e]\n", 0),
("read digits", "read the next character into c\nconvert the character c to a number and store the result in d\nprint d", "7", "7\n", 0),
("power", 'print 2 ^ 10, " ", 2 ^ -1, " ", 2 ^ 0.5, " ", (-2) ^ 3, " ", 0 ^ 0', "", "1024 0.5 1.414214 -8 1\n", 0),
("mod and remainder", 'print -7 mod 3, " ", remainder of -7 divided by 3', "", "2 -1\n", 0),
("and / or / not", 'set a to 3\nif a is at least 1 and a is at most 5:\n    print "in"\nif a is 1 or a is 3:\n    print "odd"\nif not (a is 3):\n    print "no"\nelse:\n    print "yes"', "", "in\nodd\nyes\n", 0),
("else if", 'set a to 5\nif a is 1:\n    print "one"\nelse if a is 5:\n    print "five"\nelse:\n    print "other"', "", "five\n", 0),
("stop and skip", 'set n to 0\nwhile n is less than 10:\n    add 1 to n\n    if n is 2:\n        skip\n    if n is 5:\n        stop\n    write n\nprint', "", "134\n", 0),
("arrays with formulas", 'allocate array a with 3 slots\nset i to 0\nwhile i is less than 3:\n    store i * i + 1 in a at index i\n    add 1 to i\nload from a at index 1 + 1 into v\nprint v', "", "5\n", 0),
("finish with a formula", 'finish with 3 + 4', "", "", 7),
("pi", 'print pi', "", "3.141593\n", 0),
("index error", 'allocate array a with 2 slots\nset i to 1 + 1\nstore 1 in a at index i', "", "", 255),
("routines", 'routine bump:\n    add 1 to n\nset n to 5\nrun bump\nrun bump\nprint n', "", "7\n", 0),
]
CASES += [
("english: declared numbers", 'Let a number be called x\nCreate a number named y\nDefine a number as z\nset x to 4\nset the y to x * 2\nset z to y - x\nprint x, " ", y, " ", z', "", "4 8 4\n", 0),
("english: arrays with slots", 'Create an array named cells with 3 slots\nLet a number be called i\nLet a number be called v\nuntil i is 3:\n    store i * i + 1 in cells at index i\n    add 1 to i\nload from cells at index 2 into v\nprint v', "", "5\n", 0),
("english: shadowing and unless", 'Let a number be called n\nset n to 1\nif yes:\n    Let a number be called n\n    set n to 7\n    print n\nunless n is 2:\n    print n', "", "7\n1\n", 0),
("english: neither / between", 'Let a number be called n\nset n to 5\nif n is between 1 and 9 but neither n is 3 nor n is 4:\n    print "ok"', "", "ok\n", 0),
("english: routines", 'Let a number be called n\nroutine bump:\n    add 1 to n\nset n to 5\nrun bump\nrun bump\nprint n', "", "7\n", 0),
]
CASES += [
("5.1 for loop", 'Let a number be called t\nfor i from 1 to 5:\n    add i to t\nprint t', "", "15\n", 0),
("5.1 for loop with a step, down and fractional", 'for i from 10 to 1 by -3:\n    write i, " "\nfor x from 0 to 1 by 0.25:\n    write x, " "\nprint', "", "10 7 4 1 0 0.25 0.5 0.75 1 \n", 0),
("5.1 for loop that never runs", 'for i from 5 to 1:\n    print "never"\nprint "done"', "", "done\n", 0),
("5.1 for loop: stop and skip", 'for i from 1 to 10:\n    if i is 3:\n        skip\n    if i is 6:\n        stop\n    write i\nprint', "", "1245\n", 0),
("5.1 for loop: zero step is an error", 'for i from 1 to 3 by 0:\n    print i', "", "", 255),
("5.1 for loop: far too long is an error", 'for i from 1 to 1e300:\n    print i', "", "", 255),
("5.1 repeat", 'repeat 3 times:\n    write "ab"\nprint', "", "ababab\n", 0),
("5.1 repeat forever", 'Let a number be called n\nrepeat forever:\n    add 1 to n\n    if n is 4:\n        stop\nprint n', "", "4\n", 0),
("5.1 repeat: a negative count is an error", 'repeat 0 - 1 times:\n    print 1', "", "", 255),
("5.1 for each over an array", 'Create an array named xs with 4 slots\nLet a number be called t\nfor i from 0 to 3:\n    set item i of xs to i * i\nfor each x in xs:\n    add x to t\nprint t', "", "14\n", 0),
("5.1 array indexing, length, first, last", 'Create an array named xs with 3 slots\nset item 0 of xs to 4\nset item 2 of xs to 9\nadd 1 to item 0 of xs\nprint item 0 of xs, " ", length of xs, " ", the first of xs, " ", the last of xs', "", "5 3 5 9\n", 0),
("5.1 array index out of range", 'Create an array named xs with 2 slots\nprint item 2 of xs', "", "", 255),
("5.1 functions", 'define area with w and h:\n    give back w * h\nprint area(3, 4) + 1\nLet a number be called r\ncall area with 2 and 5 and store the result in r\nprint r', "", "13\n10\n", 0),
("5.1 recursion", 'define fact with n:\n    if n is at most 1:\n        give back 1\n    give back n * fact(n - 1)\nprint fact(10)\ndefine fib with n:\n    Let a number be called lo\n    Let a number be called hi\n    if n is less than 2:\n        give back n\n    set lo to fib(n - 1)\n    set hi to fib(n - 2)\n    give back lo + hi\nprint fib(20)', "", "3628800\n6765\n", 0),
("5.1 mutual recursion", 'define even with n:\n    if n is 0:\n        give back 1\n    give back odd(n - 1)\ndefine odd with n:\n    if n is 0:\n        give back 0\n    give back even(n - 1)\nprint even(10), odd(7), even(7)', "", "110\n", 0),
("5.1 runaway recursion is an error", 'define f with n:\n    give back f(n + 1)\nprint f(1)', "", "", 255),
("5.1 yes/no values", 'Let a flag be called big\nLet a number be called n\nset n to 7\nset big to n is greater than 5\nprint big, " ", n is 3, " ", not big\nif big:\n    print "big"\nwhile not big:\n    stop', "", "yes no no\nbig\n", 0),
("5.1 make: globals reach every function", 'define bump with k:\n    add k to total\n    set item 1 of marks to total\nmake total a global number\nmake marks a global array with 3 slots\nfor i from 1 to 3:\n    call bump with i\nprint total, " ", item 1 of marks', "", "6 6\n", 0),
("5.1 a print is worked out before it is written", 'define loud:\n    print "inside"\n    give back 7\nprint "x", loud()', "", "inside\nx7\n", 0),
("5.1 an error inside a print leaves no half line", 'Create an array named xs with 1 slots\nprint "x", item 5 of xs', "", "", 255),
]
CASES = [c if c[0].startswith(("english", "5.1")) else (c[0], "Simply,\n" + "".join("    " + l if l.strip() else l for l in c[1].splitlines(True)),) + c[2:] for c in CASES]
fails = 0
for name, prog, stdin, want, code in CASES:
    with tempfile.TemporaryDirectory() as t:
        src, exe = os.path.join(t, "t.zmy"), os.path.join(t, "t")
        open(src, "w").write(prog + "\n")
        b = subprocess.run([sys.executable, os.path.join(ROOT, "zoomy.py"), src, "-o", exe], capture_output=True, text=True)
        native = "static ELF" in b.stdout
        r = subprocess.run([exe], input=stdin.encode(), capture_output=True, timeout=20) if native else None
        ok = native and r.stdout.decode() == want and r.returncode == code
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails += 1
        print("   build:", b.stdout.strip()[:200], b.stderr.strip()[:200], "\n   got:", r and (r.stdout, r.returncode))
# Python libraries are still refused (clearly) when native is forced
r = subprocess.run([sys.executable, os.path.join(ROOT, "zoomy.py"), "--native", os.path.join(ROOT, "examples", "python_libs.zmy")], capture_output=True, text=True)
ok = "[Error]" in r.stdout and r.returncode == 1
print(("PASS " if ok else "FAIL ") + "--native refuses a program that uses Python libraries")
fails += not ok
print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
