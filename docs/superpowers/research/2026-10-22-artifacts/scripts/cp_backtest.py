import pandas as pd, numpy as np
from cp_core import *
pd.set_option('display.width',250)
CORR=['Hormuz','RedSea','Panama','Malacca','Taiwan','Gibraltar','Dover','Bosporus']
w=wide('n_total'); cap=wide('capacity'); capt=wide('capacity_tanker')
def corridor_ratios(base_fn, win=7):
    r=ratio(w, base_fn(w), win)
    r['RedSea']=r[['BabM','Suez']].mean(axis=1)
    return r
# weights from 2022-01..2023-10 tonnage
b=slice('2022-01-01','2023-10-31')
def corr_mean(df):
    m=df.loc[b].mean(); m['RedSea']=m[['BabM','Suez']].mean(); return m[CORR]
ton=corr_mean(cap); tank=corr_mean(capt); nont=ton-tank
W={'ton':ton/ton.sum(), 'split':0.5*tank/tank.sum()+0.5*nont/nont.sum(), 'eq':pd.Series(1/len(CORR),index=CORR)}
DB=0.90
def corr_scores(r): return (r[CORR]/DB).clip(upper=1.0).clip(lower=0)  # share of normal, deadband
def agg_mean(s,wt): return 100*(s*wt).sum(axis=1,min_count=len(CORR))
def agg_k(s,wt,k=3): return (100-100*k*((1-s)*wt).sum(axis=1,min_count=len(CORR))).clip(lower=0)
def agg_mix(s,wt): return 0.5*agg_mean(s,wt)+0.5*100*s.min(axis=1)
if __name__=='__main__':
    print('weights'); print(pd.DataFrame(W).round(3).to_string())
    pd.DataFrame(W).to_csv('out_weights.csv')
