"""Bank of Korea ECOS via the public 'sample' key (10 rows per call). Production needs a free key."""
import json, sys, time, urllib.request
BASE = "https://ecos.bok.or.kr/api"
def get(path):
    for _ in range(3):
        try:
            return json.load(urllib.request.urlopen(f"{BASE}/{path}", timeout=30))
        except Exception as e:
            time.sleep(2)
    raise RuntimeError(path)
def paged(svc, tail, key):
    out, s = [], 1
    while True:
        d = get(f"{svc}/sample/json/en/{s}/{s+9}/{tail}")
        if svc not in d: break
        rows = d[svc]["row"]; out += rows
        if s + 9 >= d[svc]["list_total_count"]: break
        s += 10; time.sleep(0.15)
    return out
if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "items":
        rows = paged("StatisticItemList", sys.argv[2], None)
        json.dump(rows, open(sys.argv[3], "w"))
        print(len(rows))
