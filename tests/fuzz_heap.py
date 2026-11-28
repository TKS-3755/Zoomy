"""random programs with text, lists and tables, built natively and by the Python backend; they must agree.
usage: python3 tests/fuzz_heap.py [programs] [seed]"""
import os, random, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Z = [sys.executable, os.path.join(HERE, "zoomy.py")]
WORDS = ["", "a", "bb", "hello", "World", "x y", "  pad  ", "apple", "Banana", "cat dog", "zebra", "q1", "a,b,c", "one two three", "MiXeD"]
NUMS = ["0", "1", "2", "3", "7", "10", "42", "0.5", "1.25", "100", "0.1", "999999", "123456.789", "1000000", "0.000001", "2.5e-7", "3", "5"]


class Gen:
    def __init__(self, rnd):
        self.r = rnd
        self.lines = []
        self.ind = 0

    def say(self, t):
        self.lines.append("    " * self.ind + t)

    def snum(self):
        return self.r.choice(NUMS)

    def sstr(self):
        return '"' + self.r.choice(WORDS) + '"'

    def nexpr(self, d=0):
        r = self.r
        k = r.randrange(9 if d < 2 else 3)
        if k == 0: return self.snum()
        if k == 1: return r.choice(["n0", "n1", "n2"])
        if k == 2: return "length of " + r.choice(["s0", "s1", "s2", "l0", "l1", "m0"])
        if k == 3: return "(%s + %s)" % (self.nexpr(d + 1), self.nexpr(d + 1))
        if k == 4: return "(%s - %s)" % (self.nexpr(d + 1), self.nexpr(d + 1))
        if k == 5: return "(%s * %s)" % (self.nexpr(d + 1), self.nexpr(d + 1))
        if k == 6: return "sum of " + r.choice(["l0", "l1"])
        if k == 7: return "(" + self.nexpr(d + 1) + " mod 7)"
        return "count of " + self.sstr() + " in " + r.choice(["s0", "s1", "s2"])

    def sexpr(self, d=0):
        r = self.r
        k = r.randrange(10 if d < 2 else 3)
        if k == 0: return self.sstr()
        if k == 1: return r.choice(["s0", "s1", "s2"])
        if k == 2: return r.choice(["s0", "s1", "s2"])
        if k == 3: return "(%s + %s)" % (self.sexpr(d + 1), self.sexpr(d + 1))
        if k == 4: return "uppercase of " + self.sexpr(d + 1)
        if k == 5: return "lowercase of " + self.sexpr(d + 1)
        if k == 6: return "trim of " + self.sexpr(d + 1)
        if k == 7: return "reversed of " + self.sexpr(d + 1)
        if k == 8: return 'replace "a" with "oo" in ' + self.sexpr(d + 1)
        return '"{%s} and {%s}"' % (self.nexpr(2), self.sexpr(2))

    def cond(self):
        r = self.r
        k = r.randrange(7)
        if k == 0: return "%s is above %s" % (self.nexpr(1), self.nexpr(1))
        if k == 1: return "%s is %s" % (self.nexpr(1), self.nexpr(1))
        if k == 2: return "%s is below %s" % (self.sexpr(1), self.sexpr(1))
        if k == 3: return "%s is %s" % (self.sexpr(1), self.sexpr(1))
        if k == 4: return "%s contains %s" % (r.choice(["s0", "s1", "s2"]), self.sstr())
        if k == 5: return "l0 contains %s" % self.snum()
        return "t0 contains %s" % self.sstr()

    def stmt(self, d=0):
        r = self.r
        k = r.randrange(26 if d < 2 else 18)
        if k == 0: self.say("set %s to %s" % (r.choice(["s0", "s1", "s2"]), self.sexpr()))
        elif k == 1: self.say("set %s to %s" % (r.choice(["n0", "n1", "n2"]), self.nexpr()))
        elif k == 2: self.say("append %s to %s" % (self.snum(), r.choice(["l0", "l1"])))
        elif k == 3: self.say("append %s to m0" % self.sexpr())
        elif k == 4:
            self.say("if length of l0 is above 0:"); self.say("    remove item at 0 from l0")
        elif k == 5: self.say("sort %s%s" % (r.choice(["l0", "l1", "m0"]), r.choice(["", " descending"])))
        elif k == 6: self.say("reverse " + r.choice(["l0", "l1", "m0"]))
        elif k == 7: self.say("put %s in t0 at %s" % (self.nexpr(), self.sexpr()))
        elif k == 8:
            key = self.sexpr(2)
            self.say("if t0 contains %s:" % key); self.say("    add %s to t0 at %s" % (self.snum(), key))
        elif k == 9: self.say("print " + self.sexpr())
        elif k == 10: self.say("print " + self.nexpr())
        elif k == 11: self.say("print " + r.choice(["l0", "l1", "m0", "t0"]))
        elif k == 12: self.say('print "n0=", n0, " s0=", s0, " len=", length of l0')
        elif k == 13: self.say("insert %s into l1 at 0" % self.snum())
        elif k == 14: self.say("print sorted of " + r.choice(["l0", "l1", "m0"]))
        elif k == 15: self.say("print join m0 with %s" % self.sstr())
        elif k == 16: self.say("print split %s by %s" % (self.sexpr(2), r.choice(['" "', '","', '"a"', '""'])))
        elif k == 17: self.say("print keys of t0")
        elif k == 18:
            self.say("if %s:" % self.cond()); self.ind += 1
            for _ in range(r.randrange(1, 3)): self.stmt(d + 1)
            self.ind -= 1
            if r.random() < .5:
                self.say("else:"); self.ind += 1
                self.stmt(d + 1); self.ind -= 1
        elif k == 19:
            self.say("for each x in %s:" % r.choice(["l0", "l1"])); self.ind += 1
            self.say("print x * 2")
            if r.random() < .5: self.say("add x to n0")
            self.ind -= 1
        elif k == 20:
            self.say("for each w in m0:"); self.ind += 1
            self.say("print uppercase of w")
            self.ind -= 1
        elif k == 21:
            self.say("for each w in keys of t0:"); self.ind += 1
            self.say('print w, "=", t0 at w')
            self.ind -= 1
        elif k == 22:
            v = "j%d" % d
            self.say("set %s to 0" % v); self.say("while %s is below %d:" % (v, r.randrange(1, 4))); self.ind += 1
            self.stmt(d + 1); self.say("add 1 to %s" % v); self.ind -= 1
        elif k == 23:
            self.say("for i from 0 to %d:" % r.randrange(0, 3)); self.ind += 1
            self.say("append i to l1"); self.stmt(d + 1); self.ind -= 1
        elif k == 24: self.say("print the first of l0")      # an empty list is an error in both
        else: self.say("print l1 at %d" % r.randrange(0, 4))

    def program(self):
        L = ["Let a string be called s0", "Let a string be called s1", "Let a string be called s2",
             "Let a number be called n0", "Let a number be called n1", "Let a number be called n2", "Let a number be called i", "Let a number be called j0", "Let a number be called j1", "Let a number be called j2",
             "Let a value be called x", "Let a value be called w",
             "Create an array of numbers named l0", "Create an array of numbers named l1", "Create an array of strings named m0",
             "Let a table be called t0",
             "set s0 to " + self.sstr(), "set s1 to " + self.sstr(), "set s2 to " + self.sstr(),
             "set n0 to " + self.snum(), "set n1 to " + self.snum(), "set n2 to " + self.snum(),
             "set l0 to [3, 1, 2]", "set l1 to empty list", 'set m0 to ["pear", "fig"]', 'set t0 to table with "k" as 1']
        self.lines = []
        for _ in range(self.r.randrange(8, 26)):
            self.stmt()
        return "\n".join(L + self.lines) + "\n"


