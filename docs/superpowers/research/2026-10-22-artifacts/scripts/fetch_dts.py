"""Pull daily customs deposits from the Daily Treasury Statement (fiscaldata API)."""
import json, sys, urllib.request, urllib.parse
import pandas as pd

OUT = sys.argv[1]
BASE = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/deposits_withdrawals_operating_cash"
NAMES = [
    "Customs and Certain Excise Taxes",
    "DHS - Customs and Certain Excise Taxes",
    "DHS - Customs Duties, Taxes, and Fees",
]
rows = []
for name in NAMES:
    page = 1
    while True:
        q = {
            "filter": f"transaction_catg:eq:{name},transaction_type:eq:Deposits",
            "fields": "record_date,transaction_catg,transaction_today_amt,transaction_mtd_amt,transaction_fytd_amt,account_type",
            "page[size]": "10000",
            "page[number]": str(page),
            "sort": "record_date",
        }
        url = BASE + "?" + urllib.parse.urlencode(q, safe=":,[]()")
        with urllib.request.urlopen(url, timeout=120) as r:
            d = json.load(r)
        rows += d["data"]
        if page >= d["meta"]["total-pages"]:
            break
        page += 1
    print(name, len(rows))
df = pd.DataFrame(rows)
for c in ["transaction_today_amt", "transaction_mtd_amt", "transaction_fytd_amt"]:
    df[c] = pd.to_numeric(df[c], errors="coerce")
df["record_date"] = pd.to_datetime(df["record_date"])
df = df.sort_values("record_date")
df.to_csv(OUT, index=False)
print(df.account_type.value_counts())
print(df.head(3)); print(df.tail(5))
