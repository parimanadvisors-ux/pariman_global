import os
import redis
from flask import Flask, render_template, session, redirect, url_for, request, flash
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_session import Session
from flask_wtf.csrf import CSRFProtect

# Initialize extensions globally
db = SQLAlchemy()
migrate = Migrate()
sess = Session()
csrf = CSRFProtect()

def create_app():
    app = Flask(__name__)
    
    # 1. Trust Nginx proxy headers
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # 2. Security & Database Config
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fallback-dev-key')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # 3. Redis Session Config
    redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    app.config['SESSION_TYPE'] = 'redis'
    app.config['SESSION_PERMANENT'] = False
    app.config['SESSION_USE_SIGNER'] = True
    app.config['SESSION_KEY_PREFIX'] = 'pariman_session:'
    app.config['SESSION_REDIS'] = redis.from_url(redis_url)
    
    # Security flags for cookies 
    app.config['SESSION_COOKIE_SECURE'] = False 
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    # Initialize extensions with the app
    db.init_app(app)
    
    # IMPORT MODELS HERE
    with app.app_context():
        from models import User, Role, UserRole
        import models

    migrate.init_app(app, db)
    sess.init_app(app)
    csrf.init_app(app)

    # =========================================================================
    # Auth & Dashboard Routes
    # =========================================================================
    @app.route("/")
    def dashboard():
        if 'user_id' not in session:
            return redirect(url_for('login'))
        
        is_admin = session.get('email') == os.environ.get('ROOT_ADMIN_USER')
        email = session.get('email', '')
        user_name = email.split('@')[0].title() if email else 'Staff'

        return render_template("dashboard.html", user_name=user_name, is_admin=is_admin)

    @app.route("/login", methods=['GET', 'POST'])
    def login():
        if 'user_id' in session:
            return redirect(url_for('dashboard'))

        error = None
        if request.method == 'POST':
            email = request.form.get('email')
            password = request.form.get('password')
            
            user = User.query.filter_by(email=email).first()
            
            if user and user.is_active and check_password_hash(user.password_hash, password):
                session.clear()
                session['user_id'] = user.id
                session['email'] = user.email
                
                # Fetch role to save in session for quick frontend checks if needed
                user_role = UserRole.query.filter_by(user_id=user.id).first()
                if user_role:
                    role = Role.query.get(user_role.role_id)
                    session['role'] = role.name if role else 'Staff'
                else:
                    session['role'] = 'Staff'

                return redirect(url_for('dashboard'))
            else:
                error = "Invalid email or password, or account is disabled."

        return render_template("login.html", error=error)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for('login'))
        
    @app.route("/health")
    def health_check():
        return {"success": True, "message": "Portal Auth Service Healthy"}, 200

    # =========================================================================
    # Admin Staff Management Routes
    # =========================================================================
    def check_is_admin():
        if 'user_id' not in session or session.get('email') != os.environ.get('ROOT_ADMIN_USER'):
            return False
        return True

    @app.route("/admin/staff", methods=['GET'])
    def admin_staff_page():
        if not check_is_admin():
            return "Unauthorized Access. Admin only.", 403
            
        # Get all roles to populate the dropdown
        roles = Role.query.all()
        
        # Get all users and join with their primary role
        users_raw = db.session.query(User, Role).outerjoin(UserRole, User.id == UserRole.user_id).outerjoin(Role, UserRole.role_id == Role.id).all()
        
        users_list = []
        for u, r in users_raw:
            users_list.append({
                'id': u.id,
                'email': u.email,
                'is_active': u.is_active,
                'created_at': u.created_at,
                'role_name': r.name if r else 'No Role'
            })
            
        # Get flashed messages for feedback
        error = request.args.get('error')
        success = request.args.get('success')

        return render_template("staff_master.html", roles=roles, users=users_list, error=error, success=success)

    @app.route("/admin/staff/add", methods=['POST'])
    def admin_staff_add():
        if not check_is_admin():
            return "Unauthorized Access. Admin only.", 403
            
        email = request.form.get('email')
        password = request.form.get('password')
        role_id = request.form.get('role_id')
        
        if not email or not password or not role_id:
            return redirect(url_for('admin_staff_page', error="All fields are required."))
            
        # Check if user exists
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            return redirect(url_for('admin_staff_page', error="An account with that email already exists."))
            
        try:
            # Hash password and create user
            hashed_pw = generate_password_hash(password)
            new_user = User(email=email, password_hash=hashed_pw, is_active=True)
            db.session.add(new_user)
            db.session.flush() # get the ID without committing yet
            
            # Assign Role
            new_user_role = UserRole(user_id=new_user.id, role_id=role_id)
            db.session.add(new_user_role)
            
            db.session.commit()
            return redirect(url_for('admin_staff_page', success=f"Successfully created account for {email}"))
            
        except Exception as e:
            db.session.rollback()
            return redirect(url_for('admin_staff_page', error=f"Database error: {str(e)}"))

    @app.route("/admin/staff/toggle", methods=['POST'])
    def admin_staff_toggle():
        if not check_is_admin():
            return "Unauthorized Access. Admin only.", 403
            
        user_id = request.form.get('user_id')
        user = User.query.get(user_id)
        
        if not user:
            return redirect(url_for('admin_staff_page', error="User not found."))
            
        if user.email == os.environ.get('ROOT_ADMIN_USER'):
            return redirect(url_for('admin_staff_page', error="Cannot disable the Root Admin account."))
            
        try:
            user.is_active = not user.is_active
            db.session.commit()
            action = "enabled" if user.is_active else "disabled"
            return redirect(url_for('admin_staff_page', success=f"Successfully {action} {user.email}."))
            
        except Exception as e:
            db.session.rollback()
            return redirect(url_for('admin_staff_page', error=f"Database error: {str(e)}"))

    return app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)