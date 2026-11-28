import subprocess, sys, os, importlib.util
ENGINE = sys.argv[1]
src = open(ENGINE).read()
body = src[:src.index("(=============================================================================)\n(                               MAIN GAME ENTRY")]
VAL = dict(zip("pnbrqk", range(1, 7)))
def setup(fen):
    f = fen.split(); lines = ["    for sq from 21 to 98:", "        if item sq of board is not 99:", "            set item sq of board to 0"]
    for ri, row in enumerate(f[0].split("/")):
        rank = 7 - ri; file = 0
        for ch in row:
            if ch.isdigit(): file += int(ch)
            else:
                lines.append("    set item %d of board to %d" % ((rank + 2) * 10 + file + 1, VAL[ch.lower()] * (1 if ch.isupper() else -1))); file += 1
    for i, c in enumerate("KQkq"): lines.append("    set item %d of castle to %d" % (i, 1 if c in f[2] else 0))
    lines.append("    set ep_sq to 0")
    return "\n".join(lines), (1 if f[1] == "w" else -1)
def sq(n):
    r, f = divmod(n - 21, 10)
    return "abcdefgh"[f] + str(r + 1)
T = [
 ("back-rank mate in 1", "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - -", "d1d8", True),
 ("scholar's mate", "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq -", "h5f7", True),
 ("knight fork", "r3k3/8/8/3N4/8/8/8/4K3 w - -", "d5c7", False),
 ("rook ladder mate", "k7/8/1K6/8/8/8/8/7R w - -", "h1h8", True),
 ("black to mate", "7k/8/8/8/8/5q2/6r1/7K b - -", "g2g1|f3f1", True),
 ("do not hang the queen", "rnb1kbnr/pppp1ppp/8/4p3/4P1q1/5N2/PPPP1PPP/RNBQKB1R w KQkq -", None, False),
]
bad = 0
for name, fen, want, mate in T:
    s, side = setup(fen)
    for pr in (511,):
        prog = body + "\naction start:\n    run init_tables\n    run init_board\n" + s + "\n    set pruning to %d\n    set feat to 7\n    Let a number be called sc\n    set sc to think(6, %d)\n    print best_from, \" \", best_to, \" \", sc, \" \", nodes\n" % (pr, side)
        open("sp/t.zmy", "w").write(prog)
        b = subprocess.run([sys.executable, "../zoomy5/zoomy.py", "--native", "sp/t.zmy", "-o", "sp/t.bin"], capture_output=True, text=True)
        assert "static ELF" in b.stdout, b.stdout + b.stderr
        r = subprocess.run(["sp/t.bin"], capture_output=True, text=True, timeout=300).stdout.split()
        mv = sq(int(r[0])) + sq(int(r[1])); score = int(r[2])
        ok = (want is None or mv in want.split("|")) and (not mate or score > 70000)
        bad += not ok
        print(("PASS" if ok else "FAIL"), name, "pruning" if pr else "plain  ", mv, score, "nodes", r[3])
print(bad, "failure(s)")
