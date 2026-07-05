import base64
import json
import os
import psycopg2
from flask import Flask, render_template, request, jsonify, Response

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)


def get_conn():
    return psycopg2.connect(DATABASE_URL)


import time

def init_db():
    print("Connecting to database...")
    while True:
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute(
                """CREATE TABLE IF NOT EXISTS kv_store (
                    key TEXT PRIMARY KEY,
                    value JSONB
                )"""
            )
            cur.execute(
                """CREATE TABLE IF NOT EXISTS files (
                    key TEXT PRIMARY KEY,
                    blob BYTEA NOT NULL,
                    filename TEXT,
                    type TEXT,
                    client_id TEXT,
                    fy TEXT,
                    size INTEGER,
                    uploaded TIMESTAMP DEFAULT now()
                )"""
            )
            conn.commit()
            cur.close()
            conn.close()
            print("Database connected and tables initialized!")
            break  # Exit the loop once successful
        except Exception as e:
            print(f"Database not ready yet ({e}). Retrying in 2 seconds...")
            time.sleep(2)


init_db()


@app.route("/")
def index():
    return render_template("itr.html")

@app.route("/ping")
def ping():
    return "ok", 200


# ---------- KV store (clients, users, allocations, inward, itrStatus, seq) ----------

@app.route("/api/kv", methods=["GET"])
def kv_get_all():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT key, value FROM kv_store")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify({k: v for k, v in rows})


@app.route("/api/kv/<key>", methods=["POST"])
def kv_set(key):
    body = request.get_json(force=True)
    value = body.get("value")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO kv_store (key, value) VALUES (%s, %s)
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
        (key, json.dumps(value)),
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/kv/<key>", methods=["DELETE"])
def kv_del(key):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM kv_store WHERE key=%s", (key,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})


# ---------- File storage (ITR documents) ----------

MAX_FILE = 5 * 1024 * 1024  # 5 MB


@app.route("/api/files/<path:key>", methods=["POST"])
def file_save(key):
    body = request.get_json(force=True)
    b64 = body["data"]  # base64-encoded file content
    meta = body.get("meta", {})
    raw = base64.b64decode(b64)
    if len(raw) > MAX_FILE:
        return jsonify({"error": "File exceeds 5 MB limit"}), 400
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO files (key, blob, filename, type, client_id, fy, size)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (key) DO UPDATE SET
             blob=EXCLUDED.blob, filename=EXCLUDED.filename, type=EXCLUDED.type,
             client_id=EXCLUDED.client_id, fy=EXCLUDED.fy, size=EXCLUDED.size,
             uploaded=now()""",
        (
            key,
            psycopg2.Binary(raw),
            meta.get("filename"),
            meta.get("type"),
            meta.get("clientId"),
            meta.get("fy"),
            len(raw),
        ),
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/files/<path:key>", methods=["GET"])
def file_get(key):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT blob, type, filename FROM files WHERE key=%s", (key,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return jsonify(None), 404
    blob, ftype, filename = row
    return Response(
        bytes(blob),
        mimetype=ftype or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{filename or key}"'},
    )


@app.route("/api/files/<path:key>/meta", methods=["GET"])
def file_meta(key):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT filename, type, client_id, fy, size, uploaded FROM files WHERE key=%s",
        (key,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return jsonify(None)
    return jsonify(
        {
            "filename": row[0],
            "type": row[1],
            "clientId": row[2],
            "fy": row[3],
            "size": row[4],
            "uploaded": row[5].isoformat() if row[5] else None,
        }
    )


@app.route("/api/files/<path:key>", methods=["DELETE"])
def file_del(key):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM files WHERE key=%s", (key,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/files-all", methods=["DELETE"])
def files_delete_all():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM files")
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/files-usage", methods=["GET"])
def files_usage():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(SUM(size),0) FROM files")
    total = cur.fetchone()[0]
    cur.close()
    conn.close()
    return jsonify({"usedBytes": int(total)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
