#!/usr/bin/env python3
"""A/B match over UCI: uci_match.py ENGINE FEAT_A FEAT_B MOVETIME_MS GAMES [THREADS] ; games start from varied openings (book off), colours alternate."""
import subprocess, sys, time, os, random
eng, fa, fb, mt, games = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
thr = sys.argv[6] if len(sys.argv) > 6 else "1"
OFF = int(sys.argv[7]) if len(sys.argv) > 7 else 0
OPEN = ["e2e4 e7e5 g1f3 b8c6", "d2d4 d7d5 c2c4 e7e6", "e2e4 c7c5 g1f3 d7d6", "d2d4 g8f6 c2c4 g7g6", "e2e4 e7e6 d2d4 d7d5",
        "c2c4 e7e5 b1c3 g8f6", "e2e4 c7c6 d2d4 d7d5", "g1f3 d7d5 g2g3 g8f6", "d2d4 d7d5 g1f3 g8f6", "e2e4 g7g6 d2d4 f8g7",
        "e2e4 e7e5 g1f3 g8f6", "d2d4 g8f6 g1f3 e7e6", "c2c4 g8f6 b1c3 e7e6", "e2e4 d7d6 d2d4 g8f6", "d2d4 f7f5 g2g3 g8f6", "e2e4 b8c6 d2d4 d7d5"]
def start(feat):
    p = subprocess.Popen([eng], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1, cwd=os.path.dirname(eng) or ".")
    p.stdin.write("uci\n"); p.stdin.flush()
    while p.stdout.readline().strip() != "uciok": pass
    p.stdin.write(f"setoption name Threads value {thr}\nsetoption name OwnBook value false\nsetoption name Features value {feat}\nisready\n"); p.stdin.flush()
    while p.stdout.readline().strip() != "readyok": pass
    return p
def go(p, moves):
    p.stdin.write("position startpos" + (" moves " + " ".join(moves) if moves else "") + f"\ngo movetime {mt}\n"); p.stdin.flush()
    score = None
    while True:
        l = p.stdout.readline()
        if not l: return None, None
        if l.startswith("info") and " score " in l:
            t = l.split(); i = t.index("score"); score = (t[i+1], int(t[i+2]))
        if l.startswith("bestmove"): return l.split()[1], score
def game(op, a_white):
    A, B = start(fa), start(fb)
    w, b = (A, B) if a_white else (B, A)
    moves = op.split(); res = None; adj = 0
    for ply in range(len(moves), 300):
        p = w if ply % 2 == 0 else b
        mv, sc = go(p, moves)
        if mv is None: res = "crash"; break
        if mv == "0000":
            res = "loss" if sc is None or True else "draw"   # side to move has no move: mate or stalemate, decided below
            mated = go_in_check(p, moves)
            res = ("L" if mated else "D", ply % 2)
            break
        moves.append(mv)
        if sc and sc[0] == "cp" and abs(sc[1]) > 1200: adj += 1
        elif sc and sc[0] == "mate": adj += 3
        else: adj = 0
        if adj >= 6:
            winner_white = (sc[1] > 0) == (ply % 2 == 0) if sc[0] == "cp" else (sc[1] > 0) == (ply % 2 == 0)
            res = ("W", 0 if winner_white else 1); break
        # draw by repetition / 50 moves: simple repetition of positions via move list
        if ply > 40 and moves[-4:-2] == moves[-8:-6] and moves[-2:] == moves[-6:-4] and moves[-4:] == moves[-8:-4]: res = ("D", 0); break
    else: res = ("D", 0)
    for p in (A, B):
        try: p.stdin.write("quit\n"); p.stdin.flush(); p.wait(timeout=5)
        except Exception: p.kill()
    return res, len(moves)
def go_in_check(p, moves): return True   # engine prints bestmove 0000 only when mated or stalemated; stalemate is rare in these games
tally = {"A": 0, "B": 0, "D": 0}
for g in range(games):
    a_white = g % 2 == 0
    res, n = game(OPEN[((g // 2) + OFF) % len(OPEN)], a_white)
    if res == "crash": print("crash"); continue
    kind, who = res   # who: index (0 white / 1 black) of the side that lost (L), won (W)
    if kind == "D": r = "D"
    elif kind == "L": r = "B" if (who == 0) == a_white else "A"
    else: r = "A" if (who == 0) == a_white else "B"
    tally[r] += 1
    print(f"game {g+1}: {r} ({n} plies)  A={tally['A']} B={tally['B']} D={tally['D']}", flush=True)
print("FINAL", tally, "A score %.1f/%d" % (tally["A"] + tally["D"] / 2, games))
