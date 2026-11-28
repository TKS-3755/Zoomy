#!/usr/bin/env python3
"""Zoomy 8: the same action in many voices - chatty / slang, official / formal, old-fashioned.
Each phrase must read as the plain sentence; words that are also good variable names must still work as variable names;
and a whole program written in three voices must print the same thing."""
import os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import zoomy_sentence as zs

fails = 0


def check(name, ok, detail=""):
    global fails
    if not ok:
        fails += 1
        print(f"FAIL {name}: {detail}")


# phrase -> the plain statement(s) it means
TABLE = [
    # printing
    ('shout "hi"', ['print "hi"']), ('yell x', ['print x']), ('spit out x', ['print x']), ("show me x", ["print x"]), ("let me see x", ["print x"]),
    ("lemme see x", ["print x"]), ("print out x", ["print x"]),
    ("output x", ["print x"]), ("emit x", ["print x"]), ("announce x", ["print x"]), ("report x", ["print x"]), ("present x", ["print x"]),
    ("state x", ["print x"]), ("echo x", ["print x"]), ("render x", ["print x"]),
    ("behold x", ["print x"]), ("Behold, x", ["print x"]), ('proclaim "hi"', ['print "hi"']), ("utter x", ["print x"]), ("recite x", ["print x"]),
    ("declare x", ["print x"]), ("lo and behold x", ["print x"]), ("hear ye x", ["print x"]), ("let it be known that x", ["print x"]),
    # setting
    ("stash 5 in x", ["set x to 5"]), ("stick 5 into x", ["set x to 5"]), ("chuck 5 in x", ["set x to 5"]), ("toss 1 into counts at word", ["put 1 in counts at word"]),
    ("initialise x to 4", ["set x to 4"]), ("initialize x to 4", ["set x to 4"]), ("assign x the value 9", ["set x to 9"]), ("assign x the value of y", ["set x to y"]),
    ("let x equal 4", ["set x to 4"]), ("let x be 4", ["set x to 4"]), ("make x be 3", ["set x to 3"]), ("designate x the value 2", ["set x to 2"]),
    ("x becomes x plus 1", ["set x to x plus 1"]), ("x shall be 5", ["set x to 5"]), ("x shall become 5", ["set x to 5"]), ("x will be 5", ["set x to 5"]),
    ("y gets 7", ["set y to 7"]), ("x is now 7", ["set x to 7"]), ("x doth become 7", ["set x to 7"]),
    # arithmetic
    ("bump x by 3", ["add 3 to x"]), ("bump x", ["add 1 to x"]), ("increment x", ["add 1 to x"]), ("augment x by 2", ["add 2 to x"]), ("raise x by 2", ["add 2 to x"]),
    ("tack 4 onto x", ["add 4 to x"]), ("tack on 4 to x", ["add 4 to x"]),
    ("decrement x", ["subtract 1 from x"]), ("reduce x by 2", ["subtract 2 from x"]), ("lower x by 2", ["subtract 2 from x"]), ("diminish x by 2", ["subtract 2 from x"]),
    ("deduct 3 from x", ["subtract 3 from x"]), ("knock 3 off x", ["subtract 3 from x"]), ("shave 2 off x", ["subtract 2 from x"]), ("take 2 off x", ["subtract 2 from x"]),
    ("scale x by 3", ["multiply x by 3"]), ("square x", ["multiply x by x"]),
    # leaving loops, the program, giving back
    ("bail out", ["stop"]), ("bail", ["stop"]), ("break out of the loop", ["stop"]), ("get out", ["stop"]), ("cease the loop", ["stop"]),
    ("carry on", ["skip"]), ("next one", ["skip"]), ("proceed to the next iteration", ["skip"]), ("move on to the next one", ["skip"]),
    ("call it a day", ["finish"]), ("wrap it up", ["finish"]), ("that's all, folks", ["finish"]), ("we are done", ["finish"]), ("quit", ["finish"]),
    ("exit with 3", ["finish with 3"]), ("conclude with 2", ["finish with 2"]),
    ("hand back x + 1", ["give back x + 1"]), ("yield 5", ["give back 5"]), ("answer with x", ["give back x"]), ("send back x", ["give back x"]),
    # polite, chatty and old-fashioned openings
    ("Kindly print x", ["print x"]), ("Please kindly shout x", ["print x"]), ("I would like you to print x", ["print x"]), ("Let's print x", ["print x"]),
    ("go ahead and set x to 1", ["set x to 1"]), ("Prithee, print x", ["print x"]), ("Verily, print x", ["print x"]), ("Hereby set x to 3", ["set x to 3"]),
    ("Alright, print x", ["print x"]), ("So print x", ["print x"]), ("Hey, print x", ["print x"]), ("We shall print x", ["print x"]), ("Time to print x", ["print x"]),
    ("Furthermore, print x", ["print x"]), ("Hereby assign x the value 3", ["set x to 3"]), ("Prithee, x shall become 7", ["set x to 7"]),
    # conditions, else, loops
    ("in case x is 5:", ["if x is 5:"]), ("supposing that x is 5:", ["if x is 5:"]), ("assuming x is 5:", ["if x is 5:"]), ("given that x is 5:", ["if x is 5:"]),
    ("in the event that x is 5:", ["if x is 5:"]), ("on condition that x is 5:", ["if x is 5:"]), ("anytime x is 4:", ["if x is 4:"]), ("every time x is 4:", ["if x is 4:"]),
    ("so long as x is below 3:", ["while x is below 3:"]), ("whilst x is below 3:", ["while x is below 3:"]), ("for as long as x is below 3:", ["while x is below 3:"]),
    ("keep going while x is below 3:", ["while x is below 3:"]), ("until such time as x is 3:", ["until x is 3:"]),
    ("or else:", ["otherwise:"]), ("failing that:", ["otherwise:"]), ("alternatively:", ["otherwise:"]), ("contrariwise:", ["otherwise:"]), ("in any other case:", ["otherwise:"]),
    ("loop 5 times:", ["repeat 5 times:"]), ("iterate 5 times:", ["repeat 5 times:"]), ("do this 5 times:", ["repeat 5 times:"]), ("go around 5 times:", ["repeat 5 times:"]),
    ("loop forever:", ["repeat forever:"]), ("go through each score in scores:", ["for each score in scores:"]), ("loop over every score in scores:", ["for each score in scores:"]),
    ("for every score in scores:", ["for each score in scores:"]),
    ('print x in case y is 3, or else print z', ["if y is 3:", "print x", "otherwise:", "print z"]),
    ('print x whilst y is 2', ["while y is 2:", "print x"]), ('print x so long as y is 2', ["while y is 2:", "print x"]),
    ("if x is 3 then bump y by 2 else knock 1 off y", ["if x is 3:", "add 2 to y", "otherwise:", "subtract 1 from y"]),
    # comparing
    ("if x exceeds 3:", ["if x is above 3:"]), ("if x falls short of 3:", ["if x is below 3:"]), ("if x equals 3:", ["if x is 3:"]), ("if x is exactly 3:", ["if x is 3:"]),
    ("if x differs from 3:", ["if x is not 3:"]), ("if x does not exceed 3:", ["if x is at most 3:"]), ("if x is no greater than 3:", ["if x is at most 3:"]),
    ("if x has reached 3:", ["if x is at least 3:"]), ("if x is no less than 3:", ["if x is at least 3:"]), ("if x is greater than or equal to 3:", ["if x is at least 3:"]),
    ("if x is less than or equal to 3:", ["if x is at most 3:"]), ("if x is unequal to 3:", ["if x is not 3:"]),
]
for text, want in TABLE:
    try:
        got = [t for _, t in zs.normalize(text)]
    except Exception as ex:
        got = [f"ERROR {ex}"]
    check("reads as " + repr(want) + ": " + text, [g.lower() for g in got] == [w.lower() for w in want], got)

