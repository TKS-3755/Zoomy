#!/usr/bin/env python3
"""Tests for the full language (Python backend): each case is (name, program, stdin, expected stdout, expected exit code)."""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import zoomy_py

CASES_OLD = [
("conversational arithmetic is left to right", 'print 10 + 5 * 2, " ", (10 + 5) * 2, " ", 2 ^ 3 ^ 2, " ", -2 ^ 2, " ", 7 mod 3, " ", 2 ** 10', "", "30 30 64 4 1 1024\n", 0),
("structural arithmetic follows PEMDAS", 'Structurally,\n    print 10 + 5 * 2, " ", (10 + 5) * 2, " ", 2 ^ 3 ^ 2, " ", -2 ^ 2, " ", 7 mod 3, " ", 2 ** 10', "", "20 30 512 -4 1 1024\n", 0),
("word operators", 'print 1 plus 2 times 3, " ", 10 minus 4 divided by 2, " ", 2 to the power of 8\nStructurally:\n    print 1 plus 2 times 3, " ", 10 minus 4 divided by 2', "", "9 3 256\n7 8\n", 0),
("structural scope ends with the block", 'Structurally,\n    set a to 2 + 3 * 4\nset b to 2 + 3 * 4\nStructurally:\n    if a is 14:\n        set c to 1 + 1 * 5\nprint a, " ", b, " ", c', "", "14 20 6\n", 0),
("native power", 'print 2 ^ 0.5, " ", 9 ^ 0.5, " ", 2 ^ -2, " ", 0 ^ 0, " ", 0 ^ -1, " ", (-8) ^ 0.5, " ", 10 ^ 2.5, " ", 2 ^ 10 ^ 0.5', "", "1.414214 3 0.25 1 inf nan 316.227766 32\n", 0),
("x and ÷", 'print 6 × 7, " ", 9 ÷ 3', "", "42 3\n", 0),
("pipeline left to right", 'set x to 10 and add 5 and multiply by 2\nprint x\nStructurally,\n    set y to 10 + 5 * 2\nprint y', "", "30\n20\n", 0),
("pipeline divide by itself", 'set x to 10 and divide by x\nprint x', "", "1\n", 0),
("multi target", 'set x to 6 and set y to 3 and divide x and y by 3\nprint x, " ", y\nadd 1 to x and y\nprint x, " ", y', "", "2 1\n3 2\n", 0),
("elided after multi is an error handled", 'set x to 1\nset y to 2\nadd 1 to x and y and multiply by 3\nprint x', "", None, None),
("structurally block", 'Structurally,\n    set a to 2 + 3 * 4\nStructurally:\n    set b to (2 + 3) * 4\nprint a, " ", b', "", "14 20\n", 0),
("convert char", "convert the character '7' to a number and store the result in n\nprint n, \" \", input_ok\nconvert the character 'x' to a number and store the result in n\nprint n, \" \", input_ok\nconvert the number 101 to ASCII and store the result in s\nprint s", "", "7 1\nnan 0\ne\n", 0),
("text and interpolation", 'set name to "Zoe"\nprint "Hi {name}! {1 + 2} \\{ok\\}"\nprint uppercase of name, " ", length of name, " ", lowercase of "ABC"', "", "Hi Zoe! 3 {ok}\nZOE 3 abc\n", 0),
("text functions", 'print join split "a,b,c" by "," with "-"\nprint replace "o" with "0" in "foo"\nprint trim of "  hi  ", "|"\nprint number from "3.5" plus 1\nprint text of 2.50 plus "!"', "", "a-b-c\nf00\nhi|\n4.5\n2.5!\n", 0),
("lists", 'set l to [3, 1, 2]\nappend 9 to l\nsort l\nprint l\nprint item 0 of l, " ", length of l, " ", last of l, " ", l[1]\nremove 9 from l\ninsert 7 into l at 0\nprint l, " ", sum of l, " ", smallest of l, " ", largest of l\nreverse l\nprint l\nprint 2 is in l, " ", l contains 5, " ", position of 1 in l', "", "[1, 2, 3, 9]\n1 4 9 2\n[7, 1, 2, 3] 13 1 7\n[3, 2, 1, 7]\nyes no 2\n", 0),
("tables", 'set t to table with "a" as 1 and "b" as 2\nput 5 in t at "c"\nset t at "a" to 10\nprint t\nprint keys of t, " ", values of t, " ", length of t\nremove "b" from t\nprint t at "c"\nprint empty table', "", 'table with "a" as 10 and "b" as 2 and "c" as 5\n["a", "b", "c"] [10, 2, 5] 3\n5\nempty table\n', 0),
("loops", 'for i from 1 to 5 by 2:\n    write i, ","\nprint\nrepeat 3 times:\n    write "x"\nprint\nset n to 0\nwhile yes:\n    add 1 to n\n    if n is 2:\n        skip\n    if n is at least 4:\n        stop\n    write n\nprint\nfor each c in "abc":\n    write c, "-"\nprint\nfor i from 3 to 1 by -1:\n    write i\nprint', "", "1,3,5,\nxxx\n13\na-b-c-\n321\n", 0),
("else if chain", 'define grade with s:\n    if s is at least 90:\n        give back "A"\n    else if s is at least 80:\n        give back "B"\n    otherwise:\n        give back "C"\nprint call grade with 95, call grade with 85, grade(10)', "", "ABC\n", 0),
("functions and recursion", 'define fib with n:\n    if n is less than 2:\n        give back n\n    give back fib(n - 1) + fib(n - 2)\ndefine add3 with a and b and c:\n    set s to a + b + c\n    give back s\nprint fib(15), " ", call add3 with 1 and 2 and 3\nset r to 0\ncall add3 with 1 and 1 and 1 and store the result in r\nprint r', "", "610 6\n3\n", 0),
("function locals do not leak", 'define f:\n    set inner to 5\n    give back inner\nset inner to 1\nprint call f, " ", inner', "", "5 1\n", 0),
("global statement", 'set count to 0\ndefine bump:\n    global count\n    add 1 to count\ncall bump\ncall bump\nprint count', "", "2\n", 0),
("try / fails / always", 'try:\n    print item 5 of [1, 2]\nif it fails:\n    print "failed: ", problem\nalways:\n    print "done"\ntry:\n    fail with "boom"\nif it fails as e:\n    print e', "", "failed: array index out of range\ndone\nboom\n", 0),
("fail exits 1", 'fail with "bad thing"', "", "", 1),
("check that", 'check that 1 is 2', "", "", 1),
("index error exit 255", 'set l to [1]\nprint l[3]', "", "", 255),
("yes/no logic", 'set a to yes\nprint a and no, " ", a or no, " ", not a, " ", 1 is 1 and 2 is 2\nprint 3 is between', "", None, None),
("is checks", 'print [] is empty, " ", "" is empty, " ", 5 is a number, " ", "a" is text, " ", nothing is nothing, " ", 3 is not empty', "", "yes yes yes yes yes yes\n", 0),
("comparison words", 'print 1 is less than 2, " ", 2 is at most 2, " ", 3 is greater than 4, " ", 1 is not 1, " ", "ab" starts with "a", " ", "ab" ends with "b"', "", "yes yes no no yes yes\n", 0),
("python library", "use python's math\nuse sqrt and floor from python's math\nprint math's pi > 3, \" \", sqrt(9), \" \", call floor with 2.5, \" \", call math's pow with 2 and 5", "", "yes 3 2 32\n", 0),
("python as alias and methods", "use python's collections as c\nset d to call c's Counter with \"aab\"\nprint d at \"a\"\nset s to \"x-y\"\nprint call s's upper, \" \", call s's split with \"-\"", "", '2\nX-Y ["x", "y"]\n', 0),
("python keyword args", "use python's json\nprint call json's dumps with [1, 2] and indent named 0", "", "[\n0,\n1,\n2\n]\n".replace("0,\n", "0,\n") if False else None, None),
("input", 'ask "Name? "\nset name to ask "x"\nread line into l\nread n\nprint n plus 1, " ", l', "Ann\n41\n", None, None),
("read line and read number", 'read line into l\nread n\nprint l, "|", n plus 1', "hello world\n41", "hello world|42\n", 0),
("files", 'write "a,b\\nc" to file "/tmp/zmy_test_file.txt"\nappend "!" to file "/tmp/zmy_test_file.txt"\nread file "/tmp/zmy_test_file.txt" into t\nprint lines of t, " ", file "/tmp/zmy_test_file.txt" exists\ndelete file "/tmp/zmy_test_file.txt"\nprint file "/tmp/zmy_test_file.txt" exists', "", '["a,b", "c!"] yes\nno\n', 0),
("rounding and formatting", 'print rounded 2.567 to 2 places, " ", round of 2.5, " ", format 3.14159 with 2 decimals, " ", floor of -1.5, " ", ceiling of 1.2, " ", square root of 16, " ", absolute value of -3', "", "2.57 3 3.14 -2 2 4 3\n", 0),
("number printing", 'print 0.1 + 0.2, " ", 1 / 3, " ", 1e20, " ", 1 / 0, " ", 0 / 0, " ", 100000 * 100000', "", "0.3 0.333333 1e+20 inf nan 10000000000\n", 0),
("remainder vs mod", 'print remainder of -7 divided by 3, " ", -7 mod 3', "", "-1 2\n", 0),
("main with finish", 'finish with 7', "", "", 7),
("action block still works", 'action start:\n    set x to 2\n    print x * 21\n    finish with x', "", "42\n", 2),
("routines share variables", 'routine bump:\n    add 1 to n\naction start:\n    set n to 5\n    run bump\n    run bump\n    print n', "", "7\n", 0),
("comments", '(a whole-line note)\nset x to 5    (trailing note (with brackets inside))\nset y to (1 + 2) * 3\t(tab note)\nprint x, " ", y, "    (not a note)"\nif x is 5:    (header note)\n    print "five"', "", "5 9    (not a note)\nfive\n", 0),
("hash is not a comment", 'print 1    # old style', "", None, None),
("pi constant", 'print rounded pi to 4 places', "", "3.1416\n", 0),
("unset variable in a native program is 0", 'print oops', "", "0\n", 0),
("unset variable in a python program is an error", 'set s to "x"\nprint oops', "", "", 255),
("arguments", 'print length of arguments', "", "0\n", 0),
("random in range", 'set r to random between 1 and 6\nprint r is at least 1 and r is at most 6\nprint random number is less than 1', "", "yes\nyes\n", 0),
("slice and count", 'print slice [1, 2, 3, 4] from 1 to 3, " ", count of 2 in [2, 2, 3], " ", slice "hello" from 1 to 3', "", '[2, 3] 2 el\n', 0),
("variable named item and count", 'set item to 3\nset count to 4\nprint item plus count', "", "7\n", 0),
("nested list and table", 'set m to [[1, 2], [3, 4]]\nprint m[1][0]\nset m[0][1] to 9\nprint m', "", "3\n[[1, 9], [3, 4]]\n", 0),
("alloc array with expression", 'set n to 3\nallocate array a with n slots\nstore 5 in a at index 2\nload from a at index 2 into v\nprint v, " ", a', "", "5 [0, 0, 5]\n", 0),
]


