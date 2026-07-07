import base64
import json
import os
import sys
import psycopg2
import redis
from flask import Flask, render_template, request, jsonify, Response, session
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy.dialects.postgresql import JSONB

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
try:
    from common.auth_middleware import require_auth
except ImportError:
    def require_auth(f):
        return f

db = SQLAlchemy()
sess = Session()
migrate = Migrate()

def create_app():
    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fallback-dev-key')
    redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    app.config['SESSION_TYPE'] = 'redis'
    app.config['SESSION_PERMANENT'] = False
    app.config['SESSION_USE_SIGNER'] = True
    app.config['SESSION_KEY_PREFIX'] = 'pariman_session:'
    app.config['SESSION_REDIS'] = redis.from_url(redis_url)
    app.config['SESSION_COOKIE_SECURE'] = False
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    db_url = os.environ.get("DATABASE_URL", "")
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    sess.init_app(app)
    migrate.init_app(app, db)
    return app

app = create_app()

class KVStore(db.Model):
    __tablename__ = 'kv_store'
    __table_args__ = {'schema': 'itr'}
    key = db.Column(db.Text, primary_key=True)
    value = db.Column(JSONB)

class FileStore(db.Model):
    __tablename__ = 'files'
    __table_args__ = {'schema': 'itr'}
    key = db.Column(db.Text, primary_key=True)
    blob = db.Column(db.LargeBinary, nullable=False)
    filename = db.Column(db.Text)
    type = db.Column(db.Text)
    client_id = db.Column(db.Text)
    fy = db.Column(db.Text)
    size = db.Column(db.Integer)
    uploaded = db.Column(db.DateTime, server_default=db.func.now())

def get_conn():
    db_url = app.config["SQLALCHEMY_DATABASE_URI"]
    return psycopg2.connect(db_url)

@app.route("/health")
def health_check():
    return {"success": True, "message": "ITR Service Healthy"}, 200

@app.route("/")
@require_auth
def index():
    return render_template("itr.html")

@app.route("/admin/import", methods=["GET"], strict_slashes=False)
@require_auth
def admin_import_page():
    is_admin = session.get('email') == os.environ.get('ROOT_ADMIN_USER')
    if not is_admin:
        return "Unauthorized Access. Admin only.", 403
    return render_template("admin_import.html")

@app.route("/admin/import", methods=["POST"], strict_slashes=False)
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
        keys_to_import = ['users', 'clients', 'allocations', 'inward', 'itrStatus', 'seq']
        conn = get_conn()
        cur = conn.cursor()
        records_imported = 0
        for key in keys_to_import:
            if key in data:
                val = data[key]
                cur.execute(
                    """INSERT INTO itr.kv_store (key, value) VALUES (%s, %s)
                       ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
                    (key, json.dumps(val))
                )
                records_imported += 1
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True, "message": f"Successfully imported {records_imported} data categories!"})
    except Exception as e:
        return jsonify({"success": False, "message": f"Error parsing data: {str(e)}"}), 500

@app.route("/api/kv", methods=["GET"])
@require_auth
def kv_get_all():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT key, value FROM itr.kv_store")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify({k: v for k, v in rows})

@app.route("/api/kv/<key>", methods=["POST"])
@require_auth
def kv_set(key):
    body = request.get_json(force=True)
    value = body.get("value")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO itr.kv_store (key, value) VALUES (%s, %s)
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
        (key, json.dumps(value)),
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/kv/<key>", methods=["DELETE"])
@require_auth
def kv_del(key):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM itr.kv_store WHERE key=%s", (key,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/files/<path:key>", methods=["POST"])
@require_auth
def file_save(key):
    body = request.get_json(force=True)
    b64 = body["data"]
    meta = body.get("meta", {})
    raw = base64.b64decode(b64)
    if len(raw) > (5 * 1024 * 1024):
        return jsonify({"success": False, "message": "File exceeds 5 MB limit"}), 400
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO itr.files (key, blob, filename, type, client_id, fy, size)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (key) DO UPDATE SET
             blob=EXCLUDED.blob, filename=EXCLUDED.filename, type=EXCLUDED.type,
             client_id=EXCLUDED.client_id, fy=EXCLUDED.fy, size=EXCLUDED.size,
             uploaded=now()""",
        (key, psycopg2.Binary(raw), meta.get("filename"), meta.get("type"), meta.get("clientId"), meta.get("fy"), len(raw))
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/files/<path:key>", methods=["GET"])
@require_auth
def file_get(key):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT blob, type, filename FROM itr.files WHERE key=%s", (key,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return jsonify({"success": False}), 404
    return Response(
        bytes(row[0]),
        mimetype=row[1] or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{row[2] or key}"'},
    )

@app.route("/api/files/<path:key>/meta", methods=["GET"])
@require_auth
def file_meta(key):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT filename, type, client_id, fy, size, uploaded FROM itr.files WHERE key=%s", (key,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return jsonify(None)
    return jsonify({
        "filename": row[0], "type": row[1], "clientId": row[2], 
        "fy": row[3], "size": row[4], "uploaded": row[5].isoformat() if row[5] else None
    })

@app.route("/api/files/<path:key>", methods=["DELETE"])
@require_auth
def file_del(key):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM itr.files WHERE key=%s", (key,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)