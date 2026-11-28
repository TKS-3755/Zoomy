import numpy as np, sys
from scipy.optimize import minimize
exec(open('fitfeat.py').read().split("lam=1e-6")[0])   # loads data, S, helpers
def fit(sel):
    cols=[names.index(x) for x in sel]; K=F.shape[1]
    cc=cols+[K+c for c in cols]
    r=minimize(lambda w:loss_fn(w,tr,S,1e-6,cols=cc),np.zeros(len(cc)),jac=True,method='L-BFGS-B',options={'maxiter':300})
    w=r.x; l,_=loss_fn(w,te,S,0,cols=cc)
    return base-l,{n:(round(w[i]/sd[cc[i]],1),round(w[len(cols)+i]/sd[cc[len(cols)+i]],1)) for i,n in enumerate(sel)}
S1="adv_supp space b_bad kzone_union rook_pair rook_doubled n_outpost b_outpost king_openfile king_adjopen dev_back n_pair".split()
g,w=fit(S1); print("S1 gain %.5f"%g); print(w)
S2=S1+["pass_kdist","backward","pass_cnt"]
g,w=fit(S2); print("S2 gain %.5f"%g); print(w)
S3="adv_supp space b_bad kzone_union rook_pair rook_doubled n_outpost b_outpost king_openfile king_adjopen dev_back n_pair pass_cnt".split()
g,w=fit(S3); print("S3 gain %.5f"%g); print({k:(int(round(float(a))),int(round(float(b)))) for k,(a,b) in w.items()})
