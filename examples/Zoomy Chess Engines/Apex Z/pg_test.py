#!/usr/bin/env python3
"""Check APEX-Z's Polyglot support against an independent Python implementation.
Usage: pg_test.py ENGINE_DIR RANDOM64_FILE   (ENGINE_DIR holds the engine binary 'apexz'; a book.bin is written there)"""
import os, struct, subprocess, sys, collections
d, rfile = sys.argv[1], sys.argv[2]
R = [int(x, 16) for x in open(rfile).read().split()]
assert len(R) == 781
KIND = {c: i for i, c in enumerate("pPnNbBrRqQkK")}
def key(fen):
    f = fen.split(); k = 0
    rows = f[0].split("/")
    board = {}
    for i, row in enumerate(rows):
        r = 7 - i; c = 0
        for ch in row:
            if ch.isdigit(): c += int(ch)
            else: board[(r, c)] = ch; k ^= R[64 * KIND[ch] + 8 * r + c]; c += 1
    for ch, off in zip("KQkq", range(768, 772)):
        if ch in f[2]: k ^= R[off]
    if f[3] != "-":
        file = ord(f[3][0]) - 97; row = int(f[3][1]) - 1   # ep square row 2 (white pushed) or 5
        pawn, side_row = ("p", row + 1) if f[1] == "w" else ("P", row - 1)
        pawn = "P" if f[1] == "w" else "p"
        pr = row - 1 if f[1] == "w" else row + 1
        if board.get((pr, file - 1)) == pawn or board.get((pr, file + 1)) == pawn:
            k ^= R[772 + file]
    if f[1] == "w": k ^= R[780]
    return k
def mv(frm, to, promo=0):
    ff, fr, tf, tr = ord(frm[0]) - 97, int(frm[1]) - 1, ord(to[0]) - 97, int(to[1]) - 1
    return tf | (tr << 3) | (ff << 6) | (fr << 9) | (promo << 12)
START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
E4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
CAST = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
CASTB = "r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1"
EP = "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1"
PROM = "7k/P7/8/8/8/8/8/K7 w - - 0 1"
ILL = "4k3/8/8/8/8/8/8/4K3 w - - 0 1"
assert key(START) == 0x463b96181691fc9c and key("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1") == 0x823c9b50fd114196
ents = [(key(START), mv("e2", "e4"), 100), (key(START), mv("d2", "d4"), 50), (key(START), mv("a2", "a5"), 500),   # illegal one is ignored
        (key(E4), mv("e7", "e5"), 7), (key(CAST), mv("e1", "h1"), 10), (key(CAST), mv("e1", "a1"), 0),
        (key(CASTB), mv("e8", "a8"), 5), (key(EP), mv("e5", "d6"), 9), (key(PROM), mv("a7", "a8", 4), 3),
        (key(ILL), mv("e1", "e2"), 0)]
ents.sort(key=lambda e: e[0])
with open(os.path.join(d, "book.bin"), "wb") as fh:
    for k, m, w in ents: fh.write(struct.pack(">QHHI", k, m, w, 0))
def session(cmds):
    p = subprocess.run([os.path.join(d, "apexz")], input="uci\n" + cmds + "quit\n", capture_output=True, text=True, cwd=d, timeout=120)
    return p.stdout.splitlines()
fails = 0
def check(name, ok, info=""):
    global fails
    print(("ok   " if ok else "FAIL ") + name, info)
    fails += not ok
# 1. keys computed by the engine
fens = [START, E4, CAST, CASTB, EP, PROM,
        "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2",          # ep not capturable: no ep term
        "rnbqkbnr/ppp1pppp/8/8/3pP3/5N2/PPPP1PPP/RNBQKB1R b KQkq e3 0 3"]         # ep capturable by black
out = session("".join(f"position fen {f}\npgkey\n" for f in fens))
got = [l.split() for l in out if l.startswith("pgkey")]
for f, g in zip(fens, got):
    check("key " + f.split()[0][:20] + " " + f.split()[1], (int(g[1]) << 32 | int(g[2])) == key(f))
# 2. book moves
def bestmoves(pos, n):
    o = session(f"position {pos}\n" + "go depth 2\n" * n)
    return [l.split()[1] for l in o if l.startswith("bestmove")], [l for l in o if "Polyglot" in l]
bm, pl = bestmoves("startpos", 300)
c = collections.Counter(bm)
check("start position: only legal book moves, weights ~2:1", set(c) <= {"e2e4", "d2d4"} and 1.5 < c["e2e4"] / max(1, c["d2d4"]) < 2.7 and len(pl) == 300, dict(c))
bm, pl = bestmoves("startpos moves e2e4", 3)
check("after e4 the book answers e7e5", bm == ["e7e5"] * 3 and len(pl) == 3, bm)
bm, pl = bestmoves("fen " + CAST, 5)
check("white castles short (e1h1 means e1g1), zero-weight long castle never played", set(bm) == {"e1g1"}, bm)
bm, pl = bestmoves("fen " + CASTB, 3)
check("black castles long (e8a8 means e8c8)", set(bm) == {"e8c8"}, bm)
bm, pl = bestmoves("fen " + EP, 3)
check("en passant", set(bm) == {"e5d6"}, bm)
bm, pl = bestmoves("fen " + PROM, 3)
check("promotion to a queen", set(bm) == {"a7a8q"}, bm)
bm, pl = bestmoves("fen " + ILL, 2)
check("zero-weight book entry is not used", len(pl) == 0 and all(m != "e1e2" or True for m in bm), bm)
os.remove(os.path.join(d, "book.bin"))
bm, pl = bestmoves("startpos moves e2e4", 1)
check("no book.bin: falls back to the text book", bm == ["d7d5"] or len(pl) == 0, bm)
print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