def run(seed, n):
    rnd = random.Random(seed)
    bad = 0
    with tempfile.TemporaryDirectory() as d:
        for k in range(n):
            text = Gen(rnd).program()
            p = os.path.join(d, "f.zmy")
            open(p, "w").write(text)
            try:
                ref = subprocess.run(Z + [p, "--python", "--run"], capture_output=True, cwd=d, env={**os.environ, "ZOOMY_NO_HEAP": "1"}, timeout=20)
            except subprocess.TimeoutExpired:
                continue                                           # the random program never ends
            if b"[Error]" in ref.stdout[:200] and b"ELF" not in ref.stdout:      # the generator made something the front end refuses
                continue
            b = subprocess.run(Z + [p, "--native", "-o", os.path.join(d, "f")], capture_output=True, text=True, cwd=d, timeout=60)
            if "[Success]" not in b.stdout:
                print("NOT NATIVE", seed, k, b.stdout.strip()[-300:]); bad += 1
                open(os.path.join(HERE, "fuzz_heap_fail_%d_%d.zmy" % (seed, k)), "w").write(text); continue
            out = subprocess.run([os.path.join(d, "f")], capture_output=True, cwd=d, timeout=60)
            want = b"\n".join(l for l in ref.stdout.split(b"\n") if not l.startswith(b"[Success]"))
            if out.stdout != want or out.returncode != ref.returncode:
                print("DIFF", seed, k, "rc", out.returncode, ref.returncode)
                open(os.path.join(HERE, "fuzz_heap_fail_%d_%d.zmy" % (seed, k)), "w").write(text); bad += 1
    return bad


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    bad = run(seed, n)
    print(f"{bad} failure(s)")
    sys.exit(1 if bad else 0)
