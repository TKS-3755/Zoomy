#!/usr/bin/env python3
"""depth_bench.py ENGINE OUT.csv [CAP_SECONDS_PER_POSITION] [THREADS]: one iterative-deepening search per position to depth 20; the engine's info lines give the cumulative time at each depth."""
import subprocess, sys, os, time, threading
eng = os.path.abspath(sys.argv[1]); out = sys.argv[2]
cap = float(sys.argv[3]) if len(sys.argv) > 3 else 1200
thr = sys.argv[4] if len(sys.argv) > 4 else "1"
POS = [("opening", "position startpos"),
       ("kiwipete", "position fen r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"),
       ("endgame", "position fen 8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1")]
rows = []
for name, pos in POS:
    p = subprocess.Popen([eng], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1, cwd=os.path.dirname(eng))
    p.stdin.write("uci\n"); p.stdin.flush()
    while p.stdout.readline().strip() != "uciok": pass
    p.stdin.write(f"setoption name Threads value {thr}\nsetoption name OwnBook value false\nisready\n"); p.stdin.flush()
    while p.stdout.readline().strip() != "readyok": pass
    p.stdin.write(f"{pos}\ngo depth 20\n"); p.stdin.flush()
    t0 = time.time()
    threading.Timer(cap, p.kill).start()
    for l in p.stdout:
        if l.startswith("info depth"):
            t = l.split(); d = int(t[2]); i = t.index("nodes"); j = t.index("time")
            rows.append((name, d, int(t[i+1]), int(t[j+1]), " ".join(t[3:6])))
            open(out, "w").write("position,depth,nodes,time_ms,score\n" + "\n".join(f"{a},{b},{c},{d_},{e}" for a, b, c, d_, e in rows) + "\n")
        if l.startswith("bestmove"): break
    p.kill()
    print(name, "done", round(time.time() - t0), "s", flush=True)
