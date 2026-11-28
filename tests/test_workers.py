#!/usr/bin/env python3
"""Zoomy 5.5: shared arrays + workers (native), compared with the single-worker Python backend."""
import os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Z = os.path.join(ROOT, "zoomy.py")

CASES = {
    # every worker writes its own slot; the parent adds them up
    "sum_ints": ("from now on, use integers instead of floats\nLet a number be called id\nLet a number be called total\n"
                 "Create a shared array named res with 8 slots\nstart 4 workers and store my worker number in id\n"
                 "set item (id plus 1) of res to (id plus 1) times 100\nif id is greater than 0:\n    finish\n"
                 "wait for the workers\nfor each v in res:\n    add v to total\nprint total\n", "1000\n", "100\n"),
    "sum_floats": ("Let a number be called id\nLet a number be called total\nCreate a shared array named res with 8 slots\n"
                   "start 3 workers and store my worker number in id\nset item (id plus 1) of res to id plus 0.5\n"
                   "if id is greater than 0:\n    finish\nwait for the workers\nfor each v in res:\n    add v to total\nprint total\n",
                   "4.5\n", "0.5\n"),
    # workers share a counter slot they only read, and they see what the parent wrote before the fork
    "parent_data": ("Let a number be called id\nCreate a shared array named box with 4 slots\nset item 1 of box to 42\n"
                    "start 2 workers and store my worker number in id\nif id is greater than 0:\n"
                    "    set item (id plus 1) of box to (item 1 of box) plus id\n    finish\nwait for the workers\n"
                    "print item 2 of box\n", "43\n", "0\n"),
    # private variables stay private
    "private_vars": ("Let a number be called id\nLet a number be called mine\nCreate a shared array named out with 4 slots\n"
                     "set mine to 10\nstart 3 workers and store my worker number in id\nadd id to mine\n"
                     "set item (id plus 1) of out to mine\nif id is greater than 0:\n    finish\nwait for the workers\n"
                     "print item 1 of out\nprint item 2 of out\nprint item 3 of out\nprint mine\n", "10\n11\n12\n10\n", "10\n0\n0\n10\n"),
    # more workers than slots needed; 0 or 100 workers are clamped to 1..1024
    "clamp": ("Let a number be called id\nCreate a shared array named seen with 1100 slots\n"
              "start 2000 workers and store my worker number in id\nset item (id plus 1) of seen to 1\n"
              "if id is greater than 0:\n    finish\nwait for the workers\nLet a number be called t\nfor each v in seen:\n"
              "    add v to t\nprint t\n", "1024\n", "1\n"),
}


def main():
    fails = 0
    with tempfile.TemporaryDirectory() as tmp:
        for name, (text, want_native, want_py) in CASES.items():
            src = os.path.join(tmp, name + ".zmy")
            exe = os.path.join(tmp, name)
            open(src, "w").write(text)
            r = subprocess.run([sys.executable, Z, "--native", src, "-o", exe], capture_output=True, text=True)
            if r.returncode:
                print("FAIL compile", name, r.stdout[-300:]); fails += 1; continue
            for rep in range(5):                                  # races would show up as a changing answer
                out = subprocess.run([exe], capture_output=True, text=True, timeout=30).stdout
                if out != want_native:
                    print("FAIL native", name, repr(out), "wanted", repr(want_native)); fails += 1; break
            out = subprocess.run([sys.executable, Z, "--python", "--run", src], capture_output=True, text=True, timeout=60).stdout
            if out != want_py:
                print("FAIL python", name, repr(out), "wanted", repr(want_py)); fails += 1
    print(f"{fails} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
