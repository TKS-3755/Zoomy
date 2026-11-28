import numpy as np, sys
from scipy.optimize import minimize
a=np.load('f0.npz'); b=np.load('f1.npz')
F=np.vstack([a['F'],b['F']]); ph=np.concatenate([a['ph'],b['ph']]); res=np.concatenate([a['res'],b['res']])
hce=np.concatenate([a['hce'],b['hce']]).astype(float); sc=np.concatenate([a['sc'],b['sc']]).astype(float); stm=np.concatenate([a['stm'],b['stm']])
keep=(np.abs(hce)<1500)&(np.abs(sc)<2000)
F,ph,res,hce,sc,stm=F[keep],ph[keep],res[keep],hce[keep],sc[keep],stm[keep]
n=len(res); print("n",n)
NFt=F.shape[1]
F=np.hstack([F,stm[:,None].astype(float)])      # tempo as feature 34
names="n_outpost b_outpost b_bad minor_supp rook_doubled pass_free pass_blocked pass_kdist phalanx pawn_chain backward isl shield storm king_openfile king_adjopen rook_vs_k space thr_pawn thr_hang queen_att imb_N imb_R imb_B n_pair QxMinors kingzone_att rook_pair pass_cnt adv_supp central dev_back kzone_attacked_own pawn_cnt kzone_union tempo".split()
assert len(names)==F.shape[1],(len(names),F.shape)
mg=(ph/24.0)[:,None]; eg=((24-ph)/24.0)[:,None]
G=np.hstack([F*mg,F*eg])
sd=G.std(0)+1e-9; Gs=G/sd
rng=np.random.default_rng(0); idx=rng.permutation(n); te=idx[:n//5]; tr=idx[n//5:]
def sig(x): return 1/(1+np.exp(-x))
def loss_fn(w,rows,S,lam,cols=None):
    z=(hce[rows]+ (Gs[rows][:,cols]@w if cols is not None else Gs[rows]@w))/S
    p=np.clip(sig(z),1e-9,1-1e-9); r=res[rows]
    l=-(r*np.log(p)+(1-r)*np.log(1-p)).mean()+lam*np.sum(w*w)
    g=((p-r)/S)@(Gs[rows][:,cols] if cols is not None else Gs[rows])/len(rows)+2*lam*w
    return l,g
# scale S
best=None
for S in (150,200,250,300,400,500,700):
    l,_=loss_fn(np.zeros(0),tr,S,0,cols=[]) if False else (None,None)
bs=None
for S in (150,200,250,300,400,500,700):
    z=hce[tr]/S; p=np.clip(sig(z),1e-9,1-1e-9); l=-(res[tr]*np.log(p)+(1-res[tr])*np.log(1-p)).mean()
    if bs is None or l<bs[0]: bs=(l,S)
S=bs[1]; print("best S",S,"baseline train loss %.5f"%bs[0])
def hold(w,cols=None):
    l,_=loss_fn(w,te,S,0,cols); return l
base=hold(np.zeros(Gs.shape[1]) if cols is None else None) if False else None
z=hce[te]/S; p=np.clip(sig(z),1e-9,1-1e-9); base=-(res[te]*np.log(p)+(1-res[te])*np.log(1-p)).mean()
print("holdout baseline %.5f"%base)
lam=1e-6
r=minimize(lambda w:loss_fn(w,tr,S,lam),np.zeros(Gs.shape[1]),jac=True,method='L-BFGS-B',options={'maxiter':300})
w=r.x; print("holdout with all terms %.5f  (gain %.5f)"%(hold(w),base-hold(w)))
# per feature ablation: set mg and eg weights to zero
K=F.shape[1]
rows=[]
for k in range(K):
    w2=w.copy(); w2[k]=0; w2[K+k]=0
    rows.append((hold(w2)-hold(w),names[k],w[k]/sd[k],w[K+k]/sd[K+k]))
rows.sort(reverse=True)
print("feature, loss increase when removed (x1e5), mg weight cp, eg weight cp")
for d,nm,wm,we in rows: print("%-16s %7.1f  mg %7.2f  eg %7.2f"%(nm,d*1e5,wm,we))
np.save("w_all.npy",np.stack([w[:K]/sd[:K],w[K:]/sd[K:]]))
