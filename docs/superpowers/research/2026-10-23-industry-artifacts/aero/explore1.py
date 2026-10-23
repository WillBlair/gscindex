import sys; sys.path.insert(0, sys.argv[1])
from load import s, yoy
import pandas as pd
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)
d = pd.DataFrame({
 "NO": s("ANAPNO"), "VS": s("ANAPVS"), "UO": s("ANAPUO"), "TI": s("ANAPTI"),
 "dVS": s("ADAPVS"), "dUO": s("ADAPUO"), "dTI": s("ADAPTI"),
 "IP": s("IPG3364S"), "CU": s("CAPUTLG3364T9S"),
})
d["bk_m"] = d.UO / d.VS
d["is"] = d.TI / d.VS
d["d_bk_m"] = d.dUO / d.dVS
d["d_is"] = d.dTI / d.dVS
d["VSyoy"] = yoy(d.VS.rolling(3).mean())
d["IPyoy"] = yoy(d.IP)
d["b2b12"] = d.NO.rolling(12).sum() / d.VS.rolling(12).sum()
dates = ["2007-06-01","2010-06-01","2015-06-01","2018-06-01","2019-03-01","2019-06-01","2019-12-01","2020-06-01","2021-06-01","2022-06-01","2023-09-01","2024-01-01","2024-10-01","2025-06-01","2026-03-01","2026-06-01","2026-08-01","2026-09-01"]
print(d.reindex(pd.to_datetime(dates)).round(2).to_string())
print(d[["bk_m","is","d_bk_m","d_is","CU","IP"]]["1992":"2019"].describe().round(2).to_string())
