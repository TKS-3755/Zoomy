import subprocess, sys, os
ENGINE = sys.argv[1]; DEPTH = int(sys.argv[2]); SEEDS = int(sys.argv[3])
src = open(ENGINE).read()
body = src[:src.index("(=============================================================================)\n(                               MAIN GAME ENTRY")]
DRIVER = '''
action start:
    run init_tables
    run init_board
    Let a number be called side
    Let a number be called s_on
    Let a number be called s_off
    Let a number be called n_on
    Let a number be called n_off
    Let a number be called m_on
    Let a number be called m_off
    Let a number be called count
    Let a number be called legal
    Let a number be called seed
    Let a number be called pick
    Let a number be called slot
    set seed to %d
    set side to 1
    for turn from 1 to 60:
        (a few random opening moves, then the engine plays both sides)
        call generate with 1 and side
        set count to item 1 of mv_count
        if count is 0:
            print "end ", turn
            stop
        if turn is at most 6:
            set seed to (seed * 48271) mod 2147483647
            set pick to seed mod count
            set src_m to item pick of mv_from
            set dst_m to item pick of mv_to
        else:
            set pruning to 0
            set s_off to think(%d, side)
            set n_off to nodes
            set m_off to (best_from * 128) + best_to
            set pruning to 511
            set s_on to think(%d, side)
            set n_on to nodes
            set m_on to (best_from * 128) + best_to
            print "cmp ", s_off, " ", s_on, " ", m_off, " ", m_on, " ", n_off, " ", n_on, " ", side
            set src_m to best_from
            set dst_m to best_to
            (the chosen move must be one of the legal moves)
            call generate with 1 and side
            set count to item 1 of mv_count
            set legal to 0
            for i from 0 to count - 1:
                if item i of mv_from is src_m and item i of mv_to is dst_m:
                    set legal to 1
            if legal is 0:
                print "ILLEGAL ", src_m, " ", dst_m
                stop
        call apply_move with 0 and src_m and dst_m
        set side to 0 - side
'''
tot = dict(n=0, same_move=0, same_score=0, off=0, on=0, illegal=0, close=0)
for seed in range(1, SEEDS + 1):
    prog = body + DRIVER % (seed * 7919, DEPTH, DEPTH)
    prog = prog.replace("    Let a number be called pick\n", "    Let a number be called pick\n    Let a number be called src_m\n    Let a number be called dst_m\n")
    os.makedirs("sp", exist_ok=True)
    open("sp/s.zmy", "w").write(prog)
    b = subprocess.run([sys.executable, "../zoomy5/zoomy.py", "--native", "sp/s.zmy", "-o", "sp/s.bin"], capture_output=True, text=True)
    if "static ELF" not in b.stdout:
        print("BUILD FAIL", b.stdout[:400], b.stderr[:400]); sys.exit(1)
    r = subprocess.run(["sp/s.bin"], capture_output=True, text=True, timeout=900)
    for l in r.stdout.splitlines():
        p = l.split()
        if p[0] == "ILLEGAL": tot["illegal"] += 1; print("ILLEGAL", seed, l)
        if p[0] == "cmp":
            so, sn, mo, mn, no, nn = map(float, p[1:7])
            tot["n"] += 1; tot["same_move"] += mo == mn; tot["same_score"] += so == sn
            tot["close"] += abs(so - sn) <= 60; tot["off"] += no; tot["on"] += nn
print(tot, "node ratio off/on = %.1f" % (tot["off"] / max(1, tot["on"])))
