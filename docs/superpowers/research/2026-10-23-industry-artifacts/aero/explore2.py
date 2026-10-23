import sys; sys.path.insert(0, sys.argv[1])
from load import s, yoy
import pandas as pd
pd.set_option("display.width", 250)
TI, VS = s("ANAPTI"), s("ANAPVS")
isr = TI / VS.rolling(3).mean()
tot = (s("ANAPTI")+s("ADAPTI")) / (s("ANAPVS")+s("ADAPVS")).rolling(3).mean()
cu = s("CAPUTLG3364T9S")
a = pd.DataFrame({"is_nd": isr, "is_tot": tot, "cu": cu, "ip": s("IPG3364S")}).resample("YE").agg(["mean","max"]).round(2)
print(a["1990":].to_string())
print("is_nd top months:", isr.sort_values(ascending=False).head(8).round(2).to_dict())
print("cu 1972-2019 min/median/95:", cu["1972":"2019"].quantile([0,.05,.5,.95,1]).round(1).to_dict(), "1948-2019:", cu[:"2019"].quantile([.05,.5,.95]).round(1).to_dict())
print("cu worst thru 2025:", cu[:"2025"].idxmin(), cu[:"2025"].min())