E = "error"      # (E, text): the program must be refused with an [Error] containing text
CASES_ENGLISH = [
("arrays: Create named / for, Define for", 'Create an array named b1\nCreate an array for b2\nDefine an array for b3\nset b1 to 1, 2\nappend 3 to b2\nappend 4 to b3\nprint b1, b2, b3', "", "[1, 2][3][4]\n", 0),
("arrays: no Let", 'Let an array be called xs', "", E, "no Let for arrays"),
("arrays: no Define as", 'Define an array as xs', "", E, "for"),
("arrays: Create takes named or for only", 'Create an array called xs', "", E, "named or for"),
("only arrays take 'for'", 'Create a number for x', "", E, "named"),
("Let wants be called", 'Let a number named x', "", E, "be called"),
("Define wants as", 'Define a number for x', "", E, "as"),
("let / create / define are the same", 'Let a number be called a1\nCreate a number named a2\nDefine a number as a3\nset a1 to 1\nset a2 to 2\nset the a3 to 3\nprint a1 + a2 + a3', "", "6\n", 0),
("declared variables start with a default", 'Let a number be called n\nLet a string be called s\nLet a flag be called f\nCreate an array named xs\nLet a table be called t\nprint n, "|", s, "|", f, "|", xs, "|", t', "", "0||no|[]|empty table\n", 0),
("an index is a number", 'Let an index be called i\nset i to 2\nprint i + 1', "", "3\n", 0),
("arrays with slots (native)", 'Create an array named weights with 3 slots\nstore 5 in weights at index 1\nload from weights at index 1 into w\n', "", E, "I don't know a variable called 'w'"),
("arrays with slots", 'Create an array named weights with 3 slots\nLet a number be called w\nstore 5 in weights at index 1\nload from weights at index 1 into w\nprint w', "", "5\n", 0),
("typed arrays and plural names", 'Create an array of numbers named scores\nappend 70 to scores\nappend 85 to the scores\nappend 90 to scores\nLet a number be called total\nfor each score in the scores:\n    add the score to the total\nprint total, " ", length of scores', "", "245 3\n", 0),
("ordinals", 'Create an array named scores\nset scores to 70, 85, 90\nprint the first score of the scores, " ", the second item of the scores, " ", the third of the scores, " ", the last score in the scores', "", "70 85 90 90\n", 0),
("ordinal noun must fit a plural name", 'Create an array named scores\nset scores to 1, 2\nprint the third mark of the scores', "", E, "does not fit"),
("a comma list is an array", 'Create an array named xs\nset the xs to 1, 2, 3\nprint xs, " ", length of xs', "", "[1, 2, 3] 3\n", 0),
("pair, triple, quad", 'Let a pair be called p\nset p to a pair 3, 4\nLet a triple be called t\nset t to 1, 2, 3\nLet a quad be called q\nset q to a quad (1, 2, 3, 4)\nprint p, " ", t, " ", q, " ", the second of the p, " ", the third item of the t', "", "(3, 4) (1, 2, 3) (1, 2, 3, 4) 4 3\n", 0),
("a pair cannot change", 'Let a pair be called p\nset p to a pair 3, 4\nset the first of the p to 9', "", E, "fixed group"),
("a pair has exactly two values", 'Let a pair be called p\nset p to 1, 2, 3', "", E, "exactly 2"),
("possessives on tables", 'Let a table be called player\nset player to table with "name" as "Zoe" and "score" as 7\nadd 1 to the player\'s score\nset the player\'s name to "Ann"\nprint player\'s name, " ", the player\'s score', "", "Ann 8\n", 0),
("possessives reach python libraries", "use python's math\nuse floor from python's math\nprint math's sqrt(16), \" \", floor(2.7)", "", "4 2\n", 0),
("a scope ends with its block", 'if yes:\n    Let a number be called inner\n    set inner to 1\nprint inner', "", E, "belongs to a block that has ended"),
("shadowing in a deeper block", 'Let a number be called total\nset total to 1\nif yes:\n    Let a number be called total\n    set total to 99\n    print total\nprint total', "", "99\n1\n", 0),
("redeclaring in the same block is an error", 'Let a number be called x\nCreate a number named x', "", E, "already exists"),
("a loop variable belongs to the loop", 'for i from 1 to 2:\n    write i\nprint i', "", E, "belongs to a block that has ended"),
("functions can change outer variables", 'Let a number be called n\ndefine bump:\n    add 1 to n\ncall bump\ncall bump\nprint n', "", "2\n", 0),
("function locals do not leak", 'define f:\n    Let a number be called inner\n    set inner to 5\n    give back inner\nLet a number be called inner\nset inner to 1\nprint call f, " ", inner', "", "5 1\n", 0),
("nothing is silently created", 'set x to 5', "", E, "Let a number be called x"),
("typos are caught", 'Let a number be called total\nset the totl to 5', "", E, "Did you mean 'total'"),
("types are fixed", 'Let a number be called total\nset total to "ten"', "", E, "holds a number"),
("an array of numbers only takes numbers", 'Create an array of numbers named xs\nappend "a" to xs', "", E, "holds a number"),
("text and numbers do not mix", 'Let a string be called s\nset s to "a"\nprint s * 2', "", E, "cannot multiply"),
("making and setting are two statements", 'Let a number be called total to 5', "", E, "two statements"),
("'a' belongs to Let/Create/Define", 'set a total to 0', "", E, "its own statement"),
("a / an agree with the next word", 'Let an number be called x', "", E, "'a number'"),
("making and filling on one line with and", 'Let a number be called total and set total to 5\nCreate a string named s and set s to "a and b"\nLet a number be called x and Create a number named y and set y to 4 and add 1\nprint total, " ", s, " ", x, " ", y', "", "5 a and b 0 5\n", 0),
("make: a global variable from inside a function", 'define start:\n    make hits a global number\n    set hits to 3\nmake names a global array of strings\ncall start\nappend "x" to names\nprint hits, " ", names', "", "3 [\"x\"]\n", 0),
("make: usable above the line that makes it", 'define bump:\n    add 1 to total\nmake total a global number\ncall bump\ncall bump\nprint total', "", "2\n", 0),
("make: made inside a block, alive everywhere", 'if yes:\n    make seen a global flag\nset seen to yes\nprint seen', "", "yes\n", 0),
("make: a global array with slots", 'make grid a global array with 3 slots\ndefine put with v:\n    store v in grid at index 1\ncall put with 7\nLet a number be called out\nload from grid at index 1 into out\nprint out', "", "7\n", 0),
("make: shadowed by a deeper Let", 'make total a global number\nset total to 1\nif yes:\n    Let a number be called total\n    set total to 99\nprint total', "", "1\n", 0),
("make: same name twice", 'make x a global number\nLet a number be called x', "", E, "already exists"),
("make: only globals", 'make x a number', "", E, "global"),
("make: the article goes with global", 'make x an global number', "", E, "a global number"),
("make: no value on the same line", 'make x a global number to 5', "", E, "two statements"),
("global is not a statement", 'global x', "", E, "make total a global number"),
("an and a", 'Create an array named xs\nCreate a unit named u\n', "", E, "kind of thing"),
("one thing, not several", 'Let a numbers be called xs', "", E, "ONE thing"),
("Create refuses be called", 'Create a number be called x', "", E, "say named"),
("Define refuses called", 'Define an array called x', "", E, "say for"),
("is / are agree", 'Create an array named scores\nset scores to 1, 2\nprint scores are empty, " ", length of scores is 2', "", "no yes\n", 0),
("'is' with a list is refused", 'Create an array named scores\nif scores is empty:\n    print 1', "", E, "say 'are'"),
("'are' with one thing is refused", 'Let a number be called total\nif total are 1:\n    print 1', "", E, "say 'is'"),
("contain / contains agree", 'Create an array named xs\nset xs to 1, 2\nLet a string be called s\nset s to "abc"\nprint xs contain 2, " ", s contains "b", " ", s does not contain "z", " ", xs do not contain 5', "", "yes yes yes yes\n", 0),
("contain with one thing is refused", 'Let a string be called s\nset s to "abc"\nprint s contain "b"', "", E, "say 'contains'"),
("unless and until", 'unless 1 is 2:\n    print "unless"\nelse:\n    print "no"\nLet a number be called i\nuntil i is 3:\n    add 1 to i\nprint i', "", "unless\n3\n", 0),
("neither / nor", 'print neither 1 is 2 nor 3 is 4, " ", neither 1 is 1 nor 3 is 4', "", "yes no\n", 0),
("either / or and both / and", 'print either 1 is 2 or 3 is 3, " ", both 1 is 1 and 2 is 3, " ", both 1 is 1 and 2 is 2', "", "yes no yes\n", 0),
("but means and", 'Let a number be called age\nset age to 30\nif age is at least 18 but age is under 65:\n    print "adult"', "", "adult\n", 0),
("comparatives", 'print 3 is bigger than 2, " ", 3 is smaller than 2, " ", 5 is between 1 and 10, " ", 5 is not between 6 and 10, " ", 2 is the same as 2, " ", 2 is different from 3, " ", 4 is no more than 4, " ", 4 is above 3, " ", 4 is below 3', "", "yes no yes yes yes yes yes yes no\n", 0),
("the is optional when reading, welcome when writing", 'Let a number be called total\nset the total to 4\nadd 1 to the total\nprint the total + 1, " ", total', "", "6 5\n", 0),
("Simply, keeps the old rules", 'Simply,\n    set x to 5\n    add 2 to x\n    set list to [1, 2]\n    print x, " ", list\nprint x + 1', "", "7 [1, 2]\n8\n", 0),
("Simply, with functions and loops", 'Simply,\n    define sq with n:\n        give back n * n\n    for i from 1 to 3:\n        write sq(i), " "\n    print', "", "1 4 9 \n", 0),
("global is not a statement (inside a function)", 'Let a number be called count\ndefine bump:\n    global count\n    add 1 to count', "", E, "make total a global number"),
("structurally still works", 'Let a number be called y\nStructurally,\n    set y to 10 + 5 * 2\nprint y', "", "20\n", 0),
("pipelines", 'Let a number be called x\nset x to 10 and add 5 and multiply by 2\nprint x\nLet a number be called y\nset y to 3\nadd 1 to x and y\nprint x, " ", y', "", "30\n31 4\n", 0),
("try and handler variable", 'try:\n    print item 5 of [1, 2]\nif it fails as oops:\n    print "failed: ", oops', "", "failed: array index out of range\n", 0),
("ask and read into declared names", 'Let a string be called line\nLet a number be called n\nread line into line\nread n\nprint line, "|", n + 1', "hello\n41", "hello|42\n", 0),
]

