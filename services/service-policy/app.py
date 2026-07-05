import os
from datetime import datetime

from flask import Flask, request, jsonify, session, render_template, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import JSON as SA_JSON

# ---------------------------------------------------------------------------
# App / DB setup
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "popms-dev-secret-change-me")

db_url = os.environ.get("DATABASE_URL", "sqlite:///" + os.path.join(app.instance_path, "popms.db"))
# Render's Postgres URLs start with postgres:// ; SQLAlchemy needs postgresql://
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}

os.makedirs(app.instance_path, exist_ok=True)
db = SQLAlchemy(app)

# ---------------------------------------------------------------------------
# Models — one table per IndexedDB "store". Each row keeps its full record
# as JSON so the existing frontend data shapes (which vary per store) don't
# need a rigid relational schema. `id`-keyed stores get an autoincrement PK;
# `settings` is keyed by a string `key` instead (matches the original app).
# ---------------------------------------------------------------------------
ID_STORES = ["users", "categories", "policies", "archives", "acceptances",
             "docViews", "videoViews", "monthlyCerts"]


class Record(db.Model):
    """Generic row for id-keyed stores."""
    __tablename__ = "records"
    pk = db.Column(db.Integer, primary_key=True)
    store = db.Column(db.String(32), nullable=False, index=True)
    rec_id = db.Column(db.Integer, nullable=False, index=True)
    data = db.Column(SA_JSON, nullable=False)

    __table_args__ = (db.UniqueConstraint("store", "rec_id", name="uq_store_recid"),)


class Setting(db.Model):
    __tablename__ = "settings"
    key = db.Column(db.String(64), primary_key=True)
    data = db.Column(SA_JSON, nullable=False)


with app.app_context():
    db.create_all()


def next_id(store):
    row = db.session.query(db.func.max(Record.rec_id)).filter(Record.store == store).scalar()
    return (row or 0) + 1


def seed_defaults():
    if Record.query.filter_by(store="users").count() == 0:
        db.session.add(Record(store="users", rec_id=1, data={
            "role": "admin", "name": "System Administrator", "designation": "Administrator",
            "email": "admin@pariman.local", "mobile": "", "username": "admin",
            "password": "admin123", "id": 1,
        }))
    if Record.query.filter_by(store="categories").count() == 0:
        seeds = ["HR Policies", "Office Administration", "Leave Rules", "Attendance Rules",
                 "Finance Policies", "IT Security", "Cyber Security", "Data Privacy",
                 "Quality Control", "Training Policies"]
        for i, n in enumerate(seeds, start=1):
            db.session.add(Record(store="categories", rec_id=i,
                                   data={"name": n, "createdAt": int(datetime.utcnow().timestamp() * 1000), "id": i}))
    db.session.commit()


with app.app_context():
    seed_defaults()

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@app.route("/api/login", methods=["POST"])
def login():
    body = request.get_json(force=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    role = body.get("role") or "admin"

    row = None
    for r in Record.query.filter_by(store="users").all():
        d = r.data
        if d.get("username") == username and d.get("password") == password and d.get("role") == role:
            row = r
            break

    if not row:
        return jsonify({"error": "Invalid credentials"}), 401

    session["user_id"] = row.rec_id
    return jsonify(row.data)


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/me", methods=["GET"])
def me():
    uid = session.get("user_id")
    if not uid:
        return jsonify(None)
    row = Record.query.filter_by(store="users", rec_id=uid).first()
    return jsonify(row.data if row else None)


# ---------------------------------------------------------------------------
# Generic CRUD for id-keyed stores: /api/<store>[/<id>]
# ---------------------------------------------------------------------------
def store_or_404(store):
    if store not in ID_STORES:
        abort(404)


@app.route("/api/<store>", methods=["GET"])
def list_records(store):
    store_or_404(store)
    rows = Record.query.filter_by(store=store).order_by(Record.rec_id).all()
    return jsonify([r.data for r in rows])


@app.route("/api/<store>", methods=["POST"])
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
def get_record(store, rec_id):
    store_or_404(store)
    row = Record.query.filter_by(store=store, rec_id=rec_id).first()
    if not row:
        abort(404)
    return jsonify(row.data)


@app.route("/api/<store>/<int:rec_id>", methods=["PUT"])
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
def delete_record(store, rec_id):
    store_or_404(store)
    Record.query.filter_by(store=store, rec_id=rec_id).delete()
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/<store>/clear", methods=["POST"])
def clear_store(store):
    store_or_404(store)
    Record.query.filter_by(store=store).delete()
    db.session.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Settings store — keyed by string `key`, not an autoincrement id
# ---------------------------------------------------------------------------
@app.route("/api/settings", methods=["GET"])
def list_settings():
    rows = Setting.query.all()
    return jsonify([{"key": r.key, **(r.data if isinstance(r.data, dict) else {"value": r.data})} for r in rows])


@app.route("/api/settings", methods=["POST"])
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
def delete_setting(key):
    Setting.query.filter_by(key=key).delete()
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/settings/clear", methods=["POST"])
def clear_settings():
    Setting.query.delete()
    db.session.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Full backup / restore (used by the app's Settings > Backup/Restore panel)
# ---------------------------------------------------------------------------
ALL_STORES = ID_STORES + ["settings"]


@app.route("/api/backup", methods=["GET"])
def backup():
    out = {}
    for s in ID_STORES:
        rows = Record.query.filter_by(store=s).order_by(Record.rec_id).all()
        out[s] = [r.data for r in rows]
    out["settings"] = [{"key": r.key, **(r.data if isinstance(r.data, dict) else {})} for r in Setting.query.all()]
    out["_meta"] = {"version": 1, "exportedAt": datetime.utcnow().isoformat() + "Z", "system": "POPMS"}
    return jsonify(out)


@app.route("/api/restore", methods=["POST"])
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
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    # Ensure port is 5000 and host is 0.0.0.0
    app.run(host="0.0.0.0", port=5000, debug=True)