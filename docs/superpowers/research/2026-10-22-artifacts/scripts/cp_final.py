from cp_backtest import *
# Recommended design: RedSea corridor = min(BabM, Suez); clean-years baseline; tonnage weights; deadband 0.90; k=3
r=ratio(w, baseline_clean_years(w), 7)
r['RedSea']=r[['BabM','Suez']].min(axis=1)
s=corr_scores(r)
wt=W['ton']
out=pd.DataFrame({'k3':agg_k(s,wt,3),'k2':agg_k(s,wt,2),'k4':agg_k(s,wt,4),'mix':agg_mix(s,wt),'mean':agg_mean(s,wt)})
out=out.join(r[CORR+['BabM','Suez','Cape']].add_prefix('ratio_'))
out.round(3).to_csv('out_final_daily.csv')
def ev(x):
    return {'calm22-23 mean':x.loc['2022-01-08':'2023-10-31'].mean(),'calm22-23 p5':x.loc['2022-01-08':'2023-10-31'].quantile(.05),
     '2020-21 mean':x.loc['2020-01-08':'2021-12-31'].mean(),
     'EverGiven min':x.loc['2021-03-23':'2021-04-10'].min(),'EverGiven date':x.loc['2021-03-23':'2021-04-10'].idxmin().date(),
     'Panama Dec23':x.loc['2023-11-15':'2023-12-14'].mean(),'RedSea Q1-24':x.loc['2024-01':'2024-03'].mean(),
     'RedSea 2024':x.loc['2024'].mean(),'2025':x.loc['2025'].mean(),'Feb-26':x.loc['2026-02'].mean(),
     'Hormuz Mar8-31':x.loc['2026-03-08':'2026-03-31'].mean(),'Apr-26':x.loc['2026-04'].mean(),'Jul-26':x.loc['2026-07'].mean(),
     'today 10-18':x.loc['2026-10-18'],'min':x.min(),'min date':x.idxmin().date()}
pd.set_option('display.width',300)
T=pd.DataFrame({c:ev(out[c]) for c in ['mean','k2','k3','k4','mix']}).T
print(T.to_string()); T.to_csv('out_final_summary.csv')
print(out['k3'].loc['2021-03-20':'2021-04-08'].round(1).to_string())
print(out['k3'].loc['2023-12-01':'2024-01-31'].resample('W').last().round(1).to_string())
q=out[['k3','mix','mean']].resample('QE').mean().round(1); print(q.to_string())
