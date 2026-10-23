import pandas as pd
from pathlib import Path
F = Path(__file__).resolve().parent.parent / "data" / "fred"
def s(sid):
    x = pd.read_csv(F / f"{sid}.csv", index_col=0, parse_dates=True)["value"].astype(float)
    return x.sort_index()
def yoy(x): return (x / x.shift(12) - 1) * 100
