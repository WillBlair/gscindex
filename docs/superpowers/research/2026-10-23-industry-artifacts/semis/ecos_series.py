"""Fetch one ECOS monthly series with the public sample key (10 rows/call) -> data/ecos_<name>.csv"""
import sys, time, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from ecos import get
name, table, start, end, *items = sys.argv[1:]
tail = "/".join([table, "M", start, end] + items)
rows, s = [], 1
while True:
    d = get(f"StatisticSearch/sample/json/en/{s}/{s+9}/{tail}")
    if "StatisticSearch" not in d: print(d); break
    rows += d["StatisticSearch"]["row"]
    if s + 9 >= d["StatisticSearch"]["list_total_count"]: break
    s += 10; time.sleep(0.15)
out = pathlib.Path(__file__).resolve().parent.parent / "data" / f"ecos_{name}.csv"
out.write_text("date,value\n" + "\n".join(f"{r['TIME'][:4]}-{r['TIME'][4:]}-01,{r['DATA_VALUE']}" for r in rows))
print(name, len(rows), rows[0]["TIME"], rows[-1]["TIME"], rows[-1]["DATA_VALUE"], rows[-1]["ITEM_NAME1"], rows[-1].get("ITEM_NAME2"))
