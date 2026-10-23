import pandas as pd
from pw_fetch import q
ports={"port664":"LA-LB","port815":"NY-NJ","port1170":"Savannah","port1188":"Shanghai","port1201":"Singapore","port1114":"Rotterdam","port824":"Ningbo","port744":"Jebel Ali"}
ids=",".join(f"'{p}'" for p in ports)
d=q("Daily_Ports_Data", where=f"portid IN ({ids})", fields="date,portid,portname,portcalls_container,portcalls_cargo,portcalls,import_container,import,export_container,export")
d["date"]=pd.to_datetime(d["date"],unit="ms")
d.to_csv("pw/ports_daily_major.csv",index=False)
print(d.groupby("portname").date.agg(["min","max","count"]))
w=q("Daily_Trade_Data_WLD", fields="*")
w["date"]=pd.to_datetime(w["date"],unit="ms"); print("WLD", w.date.min(), w.date.max(), len(w))
cm=q("Container_Metrics", fields="date_in,metric,port664,port1188,port1201")
print(cm.metric.value_counts()); 
cm["date_in"]=pd.to_datetime(cm["date_in"],unit="ms"); print(cm.date_in.min(), cm.date_in.max()); print(cm.tail(8).to_string())
cm.to_csv("pw/container_metrics_sample.csv",index=False)
dis=q("portwatch_disruptions_database", fields="eventid,eventtype,eventname,alertlevel,country,fromdate,todate,n_affectedports", order="fromdate")
for c in ["fromdate","todate"]: dis[c]=pd.to_datetime(dis[c],unit="ms")
dis.to_csv("pw/disruptions.csv",index=False); print(dis.eventtype.value_counts()); print(dis.fromdate.min(), dis.fromdate.max()); print(dis.tail(10).to_string())
