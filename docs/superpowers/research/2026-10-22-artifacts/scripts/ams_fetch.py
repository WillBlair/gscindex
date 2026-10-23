import requests, pandas as pd
B="https://agtransport.usda.gov/resource/"
TODAY=pd.Timestamp('2026-10-22')
def q(ds, **p):
    p.setdefault('$limit',500000)
    r=requests.get(B+ds+".json",params=p,timeout=180)
    print(ds, r.status_code, r.url[:160])
    return pd.DataFrame(r.json())
out={}
# commodities in STB carloads
c=q('tb7q-kn5i',**{'$select':'commodity,count(*) as n','$group':'commodity'}); print(c.to_string())
out['reefer_rpm']=q('acar-e3r8',**{'$select':'date,avg(rpm) as avg_rpm,avg(availability) as avg_avail,count(*) as n','$group':'date','$order':'date'})
out['stb_carloads_orig']=q('tb7q-kn5i',**{'$select':'date,commodity,sum(carloads) as carloads','$where':"type='Originated'",'$group':'date,commodity','$order':'date'})
out['grain_cost_idx']=q('8uye-ieij',**{'$order':'date'})
out['barge_rates']=q('deqi-uken',**{'$order':'date'})
out['reefer_volumes']=q('rfpn-7etz',**{'$select':'tuesday_week_ending,sum(tenkunits) as tenkunits','$where':"mode='TRUCK'",'$group':'tuesday_week_ending','$order':'tuesday_week_ending'})
out['barge_moves']=q('w6ip-grsn',**{'$select':'date,type,direction,sum(barge_count) as barges','$group':'date,type,direction','$order':'date'})
for k,v in out.items(): v.to_csv(f"raw/ams_{k}.csv",index=False); print(k,len(v)); print(v.tail(3).to_string())
