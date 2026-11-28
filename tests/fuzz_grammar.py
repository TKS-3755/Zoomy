#!/usr/bin/env python3
"""Grammar fuzzing by rephrasing.

fuzz.py checks code generation.  This checks the *English*: a random program is written once in the plain statement style and
then again in many other ways Zoomy accepts (trailing `if` / `unless` / `while` / `until`, `when`, `whenever`, `provided that`,
`as long as`, one-line `if ... then ... otherwise ...`, `S twice` / `S 3 times`, statements joined with `;` `then` `, and`,
filler words, `And` / `Also` leading links, `Print x.` sentences, verb synonyms such as `show`, `increase x by 2`, `double x`,
number words such as `twenty one`, contractions such as `isn't`).  Every phrasing means the same thing, so the compiler must
produce *exactly the same Python* for all of them (apart from the line numbers).  A difference is a grammar bug.

    python3 tests/fuzz_grammar.py [programs] [seed]
"""
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import zoomy_py  # noqa: E402

WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen",
         "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
TENS = {2: "twenty", 3: "thirty", 4: "forty", 5: "fifty", 6: "sixty", 7: "seventy", 8: "eighty", 9: "ninety"}


def number_word(n):
    if n < 20:
        return WORDS[n]
    return TENS[n // 10] + ("" if n % 10 == 0 else " " + WORDS[n % 10])


def compile_text(text):
    """the generated Python, without the two lines that hold the file name and the line numbers"""
    prog = zoomy_py.Program("fuzz.zmy")
    prog.load_text(text, "fuzz.zmy")
    src, _ = zoomy_py.compile_python(prog)
    return "\n".join(l for l in src.splitlines() if not l.startswith(("_ZLINES", "_ZNAME")))


# ------------------------------------------------------------------------------------------------- the program model
class Simple:
    """one plain statement and the other ways to say the same thing"""
    def __init__(self, plain, alts=(), can_end_digit=True):
        self.plain, self.alts = plain, list(alts)


class Block:
    def __init__(self, kind, cond=None, body=(), other=(), count=None):
        self.kind, self.cond, self.body, self.other, self.count = kind, cond, list(body), list(other), count


VARS = ["x", "y", "z"]


def rnd_num(rng):
    return rng.choice([0, 1, 2, 3, 5, 7, 10, 12, 20, 21, 42, 99])


PRINT_VERBS = ["show", "display", "say", "output", "emit", "announce", "shout", "yell", "echo", "proclaim", "declare", "utter", "recite", "behold",
               "show me", "let me see", "print out", "report", "present", "pronounce", "lo and behold"]


def rnd_simple(rng):
    v, n = rng.choice(VARS), rnd_num(rng)
    k = rng.choice(["set", "add", "sub", "mul", "div", "print", "printv", "printlit", "double", "halve", "square"])
    num = [str(n), number_word(n)] + ({12: ["a dozen", "dozen"], 20: ["a score", "score"], 0: ["naught", "zilch", "nil", "nought"]}.get(n, []))
    if k == "set":
        a = [f"initialise {v} to {n}", f"initialize {v} to {n}", f"stash {n} in {v}", f"stick {n} into {v}", f"chuck {n} in {v}", f"{v} becomes {n}",
             f"{v} shall be {n}", f"{v} gets {n}", f"let {v} equal {n}", f"make {v} be {n}", f"assign {v} the value {n}", f"{v} is now {n}", f"{v} will become {n}",
             f"{v} shall become {n}", f"reset {v} to {n}"] + [f"set {v} to {w}" for w in num]
        return Simple(f"set {v} to {n}", rng.sample(a, 4))
    if k == "add":
        a = [f"{w} {v} by {n}" for w in ("increase", "bump", "increment", "augment", "raise")] + [f"tack {n} onto {v}", f"add {number_word(n)} to {v}", f"increase {v} by {number_word(n)}"]
        return Simple(f"add {n} to {v}", rng.sample(a, 4))
    if k == "sub":
        a = [f"{w} {v} by {n}" for w in ("decrease", "reduce", "lower", "diminish")] + [f"deduct {n} from {v}", f"knock {n} off {v}", f"shave {n} off {v}", f"take {n} off {v}",
                                                                                         f"take {n} from {v}", f"take {n} away from {v}", f"subtract {number_word(n)} from {v}"]
        return Simple(f"subtract {n} from {v}", rng.sample(a, 4))
    if k == "mul":
        return Simple(f"multiply {v} by {n}", [f"multiply {v} by {number_word(n)}", f"scale {v} by {n}"] + ([f"double {v}"] if n == 2 else []) + ([f"triple {v}"] if n == 3 else []))
    if k == "square":
        return Simple(f"multiply {v} by {v}", [f"square {v}"])
    if k == "div":
        m = max(n, 1)
        return Simple(f"divide {v} by {m}", ([f"halve {v}"] if m == 2 else []) + [f"divide {v} by {number_word(m)}"])
    if k == "double":
        return Simple(f"multiply {v} by 2", [f"double {v}"])
    if k == "halve":
        return Simple(f"divide {v} by 2", [f"halve {v}"])
    if k == "printv":
        return Simple(f"print {v}", [f"{w} {v}" for w in rng.sample(PRINT_VERBS, 5)])
    return Simple('print "hi"', [f'{w} "hi"' for w in rng.sample(PRINT_VERBS, 5)])


# (plain condition, its opposite, other ways to say the plain one)
CONDS = [("x is above 3", "x is at most 3", ["x exceeds 3", "x is greater than 3", "x is bigger than 3", "x is over 3", "x is more than 3"]),
         ("y is below 2", "y is at least 2", ["y falls short of 2", "y is smaller than 2", "y is under 2", "y is less than 2", "y is lower than 2"]),
         ("z is 4", "z is not 4", ["z equals 4", "z is exactly 4", "z is equal to 4", "z is the same as 4", "z is identical to 4"]),
         ("x is at least y", "x is below y", ["x has reached y", "x is no less than y", "x is not below y", "x is not less than y", "x is greater than or equal to y"]),
         ("y is 0", "y is not 0", ["y equals naught", "y is zilch", "y is nil", "y is zero"]),
         ("z is above x", "z is at most x", ["z exceeds x"]),
         ("x is at most 9", "x is above 9", ["x does not exceed 9", "x is no greater than 9", "x is not above 9", "x is less than or equal to 9", "x is not more than 9"]),
         ("z is not 4", "z is 4", ["z differs from 4", "z is unequal to 4", "z is not equal to 4", "z is not the same as 4"])]


def rnd_cond(rng):
    return rng.choice(CONDS)


def rnd_stmt(rng, depth):
    r = rng.random()
    if depth >= 2 or r < .45:
        return rnd_simple(rng)
    body = [rnd_stmt(rng, depth + 1) for _ in range(rng.randint(1, 2))]
    if r < .7:
        other = [rnd_stmt(rng, depth + 1)] if rng.random() < .4 else []
        return Block("if", rnd_cond(rng), body, other)
    if r < .8:
        return Block("unless", rnd_cond(rng), body)
    if r < .88:
        return Block("while", rnd_cond(rng), body)
    if r < .92:
        return Block("until", rnd_cond(rng), body)
    return Block("repeat", None, body, count=rng.randint(2, 21))


# ------------------------------------------------------------------------------------------------- plain rendering
def plain(st, depth=0):
    ind = "    " * depth
    if isinstance(st, Simple):
        return [ind + st.plain]
    if st.kind == "repeat":
        head = f"repeat {st.count} times:"
    else:
        head = f"{st.kind} {st.cond[0]}:"
    out = [ind + head]
    for s in st.body:
        out += plain(s, depth + 1)
    if st.other:
        out.append(ind + "otherwise:")
        for s in st.other:
            out += plain(s, depth + 1)
    return out


# ------------------------------------------------------------------------------------------------- rephrased rendering
LEADS = ["And ", "Also ", "Then ", "After that, ", "Also, "]
FILLERS = ["Please ", "First, ", "Finally, ", "Now ", "Just ", "Kindly ", "Hereby ", "Henceforth ", "Prithee, ", "Verily, ", "Go ahead and ", "I would like you to ",
           "Let's ", "We shall ", "You should ", "Alright, ", "Anyway, ", "So ", "Hey, ", "Time to ", "Pray ", "Basically, ", "Subsequently, ", "Furthermore, "]


class D(str):
    """a one-line sentence that may still get a leading link, a filler word, a capital letter and a full stop"""


def say_simple(rng, st):
    return rng.choice([st.plain] + st.alts)


def decorate(rng, line):
    ind = line[:len(line) - len(line.lstrip())]
    text = line.lstrip()
    r = rng.random()
    if r < .12:
        text = rng.choice(FILLERS) + text
    elif r < .22:
        text = rng.choice(LEADS) + text
    if rng.random() < .15 and text.split()[0] not in VARS:                 # 'X' would be another variable than 'x'
        text = text[0].upper() + text[1:]
    if rng.random() < .15 and not text[-1].isdigit():
        text += "."
    return ind + text


def contract(rng, cond):
    return cond.replace(" is not ", " isn't ") if rng.random() < .5 else cond


def is_simple(s):
    return isinstance(s, Simple)


def adverb(rng, st):
    """`S twice` / `S 3 times` for a one-line repeat"""
    return None


IF_WORDS = ["if", "when", "whenever", "provided that", "in case", "in the event that", "supposing that", "assuming", "given that", "anytime", "every time", "on condition that"]


ELSES = ["otherwise", "else", "or else", "failing that", "alternatively", "contrariwise"]


def rephrase(rng, st, depth=0):
    ind = "    " * depth
    if isinstance(st, Simple):
        return [D(ind + say_simple(rng, st))]
    one = len(st.body) == 1 and is_simple(st.body[0])
    if st.kind == "repeat":
        if one and rng.random() < .45:
            core = rng.choice([st.body[0].plain] + st.body[0].alts)
            if st.count == 2 and rng.random() < .5:
                return [D(ind + core + " twice")]
            ends_in_word = core.split()[-1] in WORDS or core.split()[-1] in TENS.values() or core.split()[-1] in ("naught", "nought", "nil", "zilch", "nada", "dozen", "score")     # 'by twelve twenty one times' is ambiguous English
            return [D(ind + core + f" {st.count if ends_in_word else rng.choice([st.count, number_word(st.count)])} times")]
        n = rng.choice([st.count, number_word(st.count)])
        out = [ind + rng.choice([f"repeat {n} times:", f"loop {n} times:", f"iterate {n} times:", f"do this {n} times:", f"go around {n} times:"])]
        for s in st.body:
            out += rephrase(rng, s, depth + 1)
        return out
    cond = contract(rng, rng.choice([st.cond[0]] + st.cond[2]))
    kw = {"if": rng.choice(IF_WORDS), "unless": "unless", "while": rng.choice(["while", "as long as", "so long as", "whilst", "for as long as"]),
          "until": rng.choice(["until", "until such time as"])}[st.kind]
    if st.kind == "if" and rng.random() < .15:
        kw = "only if"
    other_one = len(st.other) == 1 and is_simple(st.other[0])
    # a one-line form
    if one and (not st.other or other_one) and rng.random() < .5:
        core = say_simple(rng, st.body[0])
        if st.kind == "if" and kw != "only if":
            if st.other:
                e = say_simple(rng, st.other[0])
                form = rng.choice(["trail", "then", "comma"])
                if form == "trail":
                    return [D(ind + f"{core} {kw} {cond}, {rng.choice(ELSES)} {e}")]
                if form == "then":
                    return [D(ind + f"{kw} {cond} then {core} {rng.choice(ELSES)} {e}")]
                return [D(ind + f"{kw} {cond}, {core}, {rng.choice(ELSES)} {e}")]
            form = rng.choice(["trail", "then", "comma"])
            return [D(ind + {"trail": f"{core} {kw} {cond}", "then": f"{kw} {cond} then {core}", "comma": f"{kw} {cond}, {core}"}[form])]
        if not st.other:
            return [D(ind + f"{core} {kw} {cond}")]
    if st.kind == "while" and rng.random() < .15:
        kw = "keep going while"
    out = [ind + f"{kw} {cond}:"]
    for s in st.body:
        out += rephrase(rng, s, depth + 1)
    if st.other:
        out.append(ind + rng.choice(["otherwise:", "else:", "or else:", "failing that:", "alternatively:", "contrariwise:", "in any other case:"]))
        for s in st.other:
            out += rephrase(rng, s, depth + 1)
    return out


def join_simple_lines(rng, lines_sts):
    """join a run of adjacent one-line simple statements with ';' / 'then' / ', then' / ', and'"""
    return None


def program(rng):
    stmts = [rnd_stmt(rng, 0) for _ in range(rng.randint(1, 4))]
    head = ["Let a number be called x", "Let a number be called y", "Let a number be called z", "set x to 1", "set y to 2", "set z to 3"]
    ref = head + [l for s in stmts for l in plain(s)]
    var = list(head)
    i = 0
    while i < len(stmts):
        s = stmts[i]
        # a run of simple statements -> maybe one joined line
        if is_simple(s) and i + 1 < len(stmts) and is_simple(stmts[i + 1]) and rng.random() < .4:
            sep = rng.choice(["; ", " then ", ", then ", ", and ", ", and then ", " and then ", ", so ", " after that "])
            second = say_simple(rng, stmts[i + 1])
            if second.split()[0] in VARS and "and" in sep.split() and "then" not in sep:
                sep = "; "                                                   # ', and x becomes 5' does not say where the second sentence starts
            var.append(D(say_simple(rng, s) + sep + second))
            i += 2
            continue
        var += rephrase(rng, s)
        i += 1
    var = [decorate(rng, l) if isinstance(l, D) else l for l in var]
    return "\n".join(ref) + "\n", "\n".join(var) + "\n"


def main(argv):
    n = int(argv[0]) if argv else 300
    seed = int(argv[1]) if len(argv) > 1 else 1
    rng = random.Random(seed)
    fails = 0
    for k in range(n):
        ref, var = program(rng)
        try:
            want = compile_text(ref)
        except Exception as ex:
            print(f"BAD GENERATOR (the plain program does not compile): {ex}\n{ref}")
            fails += 1
            continue
        try:
            got = compile_text(var)
        except Exception as ex:
            fails += 1
            if fails <= 8:
                print(f"--- #{k}: the rephrased program is rejected: {type(ex).__name__}: {str(ex)[:160]}\n{var}--- plain:\n{ref}")
            continue
        if got != want:
            fails += 1
            if fails <= 8:
                import difflib
                d = [l for l in difflib.unified_diff(want.splitlines(), got.splitlines(), "plain", "rephrased", lineterm="", n=0)][:12]
                print(f"--- #{k}: different code\n{var}--- plain:\n{ref}" + "\n".join(d))
    print(f"{fails} failure(s) in {n} programs")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
