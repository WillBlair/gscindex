
import math

from flask import Blueprint, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from config import CATEGORY_WEIGHTS, METHODOLOGY_VERSION
from data.providers.chokepoints import CREDIT as PORTWATCH_CREDIT
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

def _score(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return round(float(value), 1)


def category_objects(data: dict) -> dict:
    """One object per category: the weighted ones (an excluded one has score None), then any
    other scored category (industry profiles, weight None).

    ``as_of`` is the date of the oldest input used. A category serving its last stored
    score has ``as_of`` None and ``stored_on`` set to the date that score was stored.
    """
    scores = data.get("current_scores") or {}
    metadata = data.get("category_metadata") or {}
    out = {}
    for cat in list(CATEGORY_WEIGHTS) + [c for c in scores if c not in CATEGORY_WEIGHTS]:
        meta = metadata.get(cat) or {}
        out[cat] = {
            "score": _score(scores.get(cat)),
            "weight": CATEGORY_WEIGHTS.get(cat),
            "as_of": meta.get("as_of"),
            "stored_on": meta.get("stored_on"),
            "source": meta.get("source"),
            "is_stale": bool(meta.get("is_stale", False)),
            "is_fallback": bool(meta.get("is_fallback", False)),
            "inputs": [{**i, "score": _score(i.get("score"))}
                       for i in meta.get("inputs") or [] if isinstance(i, dict)],
        }
    return out


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
        
    # Heavy internal structures ('category_history', 'dates') are left out.
    composite = snapshot_composite(data)
    response = {
        "methodology_version": METHODOLOGY_VERSION,
        # Actual snapshot time, not midnight of the final history date.
        "timestamp": data.get("last_updated_utc"),
        # The composite stored with the snapshot (weights renormalized over the present
        # categories); computed only for an old snapshot without one.
        "composite_index": round(composite, 1) if composite is not None else None,
        "categories": category_objects(data),
        # Degradation flags. Fallback categories serve their last stored reading (not a
        # measurement this cycle); excluded categories have no recent reading and are left
        # out of the composite; stale categories rest on an input past its freshness window.
        "degraded": bool(data.get("degraded", False)),
        "fallback_categories": data.get("fallback_categories", []),
        "excluded_categories": data.get("excluded_categories", []),
        "stale_categories": data.get("stale_categories", []),
        "disruptions": data.get("disruptions", []),
        "map_markers": data.get("map_markers", []),
        "meta": {
            "source": "Global Supply Chain Index",
            "license": "CC-BY-4.0",
            "documentation": "https://gscindex.com/docs",
            # Required attribution for the PortWatch data (chokepoints, and the port-call
            # shares behind Physical Disruption). Every other source is listed in /docs.
            "credits": [PORTWATCH_CREDIT],
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
