
from flask import Blueprint, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from scoring import snapshot_composite

# Create Blueprint
api_bp = Blueprint('api', __name__, url_prefix='/api/v1')

API_RATE_LIMIT = "500 per hour;2000 per day"


def client_ip() -> str:
    """Visitor IP behind Render's Cloudflare edge.

    request.remote_addr is the proxy, which put every visitor in one shared
    bucket. Cloudflare sets CF-Connecting-IP itself (clients cannot spoof it
    through the edge); fall back to the socket address when it is absent.
    """
    return request.headers.get("CF-Connecting-IP") or get_remote_address()


def get_limiter(app):
    """Limiter keyed on the real visitor IP.

    No default limits: Dash's own page and callback requests are not rate
    limited. Limits are applied to the API blueprints in app.py.
    """
    return Limiter(client_ip, app=app, storage_uri="memory://")

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
    composite = snapshot_composite(data)
    response = {
        # Actual snapshot time, not midnight of the final history date.
        "timestamp": data.get("last_updated_utc"),
        "composite_index": round(composite, 1) if composite is not None else None,
        "categories": current_scores,
        # Degradation flags: categories listed here are serving a neutral
        # fallback value (provider failure), not a measurement.
        "degraded": bool(data.get("degraded", False)),
        "fallback_categories": data.get("fallback_categories", []),
        "disruptions": data.get("disruptions", []),
        "map_markers": data.get("map_markers", []),
        "meta": {
            "source": "Global Supply Chain Index",
            "license": "CC-BY-4.0",
            "documentation": "https://gscindex.com/docs"
        }
    }
    
    return jsonify(response), 200


@api_bp.route('/newsletter-data', methods=['GET'])
def get_newsletter_data():
    """Return dashboard snapshot for the newsletter cron job.

    Protected by ADMIN_TOKEN to prevent public access to the full briefing text.
    The cron job sends ``Authorization: Bearer <ADMIN_TOKEN>``.
    """
    from api.admin import verify_admin

    if not verify_admin():
        return jsonify({"error": "Unauthorized"}), 401

    from data.cache import get_cached_dashboard

    data = get_cached_dashboard()
    if not data:
        return jsonify({"error": "No cached data available"}), 503

    current_scores = data.get("current_scores", {})
    composite = snapshot_composite(data)
    return jsonify({
        "current_scores": current_scores,
        "briefing": data.get("briefing", ""),
        "composite_index": round(composite, 1) if composite is not None else None,
    }), 200
