"""Shared loaders for the energy/inputs research. Reads only files in raw/."""
from pathlib import Path
import pandas as pd
import numpy as np

RAW = Path(__file__).parent / "raw"


def fred(sid: str) -> pd.Series:
    d = pd.read_csv(RAW / f"{sid}.csv")
    d.columns = ["date", "v"]
    d["date"] = pd.to_datetime(d["date"])
    d["v"] = pd.to_numeric(d["v"], errors="coerce")
    s = d.dropna().set_index("date")["v"].sort_index()
    s = s[s > 0] if sid not in NONPOS_OK else s
    return s.rename(sid)


NONPOS_OK = {"DTCDFSA066MSFRBPHI", "PPCDFSA066MSFRBPHI", "GACDFSA066MSFRBPHI",
             "DTCDISA066MSFRBNY", "PPCDISA066MSFRBNY", "GACDISA066MSFRBNY",
             "DTMSAMFRBDAL", "PRMSAMFRBDAL", "BACTSAMFRBDAL"}


def yf(tk: str) -> pd.Series:
    d = pd.read_csv(RAW / f"yf_{tk.replace('=', '_')}.csv")
    d.columns = ["date", "v"]
    d["date"] = pd.to_datetime(d["date"].str[:10])
    s = d.set_index("date")["v"].astype(float)
    s = s[s > 0]
    return s[~s.index.duplicated(keep="last")].sort_index().rename(tk)


def cpi_daily(index: pd.DatetimeIndex) -> pd.Series:
    """CPIAUCSL for each date's month; months past the last print use the last print."""
    cpi = fred("CPIAUCSL")
    m = cpi.reindex(pd.date_range(cpi.index[0], index.max(), freq="MS")).ffill()
    per = index.to_period("M").to_timestamp()
    return pd.Series(m.reindex(per).to_numpy(), index=index)


def real(s: pd.Series) -> pd.Series:
    """Price in latest-CPI dollars (Sep 2026 CPI = last available print)."""
    cpi = fred("CPIAUCSL")
    base = cpi.iloc[-1]
    return s * base / cpi_daily(s.index)
