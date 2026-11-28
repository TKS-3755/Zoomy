import sys, numpy as np, scipy.sparse as sp, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
LAM = float(sys.argv[1]); out = sys.argv[2]
KIND = {'P':1,'N':2,'B':3,'R':4,'Q':5}
rows=[];cols=[];vals=[];y=[];n=0
for line in open('tcec_l.txt'):
    fen,sc,res,hce = line.rstrip().split('|'); sc=int(sc); hce=int(hce)
    if abs(sc)>1000 or abs(hce)>1500: continue
    bd=fen.split()[0].split('/')
    nb=nr=nq=0; ent=[]
    for i,rk in enumerate(bd):
        r=7-i; f=0
        for ch in rk:
            if ch.isdigit(): f+=int(ch); continue
            w=ch.isupper(); c=ch.upper(); rel=r if w else 7-r; sg=1 if w else -1
            if c=='K': ent.append((sg,'K',rel,f))
            else:
                ent.append((sg,KIND[c],rel,f))
                if c in 'NB': nb+=1
                elif c=='R': nr+=1
                elif c=='Q': nq+=1
            f+=1
    ph=min(24,nb+2*nr+4*nq)
    for sg,k,rel,f in ent:
        if k=='K':
            rows.append(n);cols.append(384+rel*8+f);vals.append(sg*ph/24)
            rows.append(n);cols.append(448+rel*8+f);vals.append(sg*(24-ph)/24)
        else:
            rows.append(n);cols.append(k*64+rel*8+f);vals.append(sg)
    y.append(sc-hce); n+=1
F=sp.csr_matrix((vals,(rows,cols)),shape=(n,512)); y=np.array(y,float)
rng=np.random.default_rng(0); idx=rng.permutation(n); te=idx[:50000]; tr=idx[50000:]
def solve(rows_, lam):
    A=F[rows_]; M=(A.T@A).toarray()+lam*np.eye(512); b=A.T@y[rows_]
    return np.linalg.solve(M,b)
d=solve(tr,LAM)
def rmse(rs,dd): r=y[rs]-F[rs]@dd; return float(np.sqrt(np.mean(np.clip(r,-600,600)**2)))
print("positions",n,"holdout rmse before %.1f after %.1f"%(rmse(te,np.zeros(512)),rmse(te,d)))
d=solve(np.arange(n),LAM)
np.save(out,d)
print("mean |delta| %.1f max %.1f"%(np.abs(d).mean(),np.abs(d).max()))
