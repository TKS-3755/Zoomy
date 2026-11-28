#!/usr/bin/env python3
"""Zoomy 5 tests: every feature of the grammar map, each case is (name, program, stdin, expected stdout or E, code-or-error-text)."""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)

E = "error"
PRE = 'Let a number be called x\nset x to 5\nCreate an array named scores\nset scores to 72, 88, 95, 40\n'

CASES = [
# ---- 1 trailing conditions, either order
("1 trailing if", PRE + 'print "yes" if x is 5\nprint "no" if x is 6', "", "yes\n", 0),
("1 trailing unless", PRE + 'print "a" unless x is 5\nprint "b" unless x is 6', "", "b\n", 0),
("1 trailing while and until", PRE + 'add 1 to x while x is below 8\nprint x\nsubtract 1 from x until x is 2\nprint x', "", "8\n2\n", 0),
("1 trailing if with otherwise", PRE + 'print "five" if x is 5, otherwise print "other"\nprint "five" if x is 6 otherwise print "other"', "", "five\nother\n", 0),
("1 fizzbuzz in one breath", 'for number from 1 to 5:\n    print "Fizz" if number mod 3 is 0\n    print number unless number mod 3 is 0', "", "1\n2\nFizz\n4\n5\n", 0),
# ---- 2 one-line if / then / otherwise
("2 if then otherwise", PRE + 'if x is 5 then print "five" otherwise print "other"\nif x is 6 then print "six" otherwise print "other"', "", "five\nother\n", 0),
("2 comma instead of then", PRE + 'if x is 5, print "five"\nif x is 5, then print "five again"', "", "five\nfive again\n", 0),
("2 one-line chain", PRE + 'if x is 4 then print "four" else if x is 5 then print "five" otherwise print "other"', "", "five\n", 0),
("2 unless then", PRE + 'unless x is 4 then print "not four"', "", "not four\n", 0),
("2 a bare if line explains itself", PRE + 'if x is 5 print "five"', "", E, "needs a ':'"),
# ---- 3 more if-words, as long as = while
("3 when and whenever", PRE + 'when x is 5:\n    print "w"\nwhenever x is 5:\n    print "ww"', "", "w\nww\n", 0),
("3 provided that and only if", PRE + 'provided that x is 5:\n    print "p"\nonly if x is 5:\n    print "o"', "", "p\no\n", 0),
("3 as long as repeats like while", PRE + 'as long as x is above 2:\n    subtract 1 from x\nprint x', "", "2\n", 0),
("3 as long as on one line", PRE + 'subtract 1 from x as long as x is above 0\nprint x', "", "0\n", 0),
("3 else if is a keyword", PRE + 'if x is 4:\n    print "four"\nelse if x is 5:\n    print "five"\nelse:\n    print "other"', "", "five\n", 0),
("3 otherwise if and else when", PRE + 'if x is 4:\n    print "four"\notherwise if x is 6:\n    print "six"\nelse when x is 5:\n    print "five"', "", "five\n", 0),
# ---- 4 joining statements
("4 semicolon", PRE + 'set x to 1; print x', "", "1\n", 0),
("4 then", PRE + 'set x to 2 then print x', "", "2\n", 0),
("4 comma and then / so", PRE + 'set x to 3, and then print x\nset x to 4, so print x', "", "3\n4\n", 0),
("4 comma and verb", PRE + 'set x to 6, and print x', "", "6\n", 0),
("4 line ends in a comma", PRE + 'set x to 7,\nprint x', "", "7\n", 0),
("4 line ends in and", PRE + 'if x is 5 and\n    x is below 9:\n    print "both"', "", "both\n", 0),
("4 pipelines still work", PRE + 'set x to 10 and add 5 and multiply by 2\nprint x', "", "30\n", 0),
# ---- 5 filler words
("5 please", PRE + 'Please print x', "", "5\n", 0),
("5 first next then finally", PRE + 'First, set x to 1\nNext, add 2 to x\nThen, print x\nFinally, print x plus 1.', "", "3\n4\n", 0),
("5 also now just", PRE + 'Also print x\nNow, print x\nJust print x', "", "5\n5\n5\n", 0),
# ---- 6 sentence style
("6 capital letters", PRE + 'Print x\nSet x to 7\nPrint x', "", "5\n7\n", 0),
("6 full stop and exclamation mark", PRE + 'print x.\nprint x!\nprint "done".', "", "5\n5\ndone\n", 0),
("6 a number keeps its decimal point", 'print 3.\nprint 3.5.', "", "3\n3.5\n", 0),
("6 capitalised block words", PRE + 'If x is 5:\n    Print "five"!\nElse:\n    Print "other"', "", "five\n", 0),
# ---- 7 questions
("7 yes/no questions", PRE + 'Is x above 3?\nIs x at least 10?\nAre scores empty?\nDoes scores contain 95?', "", "yes\nno\nno\nyes\n", 0),
("7 what / how many / how long / where", PRE + 'What is the largest of scores?\nHow many scores are above 80?\nHow many items are in scores?\nHow long is "hello"?\nWhere is 88 in scores?', "", "95\n2\n4\n5\n1\n", 0),
("7 a question about text", 'Let a string be called s\nset s to "hello"\nDoes s start with "he"?\nDoes s contain "z"?', "", "yes\nno\n", 0),
("7 question needs a question word", PRE + 'Print x?', "", E, "starts with is"),
# ---- 8 filter clauses
("8 that are", PRE + 'for each score in scores that are above 80:\n    print score', "", "88\n95\n", 0),
("8 where", PRE + 'for each s in scores where s is below 80:\n    print s', "", "72\n40\n", 0),
("8 which / who / not", PRE + 'print scores that are not above 80\nprint scores which are below 50', "", "[72, 40]\n[40]\n", 0),
("8 inside a sentence", PRE + 'print length of scores that are above 50\nif length of scores that are above 90 is 1:\n    print "one over 90"', "", "3\none over 90\n", 0),
("8 whose", 'Create an array named players\nset players to [table with "name" as "Ann" and "score" as 90, table with "name" as "Bo" and "score" as 40]\nfor each p in players whose score is above 50:\n    print p at "name"', "", "Ann\n", 0),
# ---- 9 there is / there are
("9 there are no", PRE + 'if there are no scores:\n    print "none"\nelse:\n    print "some"', "", "some\n", 0),
("9 there is a ... in", PRE + 'if there is a 88 in scores:\n    print "has 88"\nunless there is a 7 in scores:\n    print "no 7"\nif there is nothing in scores:\n    print "empty"', "", "has 88\nno 7\n", 0),
("9 there are some", PRE + 'if there are scores:\n    print "have scores"', "", "have scores\n", 0),
# ---- 10 quantifiers
("10 all of / any of / none of", PRE + 'if all of scores are above 30:\n    print "all"\nif any of scores are above 90:\n    print "any"\nif none of scores are below 10:\n    print "none"\nif all of scores are above 50:\n    print "WRONG"', "", "all\nany\nnone\n", 0),
("10 every / no / any ... in", PRE + 'if every score in scores is above 30:\n    print "every"\nif no score in scores is above 99:\n    print "no"\nif any score in scores is below 50:\n    print "some"', "", "every\nno\nsome\n", 0),
# ---- 11 it / them / its / their
("11 it", PRE + 'set x to 10 then print it\nadd 5 to x then print it', "", "10\n15\n", 0),
("11 them and its", PRE + 'sort scores then print them\nprint its length', "", "[40, 72, 88, 95]\n4\n", 0),
("11 it with nothing before", 'print it', "", E, "nothing to point at"),
# ---- 12 contractions
("12 isn't aren't doesn't don't", PRE + 'if x isn\'t 4:\n    print "a"\nif scores aren\'t empty:\n    print "b"\nif scores don\'t contain 7:\n    print "c"', "", "a\nb\nc\n", 0),
("12 apostrophes in text are left alone", PRE + 'print "it\'s fine, isn\'t it"', "", "it's fine, isn't it\n", 0),
("12 possessive still works", 'Let a table be called player\nset player to table with "score" as 9\nprint the player\'s score', "", "9\n", 0),
("12 character literals still work", 'print char 65\nprint \'A\'', "", "A\n65\n", 0),
# ---- 13 prepositions
("13 put at the end / start", PRE + 'put 5 at the end of scores\nput 1 at the start of scores\nprint scores', "", "[1, 72, 88, 95, 40, 5]\n", 0),
("13 insert before / after", PRE + 'insert 9 before item 1 of scores\ninsert 7 after item 0 of scores\nprint scores', "", "[72, 7, 9, 88, 95, 40]\n", 0),
("13 into onto out of from", 'Create an array named xs\nset xs to 1, 2, 3\nLet a table be called t\nset t to empty table\nput 5 into t at "k"\nLet a number be called n\nset n to 1\nadd 2 onto n\nremove 2 out of xs\nprint t, " ", n, " ", xs', "", 'table with "k" as 5 3 [1, 3]\n', 0),
("13 take from", PRE + 'take 2 from x\ntake 1 away from x\nprint x', "", "2\n", 0),
# ---- 14 verb synonyms
("14 show display say", 'show "a"\ndisplay "b"\nsay "c"', "", "a\nb\nc\n", 0),
("14 increase decrease double halve triple", PRE + 'increase x by 3\ndecrease x by 1\ndouble x\nhalve x\ntriple x\nincrease x\ndecrease x\nprint x', "", "21\n", 0),
("14 make sure / ensure that", PRE + 'make sure that x is 5\nensure x is above 1\nmake sure that x is 6', "", E, "check failed"),
("14 return and continue", 'define f with n:\n    return n plus 1\nfor i from 1 to 3:\n    continue if i is 2\n    write f(i), " "\nprint', "", "2 4 \n", 0),
# ---- 15 phrasal verbs
("15 add up", PRE + 'print add up scores', "", "295\n", 0),
("15 look up", 'Let a table be called t\nset t to table with "a" as 1 and "b" as 2\nprint look up "b" in t\nprint look "a" up in t', "", "2\n1\n", 0),
("15 round up down off", 'print round up 2.1, " ", round down 2.9, " ", round off 2.567 to 1 places, " ", round off 2.5', "", "3 2 2.6 3\n", 0),
# ---- 16 modals
("16 must stops the program", PRE + 'x must be at least 0\nprint "ok"\nx must be at least 10\nprint "never"', "", E, "x must be at least 10"),
("16 should warns and goes on", PRE + 'x should be at least 10\nprint "continues"', "", "continues\n", 0),
("16 cannot", PRE + 'x cannot be 5', "", E, "x cannot be 5"),
("16 mustn't and must not", PRE + 'x mustn\'t be 6\nx must not be 7\nscores must contain 95\nprint "fine"', "", "fine\n", 0),
# ---- 17 counting adverbs
("17 twice and times", PRE + 'print "hi" twice\nadd 1 to x 3 times\nprint x\nprint "once" once', "", "hi\nhi\n8\nonce\n", 0),
("17 number words count too", PRE + 'print "ho" three times', "", "ho\nho\nho\n", 0),
# ---- 18 conjunction extras
("18 yet means but", PRE + 'if x is above 3 yet x is below 9:\n    print "between"', "", "between\n", 0),
("18 not only but also", PRE + 'if not only x is above 3 but also x is below 9:\n    print "both"', "", "both\n", 0),
("18 because gives the reason", PRE + 'check that x is above 100 because "x must be big"', "", E, "x must be big"),
("18 because needs text", PRE + 'check that x is 5 because x', "", E, "reason as text"),
# ---- 19 friendlier mistakes
("19 two actions on one line", PRE + 'set x to 1 print x', "", E, "two actions"),
("19 past tense", PRE + 'added 5 to x', "", E, "present tense: say 'add 5 to x'"),
("19 future tense", PRE + 'will add 5 to x', "", E, "present tense"),
("19 lone because", PRE + 'because x is 5', "", E, "goes after one"),
("19 although", PRE + 'although x is 5', "", E, "no 'although'"),
# ---- 20 number words
("20 number words", 'repeat three times:\n    write "a"\nprint\nLet a number be called n\nset n to twenty one\nprint n, " ", n plus one hundred, " ", five times ten, " ", two thousand five', "", "aaa\n21 121 50 2005\n", 0),
("20 a variable called zero wins", 'Let a number be called zero\nset zero to 7\nprint zero', "", "7\n", 0),
# ---- grammar slips warn, --strict stops
("soft: a / an", 'Let an number be called q\nprint q', "", "0\n", 0),
("soft: is / are", PRE + 'if scores is empty:\n    print "e"\nprint "ok"', "", "ok\n", 0),
("strict: a / an", 'Let an number be called q', "--strict", E, "not 'an number'"),
("strict: is / are", PRE + 'if scores is empty:\n    print "e"', "--strict", E, "say 'are'"),
("strict: ordinal noun", PRE + 'print the first mark of the scores', "--strict", E, "does not fit"),
# ---- Zoomy 4 programs still work
("old: fizzbuzz", 'for number from 1 to 5:\n    if number mod 3 is 0:\n        print "Fizz"\n    else:\n        print number', "", "1\n2\nFizz\n4\n5\n", 0),
("old: Structurally and Simply", 'Let a number be called y\nStructurally,\n    set y to 10 + 5 * 2\nprint y\nSimply,\n    set z to 3\n    print z', "", "20\n3\n", 0),
("old: comments", 'Let a number be called x\nset x to 5    (a note)\nprint x', "", "5\n", 0),
]

STATE = {"fails": 0}


def run(prog, flag):
    with tempfile.TemporaryDirectory() as t:
        src = os.path.join(t, "t.zmy")
        open(src, "w").write(prog + "\n")
        cmd = [sys.executable, os.path.join(ROOT, "zoomy.py"), src, "--run"] + ([flag] if flag else [])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=t)
        out = "".join(l for l in r.stdout.splitlines(True) if not l.startswith("[Success]"))
        return out, r.returncode, r.stderr


for name, prog, flag, want, code in CASES:
    out, rc, err = run(prog, flag)
    if want == E:
        ok = rc != 0 and code in (out + err) and "Traceback" not in err
    else:
        ok = out == want and rc == code and "Traceback" not in err
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        STATE["fails"] += 1
        print("   want", repr(want), code, "\n   got ", repr(out), rc, repr(err[:300]))
print(f"\n{STATE['fails']} failure(s)")
sys.exit(1 if STATE["fails"] else 0)
