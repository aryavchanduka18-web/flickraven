"""Multi-interest content profile: does clustering what a user liked beat one averaged taste vector?

    python -m pipeline.multi_interest_eval

Content source alone, established users with 12+ liked films (rated 7+), NDCG@10 against their later 7+ ratings over the
whole catalog. Variants: one averaged vector (the live rule), k-means into 2 or 3 interests scored by the best-matching
interest (max2, max3), and a weighted mixture of 3 (mix3). Result on 624 users (2026-11-10): single 0.0257, max2 0.0276,
max3 0.0285, mix3 0.0243; max3 minus single = +0.0028 with standard error 0.0026, i.e. no reliable gain, so the live
rule is unchanged. Kept so the test can be repeated when the content features improve (for example plot embeddings).
"""
import numpy as np, scipy.sparse as sp, json, sys
from sklearn.cluster import KMeans
from cinematch_engine.online import UserState
from pipeline.availability_calibration import build_engine, sample
e, movies, f = build_engine()
ml2row, hold, users, groups = sample(e, movies, f, 700)
cat=e.cat
def profile_single(liked, disliked):
    p = sp.csr_matrix((1, cat.content.shape[1]), dtype=np.float32)
    for group, sign in ((liked,1.0),(disliked,-1.0)):
        if group:
            rows,w=zip(*group); w=np.asarray(w,np.float32)/np.sum(w)
            p=p+sign*sp.csr_matrix(w[None,:])@cat.content[list(rows)]
    return p
def score_single(liked,disliked):
    return np.asarray((cat.content@profile_single(liked,disliked).T).todense()).ravel()
def score_multi(liked,disliked,kmax,mode):
    n=len(liked)
    k=min(kmax,n//4)
    if k<2: return score_single(liked,disliked)
    rows=[r for r,_ in liked]; w=np.array([x for _,x in liked],np.float32)
    X=cat.content[rows]
    lab=KMeans(k,n_init=3,random_state=0).fit_predict(X)
    S=np.zeros((cat.n,k),np.float32); mass=np.zeros(k)
    for c in range(k):
        m=lab==c
        if m.sum()==0: continue
        v=sp.csr_matrix((w[m]/w[m].sum())[None,:])@X[m]
        S[:,c]=np.asarray((cat.content@v.T).todense()).ravel(); mass[c]=w[m].sum()
    if mode=="max": s=S.max(1)
    else:
        a=(mass/mass.sum())**0.5; s=(S*a).sum(1)/a.sum()
    if disliked:
        rows,ww=zip(*disliked); ww=np.asarray(ww,np.float32)/np.sum(ww)
        neg=sp.csr_matrix(ww[None,:])@cat.content[list(rows)]
        s=s-np.asarray((cat.content@neg.T).todense()).ravel()
    return s
disc=1/np.log2(np.arange(2,12))
variants={"single":lambda l,d:score_single(l,d),"max2":lambda l,d:score_multi(l,d,2,"max"),"max3":lambda l,d:score_multi(l,d,3,"max"),"mix3":lambda l,d:score_multi(l,d,3,"mix")}
res={k:[] for k in variants}; used=0
for u in users:
    r=groups["train"].get_group(u)
    ratings={ml2row[int(a)]:float(b) for a,b in zip(r.ml_movie_id,r.rating) if int(a) in ml2row}
    liked=[(rw,v-6) for rw,v in ratings.items() if v>=7]; disliked=[(rw,6-v) for rw,v in ratings.items() if v<=5]
    if len(liked)<12: continue
    g=groups["test"].get_group(u); lab={ml2row[int(a)] for a,b in zip(g.ml_movie_id,g.rating) if b>=7 and int(a) in ml2row}
    if not lab: continue
    used+=1
    ex=np.array(list(ratings))
    for name,fn in variants.items():
        s=fn(liked,disliked).copy(); s[ex]=-np.inf; s[e.cat.non_movie_rows]=-np.inf
        top=np.argsort(-s)[:10]
        rel=np.array([x in lab for x in top],float)
        res[name].append((rel*disc).sum()/disc[:min(len(lab),10)].sum())
print("users",used,{k:round(float(np.mean(v)),4) for k,v in res.items()})
base=np.array(res["single"])
for k,v in res.items():
    d=np.array(v)-base
    if k!="single": print(k,"diff",round(float(d.mean()),4),"se",round(float(d.std()/np.sqrt(len(d))),4))
