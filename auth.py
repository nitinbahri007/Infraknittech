import jwt
import bcrypt
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
from db import get_db_connection

auth_bp = Blueprint("auth_bp", __name__)

# =========================
# CONFIG
# =========================
JWT_SECRET      = "your-secret-key-change-this"  # production mein env variable use karo
JWT_EXPIRY_MINS = 60  # 1 hour
REFRESH_EXPIRY_DAYS = 7

# =========================
# HELPERS
# =========================
def generate_token(user_id, username, role, expiry_mins=JWT_EXPIRY_MINS):
    payload = {
        "user_id"  : user_id,
        "username" : username,
        "role"     : role,
        "exp"      : datetime.utcnow() + timedelta(minutes=expiry_mins),
        "iat"      : datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def verify_token(token):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def get_token_from_header():
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


# =========================
# POST /api/auth/login
# Body: { username, password }
# =========================
@auth_bp.route("/api/auth/login", methods=["POST"])
def login():
    data     = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({"error": "username and password required"}), 400

    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT id, username, email, password, role, is_active
            FROM users WHERE username = %s
        """, (username,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if not user:
            return jsonify({"error": "Invalid username or password"}), 401

        if not user["is_active"]:
            return jsonify({"error": "Account is inactive"}), 403

        # Password check
        if not bcrypt.checkpw(password.encode("utf-8"), user["password"].encode("utf-8")):
            return jsonify({"error": "Invalid username or password"}), 401

        # Generate tokens
        access_token  = generate_token(user["id"], user["username"], user["role"])
        refresh_token = generate_token(
            user["id"], user["username"], user["role"],
            expiry_mins=REFRESH_EXPIRY_DAYS * 24 * 60
        )

        # Save refresh token in DB
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE users
            SET refresh_token = %s, last_login = NOW(), updated_at = NOW()
            WHERE id = %s
        """, (refresh_token, user["id"]))
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({
            "status"        : "ok",
            "access_token"  : access_token,
            "refresh_token" : refresh_token,
            "expires_in"    : JWT_EXPIRY_MINS * 60,
            "user"          : {
                "id"       : user["id"],
                "username" : user["username"],
                "email"    : user["email"],
                "role"     : user["role"]
            }
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =========================
# POST /api/auth/refresh
# Body: { refresh_token }
# =========================
@auth_bp.route("/api/auth/refresh", methods=["POST"])
def refresh():
    data          = request.json or {}
    refresh_token = data.get("refresh_token", "")

    if not refresh_token:
        return jsonify({"error": "refresh_token required"}), 400

    payload = verify_token(refresh_token)
    if not payload:
        return jsonify({"error": "Invalid or expired refresh token"}), 401

    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT id, username, role, is_active, refresh_token
            FROM users WHERE id = %s
        """, (payload["user_id"],))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if not user or user["refresh_token"] != refresh_token:
            return jsonify({"error": "Invalid refresh token"}), 401

        if not user["is_active"]:
            return jsonify({"error": "Account is inactive"}), 403

        # New access token
        new_access_token = generate_token(user["id"], user["username"], user["role"])

        return jsonify({
            "status"       : "ok",
            "access_token" : new_access_token,
            "expires_in"   : JWT_EXPIRY_MINS * 60
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =========================
# POST /api/auth/logout
# Header: Authorization: Bearer <token>
# =========================
@auth_bp.route("/api/auth/logout", methods=["POST"])
def logout():
    token = get_token_from_header()
    if not token:
        return jsonify({"error": "Authorization header required"}), 401

    payload = verify_token(token)
    if not payload:
        return jsonify({"error": "Invalid token"}), 401

    try:
        # Clear refresh token from DB
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE users SET refresh_token = NULL, updated_at = NOW()
            WHERE id = %s
        """, (payload["user_id"],))
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"status": "logged out"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =========================
# GET /api/auth/me
# Header: Authorization: Bearer <token>
# Returns current user info
# =========================
@auth_bp.route("/api/auth/me", methods=["GET"])
def me():
    token = get_token_from_header()
    if not token:
        return jsonify({"error": "Authorization header required"}), 401

    payload = verify_token(token)
    if not payload:
        return jsonify({"error": "Invalid or expired token"}), 401

    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT id, username, email, role, is_active, last_login, created_at
            FROM users WHERE id = %s
        """, (payload["user_id"],))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if not user:
            return jsonify({"error": "User not found"}), 404

        # Get permissions
        from user_management import get_user_permissions
        permissions = get_user_permissions(user["id"], user["role"])

        return jsonify({
            "id"          : user["id"],
            "username"    : user["username"],
            "email"       : user["email"],
            "role"        : user["role"],
            "is_active"   : user["is_active"],
            "permissions" : permissions,
            "last_login"  : str(user["last_login"]) if user["last_login"] else None,
            "created_at"  : str(user["created_at"])
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
