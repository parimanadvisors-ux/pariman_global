import os
import sys
import json
from datetime import datetime
import redis

from flask import Flask, request, jsonify, session, render_template, abort
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import JSON as SA_JSON
from flask_session import Session
from flask_migrate import Migrate

# Allow importing from the shared 'common' directory
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
try:
    from common.auth_middleware import require_auth
except ImportError:
    # Fallback for local testing environment
    def require_auth(f):
        return f

# Initialize extensions
db = SQLAlchemy()
sess = Session()
migrate = Migrate()

def create_app():
    app = Flask(__name__)
    
    # 1. Trust Nginx proxy headers
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # 2. Redis Session Config (Must exactly match Master Portal)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fallback-dev-key')
    redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    app.config['SESSION_TYPE'] = 'redis'
    app.config['SESSION_PERMANENT'] = False
    app.config['SESSION_USE_SIGNER'] = True
    app.config['SESSION_KEY_PREFIX'] = 'pariman_session:'
    app.config['SESSION_REDIS'] = redis.from_url(redis_url)
    app.config['SESSION_COOKIE_SECURE'] = False # False for local HTTP testing
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    # Database setup
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}

    # Bind extensions
    db.init_app(app)
    sess.init_app(app)
    migrate.init_app(app, db)

    return app

app = create_app()

# ---------------------------------------------------------------------------
# Models - Scoped to 'policy' schema to prevent collisions
# ---------------------------------------------------------------------------
ID_STORES = ["users", "categories", "policies", "archives", "acceptances",
             "docViews", "videoViews", "monthlyCerts"]

class Record(db.Model):
    __tablename__ = "records"
    __table_args__ = (
        db.UniqueConstraint("store", "rec_id", name="uq_store_recid"),
        {"schema": "policy"}
    )
    pk = db.Column(db.Integer, primary_key=True)
    store = db.Column(db.String(32), nullable=False, index=True)
    rec_id = db.Column(db.Integer, nullable=False, index=True)
    data = db.Column(SA_JSON, nullable=False)

class Setting(db.Model):
    __tablename__ = "settings"
    __table_args__ = {"schema": "policy"}
    key = db.Column(db.String(64), primary_key=True)
    data = db.Column(SA_JSON, nullable=False)

def next_id(store):
    row = db.session.query(db.func.max(Record.rec_id)).filter(Record.store == store).scalar()
    return (row or 0) + 1

# ---------------------------------------------------------------------------
# Central Auth Bridge
# ---------------------------------------------------------------------------
@app.route("/api/me", methods=["GET"])
@require_auth
def me():
    # Return the master session user disguised as a local user for the frontend
    email = session.get("email", "admin@parimanglobal.com")
    name = email.split('@')[0].title()
    return jsonify({
        "id": 1,
        "username": email,
        "email": email,
        "name": name,
        "role": "admin",
        "designation": "Administrator"
    })

# ---------------------------------------------------------------------------
# Admin Import Routes
# ---------------------------------------------------------------------------
@app.route("/admin/import", methods=["GET"], strict_slashes=False)
@app.route("/policy/admin/import", methods=["GET"], strict_slashes=False)
@require_auth
def admin_import_page():
    is_admin = session.get('email') == os.environ.get('ROOT_ADMIN_USER')
    if not is_admin:
        return "Unauthorized Access. Admin only.", 403
    return render_template("admin_import.html")

