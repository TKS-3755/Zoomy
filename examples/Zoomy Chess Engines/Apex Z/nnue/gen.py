#!/usr/bin/env python3
"""self-play data: gen.py ENGINE DEPTH SECONDS SEED OUT   -> lines  fen|score_cp_white|result_white (1, 0.5, 0)"""
import subprocess, sys, random, time, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cm
eng, depth, secs, seed, out = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
rnd = random.Random(seed)
p = subprocess.Popen([eng], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1, cwd=os.path.dirname(os.path.abspath(eng)))
def send(s): p.stdin.write(s + "\n"); p.stdin.flush()
def wait(tok):
    while p.stdout.readline().strip() != tok: pass
send("uci"); wait("uciok")
send("setoption name Threads value 1\nsetoption name OwnBook value false\nsetoption name Hash value 16\nisready"); wait("readyok")
def search(fen):
    send(f"position fen {fen}\ngo depth {depth}")
    sc = None
    while True:
        l = p.stdout.readline()
        if not l: raise SystemExit("engine died")
        if l.startswith("info") and " score " in l:
            t = l.split(); i = t.index("score"); sc = (t[i+1], int(t[i+2]))
        if l.startswith("bestmove"): return l.split()[1], sc
t0 = time.time(); games = 0; npos = 0
f = open(out, "a")
while time.time() - t0 < secs:
    b = cm.Board(); recs = []; res = None; adj = 0
    send("ucinewgame"); send("isready"); wait("readyok")
    for _ in range(rnd.choice([6, 7, 8, 9, 10])):
        ms = b.legal()
        if not ms: break
        b.push(rnd.choice(ms))
    if not b.legal(): continue
    ply = 0
    while True:
        ms = b.legal()
        if not ms:
            res = (0.0 if b.white else 1.0) if b.in_check() else 0.5
            break
        if b.half >= 100 or b.insufficient() or b.rep(): res = 0.5; break
        if ply > 220: res = 0.5; break
        fen = b.fen()
        mv, sc = search(fen)
        if mv == "0000" or sc is None: res = 0.5; break
        sgn = 1 if b.white else -1
        wsc = sc[1] * sgn if sc[0] == "cp" else (30000 if sc[1] * sgn > 0 else -30000)
        if sc[0] == "cp" and abs(sc[1]) > 1500 or sc[0] == "mate": adj += 1
        else: adj = 0
        if adj >= 4:
            res = 1.0 if wsc > 0 else 0.0; break
        quiet = not b.in_check() and sc[0] == "cp"
        u = mv
        tgt = [m for m in ms if b.uci(m) == mv]
        if not tgt: res = 0.5; break
        iscap = b.b[tgt[0][1]] is not None or (b.b[tgt[0][0]] in "Pp" and (tgt[0][1] & 7) != (tgt[0][0] & 7))
        if quiet and not iscap and abs(wsc) < 3000: recs.append((fen, wsc))
        if ply < 16 and rnd.random() < 0.08:
            b.push(rnd.choice(ms))
        else:
            b.push(tgt[0])
        ply += 1
    games += 1
    for fen, s in recs:
        f.write(f"{fen}|{s}|{res}\n"); npos += 1
    f.flush()
send("quit")
print(f"{games} games, {npos} positions in {time.time()-t0:.0f}s")
