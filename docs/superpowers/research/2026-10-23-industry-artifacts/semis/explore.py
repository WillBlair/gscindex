import pandas as pd, numpy as np, pathlib
D = pathlib.Path(__file__).resolve().parent.parent / "data"
def s(name):
    d = pd.read_csv(D / f"{name}.csv", parse_dates=["date"]).set_index("date")["value"].astype(float)
    return d.resample("MS").mean()
S = {k: s(k) for k in ["fred_CAPUTLG3344S","fred_IPG3344S","fred_CAPG3344S","fred_PCU334413334413","fred_PCU3344133344131","fred_IR21320","fred_IQ21320","fred_ID8542","fred_A34SUO","fred_A34SVS","fred_A34HTI","fred_A34HNO","ecos_dram_xpi_usd","ecos_flash_xpi_usd","ecos_syssemi_xpi_usd","ecos_ic_export_volume","ecos_ic_xpi_usd","fred_PCU333242333242"]}
T = pd.DataFrame()
for k, v in S.items():
    short = k.split("_",1)[1]
    if short in ("CAPUTLG3344S",): T[short] = v
    else: T[short+"_yoy"] = (v / v.shift(12) - 1) * 100
T["UO/VS"] = S["fred_A34SUO"] / S["fred_A34SVS"]
T["HTI/VS"] = S["fred_A34HTI"] / S["fred_A34SVS"]
dates = ["2018-06","2019-06","2020-06","2021-06","2021-12","2022-06","2022-12","2023-03","2023-09","2024-06","2025-06","2025-12","2026-06","2026-08","2026-09"]
pd.set_option("display.width", 250)
print(T.loc[[pd.Timestamp(d) for d in dates]].round(1).T.to_string())
T.to_csv(D / "explore_transformed.csv")