@app.route("/admin/import", methods=["POST"], strict_slashes=False)
@app.route("/policy/admin/import", methods=["POST"], strict_slashes=False)
@require_auth
def admin_import_process():
    is_admin = session.get('email') == os.environ.get('ROOT_ADMIN_USER')
    if not is_admin:
        return jsonify({"success": False, "message": "Unauthorized Access"}), 403

    if 'file' not in request.files:
        return jsonify({"success": False, "message": "No file uploaded"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"success": False, "message": "No file selected"}), 400

    if not file.filename.endswith('.json'):
        return jsonify({"success": False, "message": "Only JSON backup files are supported."}), 400

    try:
        data = json.load(file)
        
        records_imported = 0
        
        # Import standard ID_STORES into the 'records' table
        for store_name in ID_STORES:
            if store_name in data and isinstance(data[store_name], list):
                # Clear old records for clean import (mimics the restore function)
                Record.query.filter_by(store=store_name).delete()
                
                for item in data[store_name]:
                    rid = item.get("id")
                    if rid is None:
                        rid = next_id(store_name)
                        item["id"] = rid
                    db.session.add(Record(store=store_name, rec_id=rid, data=item))
                    records_imported += 1

        # Import 'settings' into the 'settings' table
        if "settings" in data and isinstance(data["settings"], list):
            Setting.query.delete()
            for item in data["settings"]:
                key = item.get("key")
                if key:
                    db.session.add(Setting(key=key, data=item))
                    records_imported += 1

        db.session.commit()
        return jsonify({"success": True, "message": f"Successfully imported {records_imported} policy records into the Database!"})
        
    except json.JSONDecodeError:
        return jsonify({"success": False, "message": "Invalid JSON file format."}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Error parsing data: {str(e)}"}), 500

# ---------------------------------------------------------------------------
# Generic CRUD endpoints
# ---------------------------------------------------------------------------
def store_or_404(store):
    if store not in ID_STORES:
        abort(404)

@app.route("/api/<store>", methods=["GET"])
@require_auth
def list_records(store):
    store_or_404(store)
    rows = Record.query.filter_by(store=store).order_by(Record.rec_id).all()
    return jsonify([r.data for r in rows])

@app.route("/api/<store>", methods=["POST"])
@require_auth
def create_record(store):
    store_or_404(store)
    obj = request.get_json(force=True) or {}
    obj.pop("id", None)
    rid = next_id(store)
    obj["id"] = rid
    db.session.add(Record(store=store, rec_id=rid, data=obj))
    db.session.commit()
    return jsonify(obj), 201

@app.route("/api/<store>/<int:rec_id>", methods=["GET"])
@require_auth
def get_record(store, rec_id):
    store_or_404(store)
    row = Record.query.filter_by(store=store, rec_id=rec_id).first()
    if not row:
        abort(404)
    return jsonify(row.data)

@app.route("/api/<store>/<int:rec_id>", methods=["PUT"])
@require_auth
def put_record(store, rec_id):
    store_or_404(store)
    obj = request.get_json(force=True) or {}
    obj["id"] = rec_id
    row = Record.query.filter_by(store=store, rec_id=rec_id).first()
    if row:
        row.data = obj
    else:
        db.session.add(Record(store=store, rec_id=rec_id, data=obj))
    db.session.commit()
    return jsonify(obj)

@app.route("/api/<store>/<int:rec_id>", methods=["DELETE"])
@require_auth
def delete_record(store, rec_id):
    store_or_404(store)
    Record.query.filter_by(store=store, rec_id=rec_id).delete()
    db.session.commit()
    return jsonify({"ok": True})

@app.route("/api/<store>/clear", methods=["POST"])
@require_auth
def clear_store(store):
    store_or_404(store)
    Record.query.filter_by(store=store).delete()
    db.session.commit()
    return jsonify({"ok": True})

# ---------------------------------------------------------------------------
# Settings store
# ---------------------------------------------------------------------------
@app.route("/api/settings", methods=["GET"])
@require_auth
def list_settings():
    rows = Setting.query.all()
    return jsonify([{"key": r.key, **(r.data if isinstance(r.data, dict) else {"value": r.data})} for r in rows])

@app.route("/api/settings", methods=["POST"])
@require_auth
def create_setting():
    obj = request.get_json(force=True) or {}
    key = obj.get("key")
    if not key:
        return jsonify({"error": "key required"}), 400
    row = Setting.query.get(key)
    if row:
        row.data = obj
    else:
        db.session.add(Setting(key=key, data=obj))
    db.session.commit()
    return jsonify(obj), 201

@app.route("/api/settings/<key>", methods=["PUT"])
@require_auth
def put_setting(key):
    obj = request.get_json(force=True) or {}
    obj["key"] = key
    row = Setting.query.get(key)
    if row:
        row.data = obj
    else:
        db.session.add(Setting(key=key, data=obj))
    db.session.commit()
    return jsonify(obj)

@app.route("/api/settings/<key>", methods=["DELETE"])
@require_auth
def delete_setting(key):
    Setting.query.filter_by(key=key).delete()
    db.session.commit()
    return jsonify({"ok": True})

@app.route("/api/settings/clear", methods=["POST"])
@require_auth
def clear_settings():
    Setting.query.delete()
    db.session.commit()
    return jsonify({"ok": True})

# ---------------------------------------------------------------------------
# Backup / Restore
# ---------------------------------------------------------------------------
@app.route("/api/backup", methods=["GET"])
@require_auth
def backup():
    out = {}
    for s in ID_STORES:
        rows = Record.query.filter_by(store=s).order_by(Record.rec_id).all()
        out[s] = [r.data for r in rows]
    out["settings"] = [{"key": r.key, **(r.data if isinstance(r.data, dict) else {})} for r in Setting.query.all()]
    out["_meta"] = {"version": 1, "exportedAt": datetime.utcnow().isoformat() + "Z", "system": "POPMS"}
    return jsonify(out)

@app.route("/api/restore", methods=["POST"])
@require_auth
def restore():
    data = request.get_json(force=True) or {}
    for s in ID_STORES:
        Record.query.filter_by(store=s).delete()
        for item in data.get(s, []):
            rid = item.get("id")
            if rid is None:
                rid = next_id(s)
                item["id"] = rid
            db.session.add(Record(store=s, rec_id=rid, data=item))
    Setting.query.delete()
    for item in data.get("settings", []):
        key = item.get("key")
        if key:
            db.session.add(Setting(key=key, data=item))
    db.session.commit()
    return jsonify({"ok": True})

# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------
@app.route("/")
@require_auth
def index():
    return render_template("index.html")

@app.route("/health")
def health():
    return {"success": True, "message": "Policy Service Healthy", "data": None, "errors": None}, 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)