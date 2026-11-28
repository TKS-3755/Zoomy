import subprocess, sys, os, time
src=open("Apex-Z.zmy").read()
body=src[:src.index("(=============================================================================)\n(                               MAIN GAME ENTRY")]
VAL=dict(zip("pnbrqk",range(1,7)))
def setup(fen):
    f=fen.split(); L=["    for sq from 21 to 98:","        if item sq of board is not 99:","            set item sq of board to 0"]
    for ri,row in enumerate(f[0].split("/")):
        rank=7-ri; file=0
        for ch in row:
            if ch.isdigit(): file+=int(ch)
            else:
                L.append("    set item %d of board to %d"%((rank+2)*10+file+1,VAL[ch.lower()]*(1 if ch.isupper() else -1))); file+=1
    for i,c in enumerate("KQkq"): L.append("    set item %d of castle to %d"%(i,1 if c in f[2] else 0))
    L.append("    set ep_sq to 0")
    return "\n".join(L), (1 if f[1]=="w" else -1)
POS={"opening":"rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -",
"middlegame":"r1bq1rk1/pp2ppbp/2np1np1/8/3NP3/2N1BP2/PPPQ2PP/R3KB1R b KQ -",
"tactical":"r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq -",
"endgame":"8/5pk1/6p1/3r4/8/6P1/5PK1/3R4 w - -"}
D=int(sys.argv[1])
res=[]
for name,fen in POS.items():
    s,side=setup(fen)
    prog=body+"\naction start:\n    run init_tables\n    run init_board\n"+s+"\n    set pruning to 511\n    set feat to 15\n    Let a number be called sc\n    set sc to think(%d, %d)\n    print best_from, \" \", best_to, \" \", sc, \" \", nodes\n"%(D,side)
    d="tm_%d"%D; os.makedirs(d,exist_ok=True); open(d+"/t_%s.zmy"%name,"w").write(prog)
    subprocess.run([sys.executable,"../zoomy5/zoomy.py","--native",d+"/t_%s.zmy"%name,"-o",d+"/t_%s.bin"%name],capture_output=True)
    t=time.time()
    try:
        r=subprocess.run([d+"/t_%s.bin"%name],capture_output=True,text=True,timeout=int(sys.argv[2])).stdout.split()
        dt=time.time()-t; res.append("%s %.1fs %sk nodes"%(name,dt,round(int(r[3])/1000)))
    except subprocess.TimeoutExpired:
        res.append("%s >%ss"%(name,sys.argv[2]))
print("depth",D,"|"," | ".join(res))