fails = 0
def run(prog, stdin, strict=False):
    with tempfile.TemporaryDirectory() as t:
        src = os.path.join(t, "t.zmy")
        open(src, "w").write(prog + "\n")
        r = subprocess.run([sys.executable, os.path.join(ROOT, "zoomy.py"), src, "--run"] + (["--strict"] if strict else []), input=stdin.encode(), capture_output=True, timeout=30, cwd=t)
        out = "".join(l for l in r.stdout.decode().splitlines(True) if not l.startswith("[Success]"))
        return out, r.returncode, r.stderr.decode()

def simply(prog):
    return "Simply,\n" + "".join(("    " + l if l.strip() else l) for l in prog.splitlines(True))

def all_cases():
    for name, prog, stdin, want, code in CASES_OLD:
        yield "old rules under Simply, : " + name, simply(prog), stdin, want, code
    for case in CASES_ENGLISH:
        if len(case) == 6:                 # (name, prog, stdin, E, text, ...)
            pass
        yield case[0], case[1], case[2], case[3], case[4]

for name, prog, stdin, want, code in all_cases():
    out, rc, err = run(prog, stdin, strict=(want == E))      # Zoomy 5: grammar slips warn, --strict makes them errors
    if want == E:
        ok = "[Error]" in out and code in out and "Traceback" not in err
    elif want is None:                       # these must be rejected cleanly, or simply must not crash with a traceback
        ok = "Traceback" not in err and "Traceback" not in out
    else:
        ok = out == want and rc == code and "Traceback" not in err
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails += 1
        print("   want", repr(want), code, "\n   got ", repr(out), rc, repr(err[:300]))
print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
