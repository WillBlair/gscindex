"""Pull full daily chokepoint transit history from IMF PortWatch (public ArcGIS)."""
import json, sys, urllib.request, urllib.parse
import pandas as pd

URL = ("https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/"
       "Daily_Chokepoints_Data/FeatureServer/0/query")
IDS = {"chokepoint6": "Hormuz", "chokepoint4": "Bab el-Mandeb", "chokepoint1": "Suez",
       "chokepoint2": "Panama", "chokepoint5": "Malacca", "chokepoint7": "Cape of Good Hope",
       "chokepoint11": "Taiwan Strait", "chokepoint8": "Gibraltar"}
rows = []
for pid in IDS:
    offset = 0
    while True:
        q = {"where": f"portid='{pid}'", "outFields": "date,portid,n_total,n_tanker,n_container,capacity",
             "f": "json", "resultRecordCount": 2000, "resultOffset": offset, "orderByFields": "date"}
        with urllib.request.urlopen(URL + "?" + urllib.parse.urlencode(q), timeout=120) as r:
            body = json.load(r)
        feats = [f["attributes"] for f in body.get("features", [])]
        rows += feats
        if len(feats) < 2000 and not body.get("exceededTransferLimit"):
            break
        offset += len(feats)
    print(pid, IDS[pid], len(rows))
df = pd.DataFrame(rows)
df["date"] = pd.to_datetime(df["date"], unit="ms")
df["name"] = df.portid.map(IDS)
df.to_csv(sys.argv[1], index=False)
print(df.groupby("name").date.agg(["min", "max", "count"]))
