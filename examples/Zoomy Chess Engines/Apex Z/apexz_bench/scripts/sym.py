import subprocess, sys, os
src=open(sys.argv[1]).read()
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
    return "\n".join(L)
def mirror(fen):
    rows=fen.split()[0].split("/")[::-1]
    return "/".join("".join(c.swapcase() for c in r) for r in rows)+" w - -"
FENS=["rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w - -",
"r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w - -",
"8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - -",
"4k3/8/8/3P4/8/8/PP3PPP/4K3 w - -",
"r1bq1rk1/pp2ppbp/2np1np1/8/3NP3/2N1BP2/PPPQ2PP/R3KB1R w - -",
"8/5pk1/6p1/8/8/6P1/5PK1/4B3 w - -",
"6k1/5ppp/8/8/8/8/5PPP/3RR1K1 w - -",
"4k3/8/8/8/8/8/8/4KB2 w - -"]
prog=body+"\naction start:\n    run init_tables\n    run init_board\n    set feat to 7\n"
for fen in FENS:
    prog+=setup(fen)+"\n    print evaluate_full()\n"+setup(mirror(fen))+"\n    print evaluate_full()\n"
os.makedirs("sp",exist_ok=True); open("sp/y.zmy","w").write(prog)
b=subprocess.run([sys.executable,"../zoomy5/zoomy.py","--native","sp/y.zmy","-o","sp/y.bin"],capture_output=True,text=True); assert "static ELF" in b.stdout,b.stdout+b.stderr
v=[int(x) for x in subprocess.run(["sp/y.bin"],capture_output=True,text=True,timeout=60).stdout.split()]
bad=0
for i,fen in enumerate(FENS):
    a,m=v[2*i],v[2*i+1]; ok=(a==-m); bad+=not ok
    print("OK " if ok else "BAD",a,m,fen)
print(bad,"asymmetric")
