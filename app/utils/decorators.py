from functools import wraps
from flask import abort
from flask_login import current_user


def role_required(*roles):
    """Restrict access to specific roles."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if current_user.role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def admin_required(f):
    return role_required("admin")(f)


def write_required(f):
    """Admin and operatore can write; consulente is read-only."""
    return role_required("admin", "operatore")(f)
