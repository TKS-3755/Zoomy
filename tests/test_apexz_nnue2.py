#!/usr/bin/env python3
"""APEX-Z NNUE version 2 (file magic APX2: king buckets with mirroring, pairwise product, clipped + squared layer 1 with skip, output buckets by piece count): (1) the engine's static evaluation equals the Python integer reference (nnue/nnue2.py) on random positions of every piece count, (2) the incrementally updated accumulators equal a rebuild at every node (NNDebug), (3) a version 1 file still loads and evaluates, (4) a bad version 2 header is refused.  A random net: the point is exact arithmetic, not strength."""
import os, random, shutil, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AX = os.path.join(ROOT, "examples", "Zoomy Chess Engines", "Apex Z")
sys.path.insert(0, os.path.join(AX, "nnue"))
import numpy as np
import nnue, nnue2, cm
TMP = tempfile.mkdtemp()
rg = np.random.default_rng(5)
H, L1, L2, NB = 32, 16, 16, 8
rnet = nnue2.Net2(rg.integers(60, 200, H), rg.integers(-45, 46, (nnue2.NF2, H)), rg.integers(-1500, 1500, (NB, L1, H)), rg.integers(-30000, 30000, (NB, L1)),
                  rg.integers(-1500, 1500, (NB, L2, 2 * L1)), rg.integers(-30000, 30000, (NB, L2)), rg.integers(-1500, 1500, (NB, L2)), rg.integers(-1500, 1500, (NB, L1)),
                  rg.integers(-4000, 4000, NB), 400)
rnet.save(os.path.join(TMP, "apexz.nnue"))
assert nnue2.Net2.load(os.path.join(TMP, "apexz.nnue")).evaluate("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1") == rnet.evaluate("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
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
net = nnue2.Net2.load(os.path.join(TMP, "apexz.nnue"))
# 1. static evaluation against the reference: random legal positions
rnd = random.Random(7)
fens = []
for g in range(150):
    b = cm.Board()
    for _ in range(rnd.randint(4, 200)):
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
# 3. a version 1 file still loads and agrees with its reference
rg1 = np.random.default_rng(9)
r1 = nnue.Net(rg1.integers(60, 200, 32), rg1.integers(-45, 46, (nnue.NF, 32)), rg1.integers(-1500, 1500, (16, 64)), rg1.integers(-30000, 30000, 16),
              rg1.integers(-1500, 1500, (16, 16)), rg1.integers(-30000, 30000, 16), rg1.integers(-1500, 1500, 16), 4000, 400)
p1 = os.path.join(TMP, "v1.nnue"); r1.save(p1)
cmds = ["setoption name EvalFile value " + p1]
for f in fens[:20]: cmds += ["position fen " + f, "nneval"]
o = session(cmds)
if "NNUE loaded" not in o: fail("v1 not loaded", o[-200:])
got = [l.split() for l in o.splitlines() if l.startswith("nneval")]
if len(got) != 20 or any(int(l[1]) != r1.evaluate(f) for f, l in zip(fens[:20], got)): fail("v1 evaluation")
# 4. a bad version 2 header (buckets 0)
d = bytearray(open(os.path.join(TMP, "apexz.nnue"), "rb").read(200)); d[12:14] = b"\0\0"
open(os.path.join(TMP, "bad.nnue"), "wb").write(bytes(d))
o = session(["setoption name EvalFile value " + os.path.join(TMP, "bad.nnue")])
if "NNUE file not loaded" not in o: fail("bad file accepted", o[-200:])
print("positions checked", len(fens), "buckets", sorted({nnue2.bucket_of(nnue2.features2(f)[3], 8) for f in fens}))
shutil.rmtree(TMP, ignore_errors=True)
print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
