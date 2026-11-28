#!/usr/bin/env python3
"""Run every Zoomy check, in parallel.

    python3 tests/run.py            the full suite (what a release needs)
    python3 tests/run.py --quick    the everyday tier: the same checks with smaller random samples (about a quarter of the time)
    python3 tests/run.py -k wasm    only the checks whose name contains 'wasm'
    python3 tests/run.py -j 4       use 4 processes (default: one per CPU)
    python3 tests/run.py --list     show the checks and which tier each one is in

`sh tests/run_all.sh` still works and runs this.  Each check is its own process, so one failing check never hides another;
a failing check prints its output at the end.  The exit code is 0 only when everything passed."""
import concurrent.futures as cf
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

# (name, command, what the last line of output must match, extra environment, quick-tier command or None to skip, or "same")
ZERO = r"^0 failure"
SAME = "same"
CHECKS = [
    ("fuzz native/gcc/python", ["-I", "tests/fuzz.py", "400", "--gcc", "40", "--py", "300"], r" 0 failures", {}, ["-I", "tests/fuzz.py", "60", "--gcc", "0", "--py", "40"]),
    ("fuzz wasm", ["-I", "tests/fuzz.py", "40", "--wasm", "40"], r" 0 failures", {}, ["-I", "tests/fuzz.py", "8", "--wasm", "8"]),
    ("grammar fuzz", ["tests/fuzz_grammar.py", "3000"], ZERO, {}, ["tests/fuzz_grammar.py", "300"]),
    ("native text, lists, tables", ["tests/test_heap.py"], ZERO, {}, SAME),
    ("garbage collector", ["tests/test_gc.py"], ZERO, {}, SAME),
    ("fuzz text, lists, tables", ["tests/fuzz_heap.py", "120", "7"], ZERO, {}, ["tests/fuzz_heap.py", "20", "7"]),
    ("voices", ["tests/test_voices.py"], ZERO, {}, SAME),
    ("fmt", ["tests/test_fmt.py"], ZERO, {}, SAME),
    ("suggestions", ["tests/test_suggest.py"], ZERO, {}, SAME),
    ("language server", ["tests/test_lsp.py"], ZERO, {}, SAME),
    ("vscode client", ["tests/test_vscode.py"], ZERO, {}, SAME),
    ("modules", ["tests/test_modules.py"], ZERO, {}, SAME),
    ("playground", ["tests/test_playground.py"], ZERO, {}, SAME),
    ("explain and trace", ["tests/test_explain.py"], ZERO, {}, SAME),
    ("numeric", ["-I", "tests/test_numeric.py"], ZERO, {}, SAME),
    ("nocalc native", ["tests/test_nocalc.py"], ZERO, {}, SAME),
    ("nocalc python", ["tests/test_nocalc.py"], ZERO, {"ZOOMY_BACKEND": "python"}, None),
    ("language", ["tests/test_language.py"], ZERO, {}, SAME),
    ("zoomy5 grammar", ["tests/test_zoomy5.py"], ZERO, {}, SAME),
    ("native-only", ["tests/test_native.py"], ZERO, {}, SAME),
    ("ints", ["tests/test_ints.py"], ZERO, {}, ["tests/test_ints.py", "20"]),
    ("ints unsigned", ["tests/test_ints.py", "100", "unsigned"], ZERO, {}, ["tests/test_ints.py", "20", "unsigned"]),
    ("codegen", ["tests/test_codegen.py", "60"], ZERO, {}, ["tests/test_codegen.py", "15"]),
    ("codegen unsigned", ["tests/test_codegen.py", "40", "unsigned"], ZERO, {}, ["tests/test_codegen.py", "10", "unsigned"]),
    ("workers", ["tests/test_workers.py"], ZERO, {}, SAME),
    ("io55", ["tests/test_io55.py"], ZERO, {}, SAME),
    ("examples", ["tests/test_examples.py"], ZERO, {}, SAME),
    ("wording", ["tests/test_wording.py"], ZERO, {}, SAME),
    ("leading And/Also/Then", ["tests/test_leading.py"], ZERO, {}, SAME),
    ("constants", ["tests/test_constants.py"], ZERO, {}, SAME),
    ("big numbers", ["tests/test_big.py"], ZERO, {}, SAME),
    ("big numbers backends", ["tests/test_big_backends.py"], ZERO, {"BIG_RANDOM": "40"}, None),
    ("wasm", ["tests/test_wasm.py", "12"], ZERO, {}, ["tests/test_wasm.py", "4"]),
    ("big decimals", ["tests/test_bigdec.py"], ZERO, {}, None),
    ("big decimal math (sin cos tan atan ln exp)", ["tests/test_bdmath.py"], ZERO, {}, None),
    ("APEX-Z 7 NNUE (exact integer evaluation, incremental updates)", ["tests/test_apexz_nnue.py"], ZERO, {}, None),
    ("APEX-Z NNUE v2 (king buckets, pairwise, output buckets; exact integer evaluation)", ["tests/test_apexz_nnue2.py"], ZERO, {}, None),
    ("vector", ["tests/test_vector.py"], r"ok", {}, SAME),
    ("sys", ["tests/test_sys.py"], r"ALL OK", {}, SAME),
    ("optimizer", ["tests/test_opt.py"], r" 0 differences", {}, SAME),
    ("optimizer regs", ["tests/test_ints.py", "60"], ZERO, {"ZOOMY_REGS": "1"}, None),
]
EXTRA = ("migration tool", "runtime image")           # checks that are code here, not commands


