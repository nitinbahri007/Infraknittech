import bcrypt
from datetime import datetime
from functools import wraps
from flask import Blueprint, request, jsonify
from db import get_db_connection

api_bp = Blueprint("api_bp", __name__)

# =========================
# ROLES & PERMISSIONS
# =========================
ROLE_PERMISSIONS = {
    "admin": [
        "view_patches",
        "download_patches",
        "deploy_patches",
        "create_users",
        "manage_devices",
        "view_alerts"
    ],
    "operator": [
        "view_patches",
        "download_patches",
        "deploy_patches",
        "manage_devices",
        "view_alerts"
    ],
    "viewer": [
        "view_patches",
        "view_alerts"
    ]
}

def _get_custom_roles():
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute("SELECT role_name FROM roles")
        roles = [r[0] for r in cur.fetchall()]
        cur.close()
        conn.close()
        return roles
    except:
        return []

VALID_ROLES = list(ROLE_PERMISSIONS.keys()) + _get_custom_roles()
VALID_PERMISSIONS = [
    "view_patches",
    "download_patches",
    "deploy_patches",
    "create_users",
    "manage_devices",
    "view_alerts"
]

# =========================
# DB — CREATE TABLES
# =========================
def ensure_user_tables():
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()

        # users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id           INT AUTO_INCREMENT PRIMARY KEY,
                username     VARCHAR(100) UNIQUE NOT NULL,
                email        VARCHAR(200) UNIQUE NOT NULL,
                password     VARCHAR(255) NOT NULL,
                role         VARCHAR(50)  NOT NULL DEFAULT 'viewer',
                is_active    TINYINT(1)   NOT NULL DEFAULT 1,
                created_by   VARCHAR(100),
                created_at   DATETIME DEFAULT NOW(),
                updated_at   DATETIME DEFAULT NOW()
            )
        """)

        # user_permissions table (custom overrides per user)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_permissions (
                id           INT AUTO_INCREMENT PRIMARY KEY,
                user_id      INT NOT NULL,
                permission   VARCHAR(100) NOT NULL,
                granted      TINYINT(1) DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE KEY unique_user_perm (user_id, permission)
            )
        """)

        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"⚠️  user tables error: {e}")

ensure_user_tables()

# =========================
# HELPERS
# =========================
def hash_password(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def check_password(password, hashed):
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))

def get_user_permissions(user_id, role):
    """
    Role ke default permissions + user ke custom overrides merge karo
    """
    permissions = set(ROLE_PERMISSIONS.get(role, []))

    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT permission, granted FROM user_permissions
            WHERE user_id = %s
        """, (user_id,))
        overrides = cursor.fetchall()
        cursor.close()
        conn.close()

        for row in overrides:
            if row["granted"]:
                permissions.add(row["permission"])
            else:
                permissions.discard(row["permission"])

    except Exception as e:
        print(f"⚠️  get_user_permissions error: {e}")

    return list(permissions)

def require_permission(permission):
    """
    Decorator — API pe permission check karo
    Usage: @require_permission("deploy_patches")
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            # Header se user_id lo
            user_id = request.headers.get("X-User-Id")
            if not user_id:
                return jsonify({"error": "X-User-Id header required"}), 401

            try:
                conn   = get_db_connection()
                cursor = conn.cursor(dictionary=True)
                cursor.execute("""
                    SELECT id, role, is_active FROM users WHERE id = %s
                """, (user_id,))
                user = cursor.fetchone()
                cursor.close()
                conn.close()

                if not user:
                    return jsonify({"error": "User not found"}), 401

                if not user["is_active"]:
                    return jsonify({"error": "User is inactive"}), 403

                perms = get_user_permissions(user["id"], user["role"])
                if permission not in perms:
                    return jsonify({
                        "error"     : "Permission denied",
                        "required"  : permission,
                        "your_role" : user["role"]
                    }), 403

            except Exception as e:
                return jsonify({"error": str(e)}), 500

            return f(*args, **kwargs)
        return decorated
    return decorator


