from flask import Blueprint, jsonify, request
import os
from data.database import get_connection, DB_TYPE

admin_bp = Blueprint('admin', __name__, url_prefix='/api/v1/admin')

def verify_admin():
    """Verify the request has the correct ADMIN_TOKEN."""
    token = os.environ.get("ADMIN_TOKEN")
    if not token:
        return False
        
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return False
        
    return auth_header.split(" ")[1] == token

@admin_bp.route('/subscribers', methods=['GET'])
def get_subscribers():
    """Return a list of all subscribers in the database."""
    if not verify_admin():
        return jsonify({"error": "Unauthorized"}), 401
        
    conn = get_connection()
    if not conn:
        return jsonify({"error": "Database not configured"}), 500
        
    try:
        cursor = conn.cursor()
        if DB_TYPE == "postgres":
            cursor.execute("SELECT id, email, subscribed_at, is_active FROM subscribers ORDER BY subscribed_at DESC")
        elif DB_TYPE == "sqlite":
            cursor.execute("SELECT id, email, subscribed_at, is_active FROM subscribers ORDER BY subscribed_at DESC")
            
        rows = cursor.fetchall()
        
        subscribers = []
        for row in rows:
            subscribers.append({
                "id": row[0],
                "email": row[1],
                "subscribed_at": row[2],
                "is_active": bool(row[3])
            })
            
        return jsonify({
            "count": len(subscribers),
            "subscribers": subscribers
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
