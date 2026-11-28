#!/usr/bin/env python3
"""tcec_extract.py PGN_DIR OUT.txt SEED MAX_POSITIONS [PART NPARTS]
Positions from the TCEC master archive (https://github.com/TCEC-Chess/tcecgames): every move comment has the engine's own score `wv=` (white's view,
pawns) and depth `d=`.  Output lines like gen.py:  fen|centipawns (white)|result (white)   - only quiet positions (not in check, the played move is not a
capture or promotion), standard chess games only, no mate scores, depth >= MIND (default 14), after the first SKIP plies, RATE of them kept."""
import sys, os, re, random, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cm
pgn_dir, out, seed, maxpos = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
part = int(sys.argv[5]) if len(sys.argv) > 5 else 0
nparts = int(sys.argv[6]) if len(sys.argv) > 6 else 1
rnd = random.Random(seed)
MIND = int(os.environ.get('MIND', '14'))       # least search depth of the engine's score
SKIP = int(os.environ.get('SKIP', '0'))        # plies at the start of a game (opening book) that are left out
RATE = float(os.environ.get('RATE', '0.6'))    # share of the quiet positions that is kept
TOK = re.compile(r"\{([^}]*)\}|(\d+\.(?:\.\.)?)|(\S+)")
WV = re.compile(r"\bwv=([-+]?\d+\.\d+|[-+]?M\d+)")
DP = re.compile(r"\bd=(\d+)")
def san_move(b, san):
    s = san.rstrip("+#!?")
    if s in ("O-O", "O-O-O", "0-0", "0-0-0"):
        want = 6 if s.count("-") == 1 else 2
        for m in b.pseudo():
            if b.b[m[0]] in ("K", "k") and abs(m[1] - m[0]) == 2 and (m[1] & 7) == want: return m
        return None
    promo = None
    if "=" in s: s, promo = s.split("="); promo = promo.lower()
    piece = "P"
    if s[0] in "KQRBN": piece = s[0]; s = s[1:]
    s = s.replace("x", "")
    to = cm.parse(s[-2:]); dis = s[:-2]
    for m in b.pseudo():
        if m[1] != to: continue
        c = b.b[m[0]]
        if c.upper() != piece: continue
        if (m[2] or None) != promo: continue
        if dis:
            if dis in "abcdefgh":
                if cm.name(m[0])[0] != dis: continue
            elif dis in "12345678":
                if cm.name(m[0])[1] != dis: continue
            elif cm.name(m[0]) != dis: continue
        n = b.copy(); n.push(m)
        if not n.attacked(n.king(not n.white), n.white): return m
    return None
files = sorted(glob.glob(os.path.join(pgn_dir, "*.pgn")))
files = [f for i, f in enumerate(files) if i % nparts == part]
rnd.shuffle(files)
npos = 0; ngames = 0; bad = 0
fo = open(out, "w")
for fn in files:
    text = open(fn, encoding="utf-8", errors="replace").read()
    for g in text.split("[Event ")[1:]:
        if npos >= maxpos: break
        head, _, body = g.partition("\n\n")
        if "[FEN " in head or "[Variant" in head or "[SetUp" in head: continue
        mres = re.search(r'\[Result "([^"]+)"\]', head)
        if not mres or mres.group(1) not in ("1-0", "0-1", "1/2-1/2"): continue
        res = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}[mres.group(1)]
        b = cm.Board(); recs = []; ok = True; pending = None; ply = 0
        for t in TOK.finditer(body):
            c, num, san = t.groups()
            if c is not None:
                if pending is not None:
                    w = WV.search(c); d = DP.search(c)
                    if w and d and int(d.group(1)) >= MIND and ply > SKIP and "M" not in w.group(1):
                        recs.append((pending[0], int(round(float(w.group(1)) * 100)), pending[1]))
                    pending = None
                continue
            if num is not None or san in ("1-0", "0-1", "1/2-1/2", "*"): continue
            ply += 1; fen = b.fen(); chk = b.in_check()
            m = san_move(b, san)
            if m is None: ok = False; break
            iscap = b.b[m[1]] is not None or (b.b[m[0]] in "Pp" and (m[0] & 7) != (m[1] & 7)) or m[2]
            b.push(m)
            pending = (fen, not (chk or iscap))
        if not ok: bad += 1; continue
        ngames += 1
        for fen, sc, quiet in recs:
            if quiet and abs(sc) < 3000 and rnd.random() < RATE:
                fo.write(f"{fen}|{sc}|{res}\n"); npos += 1
        if ngames % 200 == 0: fo.flush(); print(ngames, "games", npos, "positions", bad, "unreadable", flush=True)
    if npos >= maxpos: break
print("done", ngames, "games", npos, "positions", bad, "unreadable")
