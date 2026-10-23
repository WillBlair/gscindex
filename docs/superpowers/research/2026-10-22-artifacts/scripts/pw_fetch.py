import requests, pandas as pd, sys, time
B="https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services"
def q(svc, where="1=1", fields="*", order="ObjectId", page=1000, extra=None):
    out=[]; off=0
    while True:
        p={"where":where,"outFields":fields,"f":"json","resultOffset":off,"resultRecordCount":page,"orderByFields":order,"returnGeometry":"false"}
        if extra: p.update(extra)
        for t in range(4):
            try:
                r=requests.get(f"{B}/{svc}/FeatureServer/0/query",params=p,timeout=60); r.raise_for_status(); j=r.json(); break
            except Exception as e:
                time.sleep(2)
        if "error" in j: raise RuntimeError(j["error"])
        feats=[f["attributes"] for f in j.get("features",[])]
        out+=feats
        if len(feats)<page and not j.get("exceededTransferLimit"): break
        off+=len(feats)
        if not feats: break
    return pd.DataFrame(out)
if __name__=="__main__":
    db=q("PortWatch_chokepoints_database", fields="portid,portname,vessel_count_total,vessel_count_container,vessel_count_dry_bulk,vessel_count_general_cargo,vessel_count_RoRo,vessel_count_tanker,industry_top1,industry_top2,industry_top3")
    db.to_csv("pw/chokepoints_db.csv",index=False); print(db.to_string())
    d=q("Daily_Chokepoints_Data", fields="date,portid,portname,n_container,n_dry_bulk,n_general_cargo,n_roro,n_tanker,n_cargo,n_total,capacity_container,capacity_dry_bulk,capacity_tanker,capacity_cargo,capacity", page=1000)
    d["date"]=pd.to_datetime(d["date"],unit="ms")
    d.to_csv("pw/chokepoints_daily.csv",index=False)
    print(len(d), d.date.min(), d.date.max())