# number words: dozen, score, naught ...
for words, n in ((["a", "dozen"], None), (["two", "dozen"], 24), (["three", "score"], 60), (["naught"], 0), (["a", "gross"], None), (["two", "hundred", "dozen"], 2400)):
    if n is not None:
        check("number " + " ".join(words), zs.number_run(words) == n, zs.number_run(words))


def zoomy(src, *flags, stdin=b""):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.zmy")
        open(p, "w").write(src)
        r = subprocess.run([sys.executable, os.path.join(ROOT, "zoomy.py"), p, *flags], capture_output=True, text=True, timeout=120, cwd=d)
        return r.returncode, r.stdout, r.stderr


# words that are also good variable names stay variable names
KEEP = """Let a number be called state
Let a number be called report
Let a number be called output
Let a number be called square
Let a number be called end
Let a number be called yield
set state to 5
set report to 6
set output to 7
set square to 8
set end to 9
set yield to 10
if state is 5:
    print "state ok"
if report is 6 and output is 7:
    print "report output ok"
if square is 8 and end is 9 and yield is 10:
    print "square end yield ok"
print state + report + output + square + end + yield
"""
rc, out, err = zoomy(KEEP, "--python", "--run")
check("variables named like voice verbs", rc == 0 and out.split("\n")[:3] == ["state ok", "report output ok", "square end yield ok"] and "45" in out, (rc, out, err))

# one program, three voices, the same output on every backend that can run it
PLAIN = """Let a number be called x
Let a number be called y
Let a number be called total
set x to 12
set y to 40
set total to 0
add 3 to x
subtract 2 from y
repeat 3 times:
    add x to total
    multiply x by 2
if total is above 100:
    print "big"
otherwise:
    print "small"
while y is above 36:
    subtract 1 from y
print total
print y
"""
CHATTY = """(chatty)
Let a number be called x
Let a number be called y
Let a number be called total
stash a dozen in x
chuck 40 in y
y gets naught plus 40
total becomes zilch
bump x by 3
knock 2 off y
loop three times:
    tack x onto total
    scale x by 2
in case total exceeds 100, shout "big", or else shout "small"
keep going while y is above 36:
    shave 1 off y
shout total
shout y
"""
FORMAL = """(formal and old-fashioned)
Let a number be called x
Let a number be called y
Let a number be called total
Kindly initialise x to twelve
Prithee, y shall become forty
Hereby assign total the value naught
Increment x by three
Deduct two from y
iterate three times:
    augment total by x
    scale x by two
supposing that total is greater than 100:
    proclaim "big"
failing that:
    proclaim "small"
so long as y is above 36:
    decrement y
behold total
behold y
"""
base = None
for name, src in (("plain", PLAIN), ("chatty", CHATTY), ("formal", FORMAL)):
    rc, out, err = zoomy(src, "--python", "--run")
    check("voice program " + name, rc == 0, (rc, out, err))
    if base is None:
        base = out
        check("plain program output", out.split() == ["big", "105", "36"], out)
    else:
        check("voice program " + name + " prints the same as the plain one", out == base, (out, base))
    if name != "plain":
        rc2, out2, _ = zoomy(src, "--native", "--run")
        out2 = "".join(l + "\n" for l in out2.splitlines() if not l.startswith("[Success]"))
        check("voice program " + name + " on the native backend", out2 == base, (rc2, out2))
print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
