#!/usr/bin/env python3
"""bench.py <engine> [depth]  -- fixed-depth search over a position set; prints nodes/time/nps."""
import subprocess, sys, time
POS = [
 "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
 "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
 "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
 "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
 "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
 "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10",
 "2rq1rk1/pp1bppbp/3p1np1/8/3NP3/2N1BP2/PPPQ2PP/2KR1B1R b - - 0 11",
 "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4",
 "8/8/4k3/8/2p5/2K5/8/8 w - - 0 1",
 "8/5pk1/6p1/8/3R4/6P1/5PK1/3r4 w - - 0 1",
 "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1",
 "r2q1rk1/ppp2ppp/2np1n2/2b1p1B1/2B1P1b1/2NP1N2/PPP2PPP/R2Q1RK1 w - - 0 8",
 "3r2k1/pp3pp1/2p1b2p/q7/2PP4/1P2P1P1/P4PBP/2RQ2K1 w - - 0 1",
 "r1b2rk1/pp1nqppp/2p1pn2/3p4/1bPP4/2N1PN2/PPQ1BPPP/R1B2RK1 w - - 0 9",
 "4rrk1/pp1n1pp1/q5p1/P1pP4/2n3P1/7P/1P3PB1/R1BQ1RK1 w - - 0 1",
 "r1bq1rk1/pp2ppbp/2np1np1/8/3NP3/2N1BP2/PPPQ2PP/R3KB1R w KQ - 0 9",
 "8/p3k3/1p2p3/3pP1p1/P2P2P1/1P6/5K2/8 w - - 0 1",
 "2kr3r/ppp2ppp/2n1b3/4q3/4P3/2N2Q2/PPP2PPP/R1B2RK1 b - - 0 12",
 "5rk1/1ppb3p/p1pb4/6q1/3P1p1r/2P1R2P/PP1BQ1P1/5RKN w - - 0 1",
 "r3r1k1/pp3pbp/1qp3p1/2B5/2BP2b1/Q1n2N2/P4PPP/3R1K1R w - - 0 1",
]
def run(eng, depth):
    p = subprocess.Popen([eng], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
    tot_n = 0; tot_t = 0.0; sig = []
    def send(s): p.stdin.write(s+"\n"); p.stdin.flush()
    send("uci")
    for fen in POS:
        send("ucinewgame"); send("isready")
        while p.stdout.readline().strip() != "readyok": pass
        send(f"position fen {fen}")
        t = time.time(); send(f"go depth {depth}")
        n = 0
        while True:
            l = p.stdout.readline()
            if l.startswith("info depth") and " nodes " in l:
                tk = l.split(); n = int(tk[tk.index("nodes")+1])
            if l.startswith("bestmove"):
                sig.append(l.split()[1]); break
        dt = time.time()-t; tot_n += n; tot_t += dt
    send("quit"); p.wait()
    return tot_n, tot_t, sig
if __name__ == "__main__":
    eng = sys.argv[1]; depth = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    n, t, sig = run(eng, depth)
    print(f"{eng}: depth {depth}, nodes {n}, time {t:.2f}s, nps {int(n/max(t,1e-9))}")
    print(" ".join(sig))
