import subprocess, sys, os
ENGINE=sys.argv[1]; D=int(sys.argv[2]); SEEDS=int(sys.argv[3])
src=open(ENGINE).read()
body=src[:src.index("(=============================================================================)\n(                               MAIN GAME ENTRY")]
MASKS=[0,511,1,8,64,128]
DRV='''
action start:
    run init_tables
    run init_board
    Let a number be called side
    Let a number be called count
    Let a number be called seed
    Let a number be called pick
    Let a number be called src_m
    Let a number be called dst_m
    Let a number be called sc
    Let a number be called k
    set seed to %d
    set side to 1
    for turn from 1 to 16:
        call generate with 1 and side
        set count to item 1 of mv_count
        if count is 0:
            stop
        if turn is at most 8:
            set seed to (seed * 48271) mod 2147483647
            set pick to seed mod count
            set src_m to item pick of mv_from
            set dst_m to item pick of mv_to
        else:
            write "pos"
%s
            print ""
            set pruning to 511
            set sc to think(4, side)
            set src_m to best_from
            set dst_m to best_to
        call apply_move with 0 and src_m and dst_m
        set side to 0 - side
'''
CALLS="".join('            set pruning to %d\n            set sc to think(%d, side)\n            write " ", sc, ":", best_from * 128 + best_to\n'%(m,D) for m in MASKS)
big={m:0 for m in MASKS}; n=0; diffs={m:[] for m in MASKS}
for seed in range(1,SEEDS+1):
    prog=body+DRV%(seed*104729,CALLS)
    os.makedirs("dv",exist_ok=True); open("dv/d.zmy","w").write(prog)
    b=subprocess.run([sys.executable,"../zoomy5/zoomy.py","--native","dv/d.zmy","-o","dv/d.bin"],capture_output=True,text=True)
    assert "static ELF" in b.stdout,b.stdout+b.stderr
    for l in subprocess.run(["dv/d.bin"],capture_output=True,text=True,timeout=200).stdout.splitlines():
        if not l.startswith("pos"): continue
        vals=[x.split(":") for x in l[3:].split()]
        sc=[int(a) for a,_ in vals]; mv=[int(b) for _,b in vals]
        n+=1
        for i,m in enumerate(MASKS):
            d=sc[i]-sc[0]
            diffs[m].append(d)
            if abs(d)>150: big[m]+=1
print("positions",n)
for m in MASKS: 
    ds=diffs[m]; print("mask %3d  |diff|>150: %3d   mean abs diff %.0f"%(m,big[m],sum(abs(d) for d in ds)/max(1,len(ds))))
