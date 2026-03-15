from flask import Flask, request, jsonify, render_template_string
import sqlite3
import uuid
import time
import os
import urllib.parse
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pass_tokens (
            token      TEXT PRIMARY KEY,
            user_id    TEXT NOT NULL,
            expires_at INTEGER NOT NULL,
            used       INTEGER DEFAULT 0
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
    conn.execute("DELETE FROM pass_tokens WHERE expires_at < ?", (int(time.time()),))
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
    return jsonify({
        "success": True,
        "url": f"{SERVER_URL}/get/{user_id}"
    })


@app.route("/get/<user_id>")
def get_key(user_id):
    pt = uuid.uuid4().hex
    conn = get_db()
    conn.execute(
        "INSERT INTO pass_tokens (token, user_id, expires_at) VALUES (?,?,?)",
        (pt, user_id, int(time.time()) + 900)
    )
    conn.commit()
    conn.close()
    return render_template_string(LANDING_PAGE, user_id=user_id, pt=pt)


@app.route("/reveal/<user_id>/<pt>")
def reveal_key(user_id, pt):
    conn = get_db()
    pt_row = conn.execute(
        "SELECT * FROM pass_tokens WHERE token=? AND user_id=? AND expires_at>?",
        (pt, user_id, int(time.time()))
    ).fetchone()

    if not pt_row:
        conn.close()
        return render_template_string(ERROR_PAGE)

    cleanup_expired()

    row = conn.execute(
        "SELECT * FROM keys WHERE user_id=? AND expires_at>?",
        (user_id, int(time.time()))
    ).fetchone()

    if row:
        remaining = row["expires_at"] - int(time.time())
        conn.close()
        return render_template_string(
            KEY_PAGE,
            key=row["key"],
            hours=remaining // 3600,
            minutes=(remaining % 3600) // 60
        )

    key = make_key()
    token = uuid.uuid4().hex
    now = int(time.time())
    conn.execute(
        "INSERT INTO keys (key, user_id, token, created_at, expires_at) VALUES (?,?,?,?,?)",
        (key, user_id, token, now, now + KEY_TTL)
    )
    conn.commit()
    conn.close()
    return render_template_string(KEY_PAGE, key=key, hours=23, minutes=59)


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


LANDING_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Get Key</title>
<script src="https://publisher.linkvertise.com/cdn/linkvertise.js"></script>
<script>linkvertise(4260771, {whitelist: [], blacklist: [""]});</script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0d0d14;font-family:'Segoe UI',sans-serif;color:#e2e2e2}
.card{background:#16161f;border:1px solid #2a2a3d;border-radius:16px;padding:44px 52px;text-align:center;max-width:480px;width:92%}
h1{font-size:22px;margin-bottom:8px;color:#fff}
.sub{font-size:14px;color:#777;margin-bottom:32px}
.btn{display:inline-block;background:#5865f2;color:#fff;text-decoration:none;font-size:16px;font-weight:600;padding:14px 36px;border-radius:10px;transition:background .15s}
.btn:hover{background:#4752c4}
.note{font-size:12px;color:#555;margin-top:20px}
</style>
</head>
<body>
<div class="card">
  <h1>🔑 Get Your Key</h1>
  <p class="sub">Complete a short task to receive your key.<br>It will be valid for 24 hours.</p>
  <a class="btn" href="/reveal/{{ user_id }}/{{ pt }}">Get Key</a>
  <p class="note">You will be redirected through a short verification.</p>
</div>
</body>
</html>"""


KEY_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Your Key</title>
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
</style>
</head>
<body>
<div class="card">
  <h1>🔑 Your Key</h1>
  <p class="sub">Click the key to copy it</p>
  <div class="key" onclick="copy(this)">{{ key }}</div>
  <p class="hint" id="h">Click to copy</p>
  <p class="timer">⏳ Expires in {{ hours }}h {{ minutes }}m</p>
</div>
<script>
function copy(el){
  navigator.clipboard.writeText(el.textContent.trim());
  var h=document.getElementById('h');
  h.textContent='✅ Copied!';
  setTimeout(()=>h.textContent='Click to copy',2000);
}
</script>
</body>
</html>"""


ERROR_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Key Not Found</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0d0d14;font-family:'Segoe UI',sans-serif;color:#e2e2e2}
.card{background:#16161f;border:1px solid #2a2a3d;border-radius:16px;padding:44px 52px;text-align:center;max-width:480px;width:92%}
h1{font-size:22px;margin-bottom:8px;color:#fff}
.err{color:#f04747;font-size:15px;margin-top:12px}
</style>
</head>
<body>
<div class="card">
  <h1>❌ Key Not Found</h1>
  <p class="err">This key is invalid or has expired.<br>Request a new one in our Discord.</p>
</div>
</body>
</html>"""


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
