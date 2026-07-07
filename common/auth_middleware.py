from functools import wraps
from flask import session, redirect, request, jsonify

def require_auth(f):
    """
    Decorator to protect routes. 
    Checks if a valid user session exists in Redis.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            # If it's an API request (expects JSON), return standard JSON envelope
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({
                    "success": False, 
                    "message": "Unauthorized. Please log in.", 
                    "data": None, 
                    "errors": ["No active session"]
                }), 401
            
            # If it's a normal web request, redirect to the Master Portal login
            return redirect('/login')
            
        return f(*args, **kwargs)
    return decorated_function