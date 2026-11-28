import subprocess, sys, os
ENGINE=sys.argv[1]; DEPTH=int(sys.argv[2]); GAMES=int(sys.argv[3]); PLIES=int(sys.argv[4]); FA=int(sys.argv[5]); FB=int(sys.argv[6]); OFF=int(sys.argv[7]) if len(sys.argv)>7 else 0
src=open(ENGINE).read()
body=src[:src.index("(=============================================================================)\n(                               MAIN GAME ENTRY")]
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
    Let a number be called result
    Let a number be called a_side
    set seed to %d
    set a_side to %d
    set side to 1
    set pruning to 511
    for turn from 1 to %d:
        call generate with 1 and side
        set count to item 1 of mv_count
        if count is 0:
            if in_check(side) is 1:
                set result to 0 - side
            stop
        if turn is at most 6:
            set seed to (seed * 48271) mod 2147483647
            set pick to seed mod count
            set src_m to item pick of mv_from
            set dst_m to item pick of mv_to
        else:
            set feat to %d
            if side is a_side:
                set feat to %d
            set sc to think(%d, side)
            set src_m to best_from
            set dst_m to best_to
        call apply_move with 0 and src_m and dst_m
        set side to 0 - side
    set feat to 1
    print result, " ", evaluate_basic()
'''
tot=dict(A=0,B=0,draw=0,adv=0)
for g in range(GAMES):
    a_side=1 if g%2==0 else -1
    prog=body+DRV%((g//2+1+OFF)*7919,a_side,PLIES,FB,FA,DEPTH)
    d="mt2_%d_%d"%(FA,FB); os.makedirs(d,exist_ok=True); open(d+"/m.zmy","w").write(prog)
    b=subprocess.run([sys.executable,"../zoomy5/zoomy.py","--native",d+"/m.zmy","-o",d+"/m.bin"],capture_output=True,text=True)
    assert "static ELF" in b.stdout,b.stdout+b.stderr
    res,ev=map(float,subprocess.run([d+"/m.bin"],capture_output=True,text=True,timeout=600).stdout.split())
    adv = (3000 if res*a_side>0 else -3000) if res!=0 else max(-2000,min(2000,ev*a_side))
    tot["adv"]+=adv
    tot["A" if adv>150 else "B" if adv<-150 else "draw"]+=1
tot["adv"]=round(tot["adv"]/GAMES); print("A=feat",FA,"B=feat",FB,"depth",DEPTH,tot)
