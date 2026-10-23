"""Proposed semiconductor categories: equal-weight mean of input scores; latest = each input's latest month."""
import pandas as pd, pathlib
D = pathlib.Path(__file__).resolve().parent.parent / "data"
sc = lambda k: pd.read_csv(D / f"scored_{k}.csv", index_col=0, parse_dates=True)["score"]
cats = {"chip_memory_prices": ["kr_dram_xpi_yoy", "kr_nand_xpi_yoy"],
        "chip_logic_prices": ["kr_syssemi_xpi_yoy", "us_semi_import_px_yoy"],
        "chip_fab_util": ["us_semi_util", "kr_semi_util_0519"]}
W = {"chip_memory_prices": 0.15, "chip_logic_prices": 0.10, "chip_fab_util": 0.15}
dates = ["2021-06", "2021-12", "2022-06", "2023-03", "2024-06"]
out = {}
for c, ins in cats.items():
    row = {d: sum(sc(i)[pd.Timestamp(d)] for i in ins) / len(ins) for d in dates}
    row["latest"] = sum(sc(i).iloc[-1] for i in ins) / len(ins)
    out[c] = row
T = pd.DataFrame(out).T
T.loc["semis block (0.15/0.10/0.15)"] = sum(T.loc[c] * w for c, w in W.items()) / sum(W.values())
print(T.round(0).to_string()); T.round(1).to_csv(D / "category_scores.csv")
