#!/usr/bin/env python3
"""APEX-Z 7 NNUE: (1) the engine's static evaluation equals the Python integer reference (nnue/nnue.py) on many positions, (2) the
incrementally updated accumulators equal a rebuild at every node of searches over castling / en passant / promotion / check positions
(UCI option NNDebug, one thread and two), (3) `UseNNUE false` gives exactly the old engine's node counts, (4) a bad network file is refused.
No trained net is shipped (the ones I trained were weaker than the hand-written evaluation), so the test makes a random one:
the point is that the integer arithmetic and the incremental updates are exact, not that the net is good."""
import os, random, shutil, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AX = os.path.join(ROOT, "examples", "Zoomy Chess Engines", "Apex Z")
sys.path.insert(0, os.path.join(AX, "nnue"))
import numpy as np
import nnue, cm
TMP = tempfile.mkdtemp()
rg = np.random.default_rng(5)
H, L1, L2 = 32, 16, 16
rnet = nnue.Net(rg.integers(60, 200, H), rg.integers(-45, 46, (nnue.NF, H)), rg.integers(-1500, 1500, (L1, 2 * H)), rg.integers(-30000, 30000, L1),
                rg.integers(-1500, 1500, (L2, L1)), rg.integers(-30000, 30000, L2), rg.integers(-1500, 1500, L2), 4000, 400)
rnet.save(os.path.join(TMP, "apexz.nnue"))
fails = 0
def fail(*a):
    global fails
    fails += 1; print("FAIL", *a)
shutil.copy(os.path.join(AX, "Apex-Z.zmy"), TMP)
r = subprocess.run([sys.executable, os.path.join(ROOT, "zoomy.py"), os.path.join(TMP, "Apex-Z.zmy"), "--native", "-o", os.path.join(TMP, "apexz")], capture_output=True, text=True)
if r.returncode: fail("build", r.stdout[-300:]); sys.exit(1)
ENG = os.path.join(TMP, "apexz")
def session(cmds, timeout=300):
    return subprocess.run([ENG], input="\n".join(["uci"] + cmds + ["quit"]) + "\n", capture_output=True, text=True, timeout=timeout, cwd=TMP).stdout
net = nnue.Net.load(os.path.join(TMP, "apexz.nnue"))
# 1. static evaluation against the reference: random legal positions
rnd = random.Random(7)
fens = []
for g in range(60):
    b = cm.Board()
    for _ in range(rnd.randint(4, 90)):
        ms = b.legal()
        if not ms: break
        b.push(rnd.choice(ms))
    if b.legal(): fens.append(b.fen())
cmds = []
for f in fens: cmds += ["position fen " + f, "nneval"]
out = [l.split() for l in session(cmds).splitlines() if l.startswith("nneval")]
if len(out) != len(fens): fail("nneval lines", len(out), len(fens))
else:
    for f, l in zip(fens, out):
        if int(l[1]) != net.evaluate(f): fail("eval", f, l, net.evaluate(f))
# 2. incremental updates
POS = ["r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",      # castling both ways, captures
       "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",          # promotions, checks
       "rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3",             # en passant
       "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", "r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1", "4k3/1P6/8/8/8/8/6p1/4K3 w - - 0 1"]
for threads in (1, 2):
    for f in POS:
        o = session(["setoption name NNDebug value true", f"setoption name Threads value {threads}", "position fen " + f, "go depth 9"])
        if "MISMATCH" in o or "bestmove" not in o: fail("accumulators", threads, f)
# 3. UseNNUE false is the old engine
o = session(["setoption name Threads value 1", "setoption name UseNNUE value false", "setoption name Features value 262095", "position startpos", "go depth 9"])
if "depth 9 score cp 38 nodes 53287 " not in o: fail("UseNNUE false is not the old evaluation", o[-300:])
# 4. a bad file
open(os.path.join(TMP, "bad.nnue"), "wb").write(b"NOPE" + bytes(100))
o = session(["setoption name EvalFile value " + os.path.join(TMP, "bad.nnue")])
if "NNUE file not loaded" not in o: fail("bad file accepted", o[-200:])
# 5. a FEN with all 32 pieces has a 71 character board field (it used to run off the end of the token array)
o = session(["position fen r1q1r1k1/1ppb1pb1/1n1p1np1/3Pp1Bp/p1P1P1P1/P1N2P1P/1P3Q2/1KNR1B1R b - - 8 17", "go depth 3"])
if "bestmove" not in o or "error" in o: fail("long FEN", o[-200:])
shutil.rmtree(TMP, ignore_errors=True)
print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
