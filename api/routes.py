from flask import Blueprint, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from scoring import compute_composite_index

# Create Blueprint
api_bp = Blueprint('api', __name__, url_prefix='/api/v1')

def get_limiter(app):
    """Factory to create a limiter attached to the app."""
    return Limiter(
        get_remote_address,
        app=app,
        default_limits=["2000 per day", "500 per hour"],
        storage_uri="memory://"
    )

@api_bp.route('/latest', methods=['GET'])
def get_latest_data():
    """Return the cached dashboard snapshot as JSON."""
    from data.cache import get_cached_dashboard
    
    data = get_cached_dashboard()
    
    if not data:
        return jsonify({
            "error": "Data not available", 
            "message": "The system is warming up. Try again in 10 seconds."
        }), 503
        
    # Simplify the response for public consumption
    # We strip out heavy internal structures like 'category_history' and 'dates' 
    # to save bandwidth, unless requested? 
    # Actually, user asked "add this data to your project", so full snapshot is better.
    
    current_scores = data.get("current_scores", {})
    response = {
        "timestamp": data.get("dates", [])[-1] if data.get("dates") else None,
        "composite_index": round(compute_composite_index(current_scores), 1) if current_scores else None,
        "categories": current_scores,
        "disruptions": data.get("disruptions", []),
        "map_markers": data.get("map_markers", []),
        "meta": {
            "source": "Global Supply Chain Index",
            "license": "CC-BY-4.0",
            "documentation": "https://gscindex.com/docs"
        }
    }
    
    return jsonify(response), 200