# =========================
# POST /api/users
# Create new user (only admin/users with create_users permission)
# Body: { username, email, password, role, permissions (optional) }
# =========================
@api_bp.route("/api/users", methods=["POST"])
def create_user():
    data     = request.json or {}
    username = data.get("username", "").strip()
    email    = data.get("email", "").strip()
    password = data.get("password", "").strip()
    role     = data.get("role", "viewer").strip().lower()
    custom_permissions = data.get("permissions", [])  # optional overrides
    created_by = data.get("created_by", "system")

    # Validate
    if not username or not email or not password:
        return jsonify({"error": "username, email, password required"}), 400

    if role not in VALID_ROLES:
        return jsonify({
            "error" : f"Invalid role '{role}'",
            "valid" : VALID_ROLES
        }), 400

    for perm in custom_permissions:
        if perm not in VALID_PERMISSIONS:
            return jsonify({
                "error" : f"Invalid permission '{perm}'",
                "valid" : VALID_PERMISSIONS
            }), 400

    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Check duplicate
        cursor.execute("""
            SELECT id FROM users WHERE username = %s OR email = %s
        """, (username, email))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({"error": "Username or email already exists"}), 409

        # Insert user
        hashed = hash_password(password)
        cursor.execute("""
            INSERT INTO users (username, email, password, role, created_by, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
        """, (username, email, hashed, role, created_by))

        user_id = cursor.lastrowid

        # Insert custom permission overrides if any
        for perm in custom_permissions:
            cursor.execute("""
                INSERT INTO user_permissions (user_id, permission, granted)
                VALUES (%s, %s, 1)
                ON DUPLICATE KEY UPDATE granted = 1
            """, (user_id, perm))

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({
            "status"      : "created",
            "user_id"     : user_id,
            "username"    : username,
            "email"       : email,
            "role"        : role,
            "permissions" : get_user_permissions(user_id, role)
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =========================
# GET /api/users
# List all users
# =========================
@api_bp.route("/api/users", methods=["GET"])
def list_users():
    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT id, username, email, role, is_active, created_by, created_at, updated_at
            FROM users
            ORDER BY created_at DESC
        """)
        users = cursor.fetchall()
        cursor.close()
        conn.close()

        for user in users:
            user["permissions"]  = get_user_permissions(user["id"], user["role"])
            user["created_at"]   = str(user["created_at"])
            user["updated_at"]   = str(user["updated_at"])

        return jsonify({"count": len(users), "users": users})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =========================
# GET /api/users/<user_id>
# Single user details
# =========================
@api_bp.route("/api/users/<int:user_id>", methods=["GET"])
def get_user(user_id):
    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT id, username, email, role, is_active, created_by, created_at, updated_at
            FROM users WHERE id = %s
        """, (user_id,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if not user:
            return jsonify({"error": "User not found"}), 404

        user["permissions"] = get_user_permissions(user["id"], user["role"])
        user["created_at"]  = str(user["created_at"])
        user["updated_at"]  = str(user["updated_at"])

        return jsonify(user)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =========================
# PUT /api/users/<user_id>
# Update user role / permissions / status
# Body: { role, permissions, is_active }
# =========================
@api_bp.route("/api/users/<int:user_id>", methods=["PUT"])
def update_user(user_id):
    data        = request.json or {}
    role        = data.get("role")
    permissions = data.get("permissions")   # list of permissions to set
    is_active   = data.get("is_active")

    if role and role not in VALID_ROLES:
        return jsonify({
            "error": f"Invalid role '{role}'",
            "valid": VALID_ROLES
        }), 400

    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT id, role FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        if not user:
            cursor.close()
            conn.close()
            return jsonify({"error": "User not found"}), 404

        # Update role
        if role:
            cursor.execute("""
                UPDATE users SET role = %s, updated_at = NOW() WHERE id = %s
            """, (role, user_id))

        # Update is_active
        if is_active is not None:
            cursor.execute("""
                UPDATE users SET is_active = %s, updated_at = NOW() WHERE id = %s
            """, (1 if is_active else 0, user_id))

        # Update custom permissions
        if permissions is not None:
            # Clear existing custom permissions
            cursor.execute("DELETE FROM user_permissions WHERE user_id = %s", (user_id,))
            # Insert new ones
            for perm in permissions:
                if perm in VALID_PERMISSIONS:
                    cursor.execute("""
                        INSERT INTO user_permissions (user_id, permission, granted)
                        VALUES (%s, %s, 1)
                    """, (user_id, perm))

        conn.commit()

        # Return updated user
        new_role = role or user["role"]
        final_perms = get_user_permissions(user_id, new_role)

        cursor.close()
        conn.close()

        return jsonify({
            "status"      : "updated",
            "user_id"     : user_id,
            "role"        : new_role,
            "permissions" : final_perms
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =========================
# DELETE /api/users/<user_id>
# Soft delete — is_active = 0
# =========================
@api_bp.route("/api/users/<int:user_id>", methods=["DELETE"])
def delete_user(user_id):
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE users SET is_active = 0, updated_at = NOW() WHERE id = %s
        """, (user_id,))
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"status": "deactivated", "user_id": user_id})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =========================
# GET /api/roles
# List all roles with their default permissions
# =========================
@api_bp.route("/api/roles", methods=["GET"])
def list_roles():
    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT r.id, r.role_name, r.description, r.created_at,
                   GROUP_CONCAT(rp.permission) as permissions
            FROM roles r
            LEFT JOIN role_permissions rp ON r.id = rp.role_id
            GROUP BY r.id
        """)
        custom_roles = cursor.fetchall()
        cursor.close()
        conn.close()

        # Custom roles from DB
        db_roles = []
        for row in custom_roles:
            db_roles.append({
                "id"          : row["id"],
                "role"        : row["role_name"],
                "description" : row["description"],
                "permissions" : row["permissions"].split(",") if row["permissions"] else [],
                "type"        : "custom",
                "created_at"  : str(row["created_at"])
            })

        # Default built-in roles
        builtin_roles = [
            {
                "role"        : role,
                "permissions" : perms,
                "type"        : "builtin"
            }
            for role, perms in ROLE_PERMISSIONS.items()
        ]

        return jsonify({
            "builtin_roles": builtin_roles,
            "custom_roles" : db_roles,
            "all_permissions": VALID_PERMISSIONS
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =========================
# POST /api/roles
# Create new custom role
# Body: { role_name, description, permissions[] }
# =========================
@api_bp.route("/api/roles", methods=["POST"])
def create_role():
    data        = request.json or {}
    role_name   = data.get("role_name", "").strip().lower()
    description = data.get("description", "")
    permissions = data.get("permissions", [])

    if not role_name:
        return jsonify({"error": "role_name required"}), 400

    # Cannot override builtin roles
    if role_name in VALID_ROLES:
        return jsonify({
            "error": f"'{role_name}' is a builtin role — choose different name"
        }), 400

    # Validate permissions
    invalid = [p for p in permissions if p not in VALID_PERMISSIONS]
    if invalid:
        return jsonify({
            "error"  : f"Invalid permissions: {invalid}",
            "valid"  : VALID_PERMISSIONS
        }), 400

    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Create roles table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS roles (
                id          INT AUTO_INCREMENT PRIMARY KEY,
                role_name   VARCHAR(100) UNIQUE NOT NULL,
                description TEXT,
                created_at  DATETIME DEFAULT NOW()
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS role_permissions (
                id          INT AUTO_INCREMENT PRIMARY KEY,
                role_id     INT NOT NULL,
                permission  VARCHAR(100) NOT NULL,
                FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
                UNIQUE KEY unique_role_perm (role_id, permission)
            )
        """)

        # Check duplicate
        cursor.execute("SELECT id FROM roles WHERE role_name = %s", (role_name,))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({"error": f"Role '{role_name}' already exists"}), 409

        # Insert role
        cursor.execute("""
            INSERT INTO roles (role_name, description, created_at)
            VALUES (%s, %s, NOW())
        """, (role_name, description))
        role_id = cursor.lastrowid

        # Insert permissions
        for perm in permissions:
            cursor.execute("""
                INSERT INTO role_permissions (role_id, permission)
                VALUES (%s, %s)
            """, (role_id, perm))

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({
            "status"      : "created",
            "role_id"     : role_id,
            "role_name"   : role_name,
            "description" : description,
            "permissions" : permissions
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =========================
# PUT /api/roles/<role_id>
# Update custom role permissions
# Body: { description, permissions[] }
# =========================
@api_bp.route("/api/roles/<int:role_id>", methods=["PUT"])
def update_role(role_id):
    data        = request.json or {}
    description = data.get("description")
    permissions = data.get("permissions")

    if permissions is not None:
        invalid = [p for p in permissions if p not in VALID_PERMISSIONS]
        if invalid:
            return jsonify({
                "error": f"Invalid permissions: {invalid}",
                "valid": VALID_PERMISSIONS
            }), 400

    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT id, role_name FROM roles WHERE id = %s", (role_id,))
        role = cursor.fetchone()
        if not role:
            cursor.close()
            conn.close()
            return jsonify({"error": "Role not found"}), 404

        if description is not None:
            cursor.execute("""
                UPDATE roles SET description = %s WHERE id = %s
            """, (description, role_id))

        if permissions is not None:
            cursor.execute("DELETE FROM role_permissions WHERE role_id = %s", (role_id,))
            for perm in permissions:
                cursor.execute("""
                    INSERT INTO role_permissions (role_id, permission)
                    VALUES (%s, %s)
                """, (role_id, perm))

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({
            "status"      : "updated",
            "role_id"     : role_id,
            "role_name"   : role["role_name"],
            "permissions" : permissions
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =========================
# DELETE /api/roles/<role_id>
# Delete custom role
# =========================
@api_bp.route("/api/roles/<int:role_id>", methods=["DELETE"])
def delete_role(role_id):
    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT role_name FROM roles WHERE id = %s", (role_id,))
        role = cursor.fetchone()
        if not role:
            cursor.close()
            conn.close()
            return jsonify({"error": "Role not found"}), 404

        cursor.execute("DELETE FROM roles WHERE id = %s", (role_id,))
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({
            "status"    : "deleted",
            "role_id"   : role_id,
            "role_name" : role["role_name"]
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =========================
# POST /api/users/check-permission
# Check if user has a specific permission
# Body: { user_id, permission }
# =========================
@api_bp.route("/api/users/check-permission", methods=["POST"])
def check_permission():
    data       = request.json or {}
    user_id    = data.get("user_id")
    permission = data.get("permission")

    if not user_id or not permission:
        return jsonify({"error": "user_id and permission required"}), 400

    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT role, is_active FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if not user:
            return jsonify({"error": "User not found"}), 404

        if not user["is_active"]:
            return jsonify({"error": "User is inactive", "allowed": False}), 403

        perms   = get_user_permissions(user_id, user["role"])
        allowed = permission in perms

        return jsonify({
            "user_id"    : user_id,
            "permission" : permission,
            "allowed"    : allowed,
            "role"       : user["role"]
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
