from flask import Flask, request, jsonify, render_template_string
import sqlite3
import uuid
import time
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

SERVER_URL = os.getenv("SERVER_URL", "http://localhost:5000")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "changeme")
KEY_TTL = 86400

DB_PATH = "keys.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS keys (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            key        TEXT UNIQUE NOT NULL,
            user_id    TEXT NOT NULL,
            token      TEXT UNIQUE NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            redeemed   INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def cleanup_expired():
    conn = get_db()
    conn.execute("DELETE FROM keys WHERE expires_at < ?", (int(time.time()),))
    conn.commit()
    conn.close()


def make_key():
    return "-".join(uuid.uuid4().hex[:4].upper() for _ in range(4))


@app.route("/generate", methods=["POST"])
def generate():
    data = request.get_json()
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"success": False}), 400

    cleanup_expired()
    conn = get_db()

    existing = conn.execute(
        "SELECT * FROM keys WHERE user_id=? AND expires_at>? AND redeemed=0",
        (user_id, int(time.time()))
    ).fetchone()

    if existing:
        conn.close()
        return jsonify({
            "success": True,
            "url": f"{SERVER_URL}/get/{existing['token']}"
        })

    key = make_key()
    token = uuid.uuid4().hex
    now = int(time.time())

    conn.execute(
        "INSERT INTO keys (key, user_id, token, created_at, expires_at) VALUES (?,?,?,?,?)",
        (key, user_id, token, now, now + KEY_TTL)
    )
    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "url": f"{SERVER_URL}/get/{token}"
    })


@app.route("/get/<token>")
def get_key(token):
    cleanup_expired()
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM keys WHERE token=? AND expires_at>?",
        (token, int(time.time()))
    ).fetchone()
    conn.close()

    if not row:
        return render_template_string(PAGE, key=None, hours=0, minutes=0)

    remaining = row["expires_at"] - int(time.time())
    return render_template_string(
        PAGE,
        key=row["key"],
        hours=remaining // 3600,
        minutes=(remaining % 3600) // 60
    )


@app.route("/verify", methods=["POST"])
def verify():
    data = request.get_json()
    key = data.get("key", "").strip().upper()
    if not key:
        return jsonify({"valid": False}), 400

    cleanup_expired()
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM keys WHERE key=? AND expires_at>? AND redeemed=0",
        (key, int(time.time()))
    ).fetchone()

    if not row:
        conn.close()
        return jsonify({"valid": False})

    conn.execute("UPDATE keys SET redeemed=1 WHERE key=?", (key,))
    conn.commit()
    conn.close()
    return jsonify({"valid": True, "user_id": row["user_id"]})


@app.route("/admin")
def admin():
    if request.args.get("secret") != ADMIN_SECRET:
        return "Forbidden", 403
    conn = get_db()
    rows = conn.execute("SELECT * FROM keys ORDER BY created_at DESC LIMIT 100").fetchall()
    conn.close()
    now = int(time.time())
    return jsonify([{
        "key": r["key"],
        "user_id": r["user_id"],
        "active": r["expires_at"] > now and not r["redeemed"],
        "redeemed": bool(r["redeemed"]),
        "expires_in_h": max(0, r["expires_at"] - now) // 3600
    } for r in rows])


PAGE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Получить ключ</title>
<script src="https://publisher.linkvertise.com/cdn/linkvertise.js"></script>
<script>linkvertise(4260771, {whitelist: [], blacklist: [""]});</script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0d0d14;font-family:'Segoe UI',sans-serif;color:#e2e2e2}
.card{background:#16161f;border:1px solid #2a2a3d;border-radius:16px;padding:44px 52px;text-align:center;max-width:480px;width:92%}
h1{font-size:22px;margin-bottom:8px;color:#fff}
.sub{font-size:14px;color:#777;margin-bottom:32px}
.key{background:#0d0d14;border:1px solid #5865f2;border-radius:10px;padding:18px 24px;font-family:'Courier New',monospace;font-size:26px;letter-spacing:5px;color:#5865f2;cursor:pointer;transition:background .15s;margin-bottom:12px;user-select:all}
.key:hover{background:#13131e}
.hint{font-size:13px;color:#555;margin-bottom:20px}
.timer{font-size:13px;color:#f0b429}
.err{color:#f04747;font-size:16px;margin-top:16px}
</style>
</head>
<body>
<div class="card">
{% if key %}
  <h1>🔑 Ваш ключ</h1>
  <p class="sub">Нажмите на ключ чтобы скопировать</p>
  <div class="key" onclick="copy(this)">{{ key }}</div>
  <p class="hint" id="h">Нажмите чтобы скопировать</p>
  <p class="timer">⏳ Действует ещё {{ hours }}ч {{ minutes }}м</p>
{% else %}
  <h1>❌ Ключ не найден</h1>
  <p class="err">Ключ недействителен или истёк.<br>Запросите новый в Discord.</p>
{% endif %}
</div>
<script>
function copy(el){
  navigator.clipboard.writeText(el.textContent.trim());
  var h=document.getElementById('h');
  h.textContent='✅ Скопировано!';
  setTimeout(()=>h.textContent='Нажмите чтобы скопировать',2000);
}
</script>
</body>
</html>"""


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
