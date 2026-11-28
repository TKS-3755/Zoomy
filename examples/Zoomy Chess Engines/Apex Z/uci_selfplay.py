#!/usr/bin/env python3
"""Two APEX-Z processes play each other over UCI. Usage: uci_selfplay.py ENGINE MOVETIME_MS GAMES [MAXPLIES]"""
import subprocess, sys, time, os
eng, mt, games = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
maxp = int(sys.argv[4]) if len(sys.argv) > 4 else 120
def start():
    p = subprocess.Popen([eng], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1, cwd=os.path.dirname(eng) or ".")
    p.stdin.write("uci\n"); p.stdin.flush()
    while p.stdout.readline().strip() != "uciok": pass
    p.stdin.write("setoption name Threads value 2\nisready\n"); p.stdin.flush()
    while p.stdout.readline().strip() != "readyok": pass
    return p
def go(p, moves):
    p.stdin.write("position startpos" + (" moves " + " ".join(moves) if moves else "") + f"\ngo movetime {mt}\n"); p.stdin.flush()
    t = time.time(); illegal = False
    while True:
        l = p.stdout.readline()
        if not l: return None, 0, True
        if "illegal" in l: illegal = True
        if l.startswith("bestmove"): return l.split()[1], time.time() - t, illegal
for g in range(games):
    a, b = start(), start()
    moves = []; worst = 0; res = "maxplies"
    for ply in range(maxp):
        p = a if ply % 2 == 0 else b
        mv, dt, ill = go(p, moves)
        worst = max(worst, dt)
        if mv is None: res = "ENGINE DIED at ply %d" % ply; break
        if ill: res = "ILLEGAL at ply %d after %s" % (ply, moves[-3:]); break
        if mv == "0000": res = "game over (no legal move) at ply %d" % ply; break
        moves.append(mv)
    print(f"game {g+1}: {res}; {len(moves)} plies; slowest move {worst*1000:.0f} ms vs {mt} ms asked", flush=True)
    for p in (a, b):
        p.stdin.write("quit\n"); p.stdin.flush(); p.wait(timeout=5)
