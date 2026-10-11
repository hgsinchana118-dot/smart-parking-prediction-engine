"""Users, password hashing and route guards."""
import re
from datetime import datetime
from functools import wraps

from flask import jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from db import get_db


def create_user(username, password, role="user"):
    if not re.fullmatch(r"[A-Za-z0-9_]{3,30}", username or ""):
        raise ValueError("Username must be 3-30 letters, digits or underscores")
    if len(password or "") < 6:
        raise ValueError("Password must be at least 6 characters")
    db = get_db()
    db.users.create_index("username", unique=True)
    if db.users.find_one({"username": username}):
        raise ValueError("Username already taken")
    db.users.insert_one({"username": username, "password_hash": generate_password_hash(password),
                         "role": role, "created_at": datetime.utcnow()})


def verify(username, password):
    u = get_db().users.find_one({"username": username})
    if u and check_password_hash(u["password_hash"], password or ""):
        return u
    return None


def ensure_admin(username, password):
    """Create the default admin if no admin exists. Returns True if created."""
    if get_db().users.find_one({"role": "admin"}):
        return False
    create_user(username, password, "admin")
    return True


def _deny(status, msg):
    if request.path.startswith("/api/"):
        return jsonify(error=msg), status
    return redirect(url_for("login"))


def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if "user" not in session:
            return _deny(401, "Please log in")
        return f(*a, **kw)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if "user" not in session:
            return _deny(401, "Please log in")
        if session.get("role") != "admin":
            return jsonify(error="Admin access required"), 403
        return f(*a, **kw)
    return wrapper
