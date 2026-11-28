import subprocess, sys, os, re
ENGINE = sys.argv[1] if len(sys.argv) > 1 else "v30.zmy"
src = open(ENGINE).read()
cut = src.index("(=============================================================================)\n(                               MAIN GAME ENTRY")
body = src[:cut]
PERFT = '''
Let a number be called bad_hash
define perft with ply and depth and side:
    Let a number be called total
    Let a number be called count
    Let a number be called slot
    Let a number be called src
    Let a number be called dst
    if depth is 0:
        give back 1
    call generate with ply and side
    set count to item ply of mv_count
    for i from 0 to count - 1:
        set slot to ((ply - 1) * 256) + i
        set src to item slot of mv_from
        set dst to item slot of mv_to
        call apply_move with ply and src and dst
        if hash_pieces is not scan_hash():
            add 1 to bad_hash
        add perft(ply + 1, depth - 1, 0 - side) to total
        call undo_move with ply and src and dst
    give back total
'''
VAL = dict(zip("pnbrqk", range(1, 7)))
def fen_setup(fen):
    f = fen.split()
    rows = f[0].split("/")
    lines = ["    for sq from 21 to 98:", "        if item sq of board is not 99:", "            set item sq of board to 0"]
    for ri, row in enumerate(rows):
        rank = 7 - ri; file = 0
        for ch in row:
            if ch.isdigit(): file += int(ch)
            else:
                v = VAL[ch.lower()] * (1 if ch.isupper() else -1)
                lines.append("    set item %d of board to %d" % ((rank + 2) * 10 + file + 1, v)); file += 1
    for i, c in enumerate("KQkq"):
        lines.append("    set item %d of castle to %d" % (i, 1 if c in f[2] else 0))
    ep = 0
    if f[3] != "-":
        ep = (int(f[3][1]) - 1 + 2) * 10 + "abcdefgh".index(f[3][0]) + 1
    lines.append("    set ep_sq to %d" % ep)
    return "\n".join(lines), (1 if f[1] == "w" else -1)
POS = [
 ("start", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -", [20, 400, 8902, 197281]),
 ("kiwipete", "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq -", [48, 2039, 97862]),
 ("pos3", "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - -", [14, 191, 2812, 43238]),
 ("kiwipete-black", "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R b KQkq -", None),
 ("ep-black", "rnbqkbnr/ppp1pppp/8/8/3pP3/8/PPPP1PPP/RNBQKBNR b KQkq e3", None),
]
fails = 0
for name, fen, want in POS:
    setup, side = fen_setup(fen)
    depth = len(want) if want else 3
    prog = body + PERFT + "\naction start:\n    run init_tables\n" + ("    run init_bitboards\n" if "init_bitboards" in body else "") + "    run init_board\n" + setup + \
        ("\n    run bb_sync" if "init_bitboards" in body else "") + "\n    set hash_pieces to scan_hash()\n    for d from 1 to %d:\n        print perft(1, d, %d)\n    print bad_hash\n" % (depth, side)
    os.makedirs("pf", exist_ok=True)
    open("pf/p.zmy", "w").write(prog)
    b = subprocess.run([sys.executable, "../zoomy5/zoomy.py", "--native", "pf/p.zmy", "-o", "pf/p.bin"], capture_output=True, text=True)
    if "static ELF" not in b.stdout:
        print("BUILD FAIL", name, b.stdout[:300], b.stderr[:300]); fails += 1; continue
    r = subprocess.run(["pf/p.bin"], capture_output=True, text=True, timeout=600)
    got = [int(x) for x in r.stdout.split()]
    hashbad = got.pop()
    if hashbad: print('HASH MISMATCHES', hashbad)
    if want:
        ok = got == want
    else:
        ok = len(got) == depth
    print(("PASS " if ok else "FAIL ") + name, got, want or "")
    fails += not ok
print(fails, "failure(s)")
