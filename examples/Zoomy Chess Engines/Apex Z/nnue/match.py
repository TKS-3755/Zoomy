#!/usr/bin/env python3
"""A/B match over UCI.  match.py GAMES MOVETIME_MS "pathA|opt=val;opt=val" "pathB|opt=val" [seed] [parallel]
Openings: random 8-ply lines (each used twice, colours swapped).  Prints a score for A and an Elo estimate with its 95 % error."""
import subprocess, sys, os, random, math, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cm
games, mt = int(sys.argv[1]), int(sys.argv[2])
specA, specB = sys.argv[3], sys.argv[4]
seed = int(sys.argv[5]) if len(sys.argv) > 5 else 1
par = int(sys.argv[6]) if len(sys.argv) > 6 else 2
def start(spec):
    path, _, opts = spec.partition("|")
    p = subprocess.Popen([path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1, cwd=os.path.dirname(os.path.abspath(path)))
    def send(s): p.stdin.write(s + "\n"); p.stdin.flush()
    send("uci")
    while p.stdout.readline().strip() != "uciok": pass
    send("setoption name Threads value 1\nsetoption name OwnBook value false\nsetoption name Hash value 32")
    for o in filter(None, opts.split(";")):
        k, _, v = o.partition("="); send(f"setoption name {k} value {v}")
    send("isready")
    while p.stdout.readline().strip() != "readyok": pass
    p.send = send
    return p
def go(p, fen):
    p.send(f"position fen {fen}\ngo movetime {mt}")
    sc = None
    while True:
        l = p.stdout.readline()
        if not l: return None, None
        if l.startswith("info") and " score " in l:
            t = l.split(); i = t.index("score"); sc = (t[i + 1], int(t[i + 2]))
        if l.startswith("bestmove"): return l.split()[1], sc
def opening(k):
    r = random.Random(seed * 1000 + k)
    while True:
        b = cm.Board()
        for _ in range(8):
            ms = b.legal()
            if not ms: break
            b.push(r.choice(ms))
        else:
            if b.legal() and not b.in_check(): return b.fen()
def play(k):
    a_white = k % 2 == 0
    fen = opening(k // 2)
    A, B = start(specA), start(specB)
    b = cm.Board(fen); adj = 0; res = None
    w, bl = (A, B) if a_white else (B, A)
    for ply in range(400):
        ms = b.legal()
        if not ms:
            res = ("mate", not b.white) if b.in_check() else ("draw", None); break
        if b.half >= 100 or b.insufficient() or b.rep(): res = ("draw", None); break
        p = w if b.white else bl
        mv, sc = go(p, b.fen())
        if mv is None: res = ("crash", None); break
        if sc and (sc[0] == "mate" or abs(sc[1]) > 1000): adj += 1
        else: adj = 0
        if adj >= 6 and sc:
            win = b.white if (sc[1] > 0) else (not b.white)
            res = ("adj", win); break
        if ply > 300: res = ("draw", None); break
        try: b.push_uci(mv)
        except ValueError: res = ("illegal", not b.white); break
    for p in (A, B):
        try: p.send("quit"); p.wait(timeout=5)
        except Exception: p.kill()
    kind, white_won = res
    if white_won is None: return k, 0.5, kind
    a_won = (white_won == a_white)
    return k, (1.0 if a_won else 0.0), kind
t0 = time.time()
sa = 0.0; W = D = L = 0
with ThreadPoolExecutor(par) as ex:
    for k, r, kind in ex.map(play, range(games)):
        sa += r; W += r == 1; D += r == 0.5; L += r == 0
        print(f"game {k}: A {'won' if r == 1 else 'lost' if r == 0 else 'drew'} ({kind})   running {sa}/{k+1 if False else W+D+L}", flush=True)
n = W + D + L
p = sa / n
elo = -400 * math.log10(1 / max(p, 1e-9) - 1) if 0 < p < 1 else (999 if p >= 1 else -999)
var = (W * (1 - p) ** 2 + D * (0.5 - p) ** 2 + L * p ** 2) / n
err = 1.96 * math.sqrt(var / n) / (p * (1 - p) * math.log(10) / 400) if 0 < p < 1 else 0
print(f"RESULT A {W}-{D}-{L} of {n}  score {p:.3f}  Elo {elo:+.0f} +- {err:.0f}   ({time.time()-t0:.0f}s)")
