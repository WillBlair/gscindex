import pandas as pd, numpy as np
D=pd.read_csv('pw/chokepoints_daily.csv',parse_dates=['date'])
SHORT={'Strait of Hormuz':'Hormuz','Bab el-Mandeb Strait':'BabM','Suez Canal':'Suez','Panama Canal':'Panama','Malacca Strait':'Malacca','Taiwan Strait':'Taiwan','Gibraltar Strait':'Gibraltar','Cape of Good Hope':'Cape','Dover Strait':'Dover','Bosporus Strait':'Bosporus','Korea Strait':'Korea'}
def wide(field='n_total'):
    d=D[D.portname.isin(SHORT)].copy(); d['k']=d.portname.map(SHORT)
    return d.pivot(index='date',columns='k',values=field).asfreq('D')
def baseline_fixed(w, start='2022-01-01', end='2023-10-31'):
    b=w.loc[start:end]; m=b.groupby(b.index.month).mean()
    return pd.DataFrame(m.loc[w.index.month].values, index=w.index, columns=w.columns)
def baseline_clean_years(w, clean=(2019,2022,2023), clean_end='2023-10-31'):
    # same calendar month, mean of the most recent up-to-two clean years strictly before t's year
    ww=w[w.index<=clean_end]
    mm=ww.groupby([ww.index.year, ww.index.month]).mean()
    out=pd.DataFrame(index=w.index, columns=w.columns, dtype=float)
    for (y,mo),idx in w.groupby([w.index.year,w.index.month]).groups.items():
        yrs=[c for c in clean if c<y][-2:]
        rows=[mm.loc[(c,mo)] for c in yrs if (c,mo) in mm.index]
        if rows: out.loc[idx]=pd.concat(rows,axis=1).mean(axis=1).values
    return out
def baseline_pre2020(w): return baseline_fixed(w,'2019-01-01','2019-12-31')
def baseline_trailing(w):
    return w.rolling(365, min_periods=300).mean().shift(7)
def ratio(w, base, win=7):
    return w.rolling(win, min_periods=win).mean()/base
