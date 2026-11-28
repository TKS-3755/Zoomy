import subprocess, sys, os
ENGINE=sys.argv[1]; DA=int(sys.argv[2]); DB=int(sys.argv[3]); GAMES=int(sys.argv[4]); PLIES=int(sys.argv[5]); PA=int(sys.argv[6]) if len(sys.argv)>6 else 1; OFF=int(sys.argv[7]) if len(sys.argv)>7 else 0
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
    Let a number be called n_a
    Let a number be called n_b
    Let a number be called result
    set seed to %d
    set side to 1
    set result to 0
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
            if (side is 1 and %d is 0) or (side is -1 and %d is 1):
                set pruning to %d
                set sc to think(%d, side)
                add nodes to n_a
            else:
                set pruning to 0
                set sc to think(%d, side)
                add nodes to n_b
            set src_m to best_from
            set dst_m to best_to
        call apply_move with 0 and src_m and dst_m
        set side to 0 - side
    print result, " ", evaluate(), " ", n_a, " ", n_b
'''
tot=dict(A=0,B=0,draw=0,nodesA=0,nodesB=0,adv=0)
for g in range(GAMES):
    seed=(g//2+1+OFF)*7919
    a_white = (g%2==0)   # the pruning engine plays White in even games
    prog=body+DRV%(seed,PLIES,1 if a_white else 0,1 if a_white else 0,PA,DA,DB)
    # pruning engine is "A": it plays the side where condition true
    prog=prog.replace("(side is 1 and %d is 0) or (side is -1 and %d is 1)"%(1 if a_white else 0,1 if a_white else 0),"(side is 1 and %d is 1) or (side is -1 and %d is 0)"%(1 if a_white else 0,1 if a_white else 0))
    os.makedirs("mt",exist_ok=True); open("mt/m_%d_%d.zmy"%(PA,DA),"w").write(prog)
    b=subprocess.run([sys.executable,"../zoomy5/zoomy.py","--native","mt/m_%d_%d.zmy"%(PA,DA),"-o","mt/m_%d_%d.bin"%(PA,DA)],capture_output=True,text=True)
    assert "static ELF" in b.stdout,b.stdout+b.stderr
    res,ev,na,nb=map(float,subprocess.run(["mt/m_%d_%d.bin"%(PA,DA)],capture_output=True,text=True,timeout=1800).stdout.split())
    # score from A's point of view: mate result or material eval
    if res!=0: a_score=(res if a_white else -res)
    else: a_score=(ev if a_white else -ev)/abs(ev if ev else 1) if abs(ev)>150 else 0
    tot["adv"]+=max(-2000,min(2000,(ev if a_white else -ev) if res==0 else (3000 if (res if a_white else -res)>0 else -3000)))
    tot["nodesA"]+=na; tot["nodesB"]+=nb
    tot["A" if a_score>0 else "B" if a_score<0 else "draw"]+=1
    print("game",g,"A white" if a_white else "A black","mate/result",res,"eval",ev,"A-nodes",na,"B-nodes",nb)
tot['adv']=round(tot['adv']/GAMES); print(tot)
