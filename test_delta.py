from data.cache import get_cached_dashboard
from scoring.engine import compute_composite_index

data = get_cached_dashboard()
if not data:
    print("No cached data found")
else:
    current_scores = data["current_scores"]
    category_history = data["category_history"]
    
    composite = compute_composite_index(current_scores)
    
    yesterday_scores = {
        cat: float(series.iloc[-2] if len(series) > 1 else series.iloc[-1])
        for cat, series in category_history.items()
    }
    composite_yesterday = compute_composite_index(yesterday_scores)
    delta = round(composite - composite_yesterday, 1)
    
    print(f"Composite: {composite}")
    print(f"Composite Yesterday: {composite_yesterday}")
    print(f"Delta: {delta}")
    
    print("\n--- History Tail ---")
    for cat, series in category_history.items():
        print(f"\n[{cat}] Current: {current_scores[cat]}")
        print(series.tail(3))