def migration_check():
    d = tempfile.mkdtemp()
    try:
        old = os.path.join(d, "old.zmy")
        open(old, "w").write("set total to 0\nset i to 1\nwhile i is at most 3:\n    add i to total\n    add 1 to i\nprint total\n")
        new, exe = os.path.join(d, "new.zmy"), os.path.join(d, "exe")
        r = subprocess.run([PY, "tools/migrate.py", old, "-o", new], cwd=ROOT, capture_output=True, text=True)
        if "Let a number be called total" not in open(new).read():
            return False, "the migrated program lacks its declaration\n" + r.stdout + r.stderr
        r = subprocess.run([PY, "zoomy.py", new, "--native", "-o", exe], cwd=ROOT, capture_output=True, text=True)
        out = subprocess.run([exe], capture_output=True, text=True).stdout if r.returncode == 0 else r.stdout + r.stderr
        return out.strip() == "6", out
    finally:
        shutil.rmtree(d, ignore_errors=True)


def run_check(name, args, pattern, env, timeout):
    t0 = time.time()
    e = dict(os.environ)
    e.update(env)
    try:
        r = subprocess.run([PY] + args, cwd=ROOT, env=e, capture_output=True, text=True, timeout=timeout)
        out = (r.stdout + r.stderr).rstrip()
        last = r.stdout.rstrip().splitlines()[-1] if r.stdout.strip() else ""
        ok = re.search(pattern, last) is not None
    except subprocess.TimeoutExpired as ex:
        out, ok = f"timed out after {timeout} s\n" + str(ex.stdout or "")[-2000:], False
    return name, ok, time.time() - t0, out


def run_function(name, fn):
    t0 = time.time()
    ok, out = fn()
    return name, ok, time.time() - t0, out


def main(argv):
    quick = "--quick" in argv
    jobs = os.cpu_count() or 2
    pick = None
    listing = "--list" in argv
    if "-j" in argv:
        jobs = int(argv[argv.index("-j") + 1])
    if "-k" in argv:
        pick = argv[argv.index("-k") + 1].lower()
    todo = []
    for name, args, pat, env, q in CHECKS:
        if quick:
            if q is None:
                continue
            if q != SAME:
                args = q
        if pick and pick not in name.lower():
            continue
        todo.append((name, args, pat, env))
    if listing:
        for name, args, pat, env, q in CHECKS:
            print(f"{name:26s} {'quick+full' if q is not None else 'full only'}")
        return 0
    # longest first keeps all the processes busy to the end
    weight = {"fuzz native/gcc/python": 9, "big decimals": 8, "wasm": 7, "examples": 7, "big numbers backends": 6, "codegen": 5, "ints": 5,
              "ints unsigned": 5, "numeric": 4, "optimizer": 4, "fuzz wasm": 4, "nocalc native": 3, "nocalc python": 3, "codegen unsigned": 3, "language": 3}
    todo.sort(key=lambda c: -weight.get(c[0], 1))
    extras = [] if pick else [("migration tool", migration_check)]
    if not pick and shutil.which("nasm"):
        extras.append(("runtime image", lambda: (lambda r: (r.returncode == 0, r.stdout + r.stderr))(
            subprocess.run([PY, "tools/build_runtime.py", "--check"], cwd=ROOT, capture_output=True, text=True))))
    t0 = time.time()
    failed, total, done = [], 0, 0
    print(f"{'quick' if quick else 'full'} suite: {len(todo) + len(extras)} checks on {jobs} process(es)", flush=True)
    with cf.ThreadPoolExecutor(max_workers=jobs) as pool:
        futs = [pool.submit(run_check, n, a, p, e, 1800) for n, a, p, e in todo] + [pool.submit(run_function, n, f) for n, f in extras]
        for f in cf.as_completed(futs):
            name, ok, secs, out = f.result()
            total += 1
            print(f"{'ok  ' if ok else 'FAIL'} {secs:6.1f}s  {name}", flush=True)
            if not ok:
                failed.append((name, out))
    for name, out in failed:
        print(f"\n---- {name} ----\n" + "\n".join(out.splitlines()[-40:]))
    print(f"\n{total - len(failed)}/{total} passed in {time.time() - t0:.0f} s")
    print("ALL OK" if not failed else f"{len(failed)} FAILED: " + ", ".join(n for n, _ in failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
