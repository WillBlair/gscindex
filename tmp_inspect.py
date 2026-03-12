import json
from data import aggregate_data
from data.status import set_status

data = aggregate_data(status_callback=set_status)
if "category_metadata" in data and "supply_chain" in data["category_metadata"]:
    # The map uses category metadata or some location feed?
    pass

# We can just look at how map_markers is built in layout.py or app.py
