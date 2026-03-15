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
            ip         TEXT NOT NULL,
            pt         TEXT UNIQUE NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pass_tokens (
            token      TEXT PRIMARY KEY,
            ip         TEXT NOT NULL,
            expires_at INTEGER NOT NULL
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


def get_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr).split(",")[0].strip()


def make_key():
    return "-".join(uuid.uuid4().hex[:4].upper() for _ in range(4))


@app.route("/")
def index():
    ip = get_ip()
    cleanup_expired()
    conn = get_db()

    # Если с этого IP уже есть действующий ключ — сразу показываем
    row = conn.execute(
        "SELECT * FROM keys WHERE ip=? AND expires_at>?",
        (ip, int(time.time()))
    ).fetchone()

    if row:
        remaining = row["expires_at"] - int(time.time())
        conn.close()
        return render_template_string(KEY_PAGE,
            key=row["key"],
            hours=remaining // 3600,
            minutes=(remaining % 3600) // 60
        )

    # Генерируем pass_token
    pt = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO pass_tokens (token, ip, expires_at) VALUES (?,?,?)",
        (pt, ip, int(time.time()) + 900)
    )
    conn.commit()
    conn.close()
    return render_template_string(LANDING_PAGE, pt=pt)


@app.route("/get/<pt>")
def get_key(pt):
    ip = get_ip()
    conn = get_db()

    pt_row = conn.execute(
        "SELECT * FROM pass_tokens WHERE token=? AND ip=? AND expires_at>?",
        (pt, ip, int(time.time()))
    ).fetchone()

    if not pt_row:
        conn.close()
        return render_template_string(ERROR_PAGE)

    cleanup_expired()

    # Проверяем нет ли уже ключа для этого IP
    row = conn.execute(
        "SELECT * FROM keys WHERE ip=? AND expires_at>?",
        (ip, int(time.time()))
    ).fetchone()

    if row:
        remaining = row["expires_at"] - int(time.time())
        conn.close()
        return render_template_string(KEY_PAGE,
            key=row["key"],
            hours=remaining // 3600,
            minutes=(remaining % 3600) // 60
        )

    key = make_key()
    now = int(time.time())
    conn.execute(
        "INSERT INTO keys (key, ip, pt, created_at, expires_at) VALUES (?,?,?,?,?)",
        (key, ip, pt, now, now + KEY_TTL)
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
        "SELECT * FROM keys WHERE key=? AND expires_at>?",
        (key, int(time.time()))
    ).fetchone()
    conn.close()

    if not row:
        return jsonify({"valid": False})
    return jsonify({"valid": True})


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
        "ip": r["ip"],
        "expires_in_h": max(0, r["expires_at"] - now) // 3600
    } for r in rows])


LANDING_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Key System</title>
<script src="https://publisher.linkvertise.com/cdn/linkvertise.js"></script>
<script>linkvertise(4260771, {whitelist: [], blacklist: [""]});</script>
<style>
  body { margin: 0; background: #fff; font-family: Arial, sans-serif; color: #111; display: flex; align-items: center; justify-content: center; min-height: 100vh; }
  .box { width: 360px; padding: 32px; border: 1px solid #ddd; }
  h2 { margin: 0 0 6px; font-size: 18px; font-weight: bold; }
  p { margin: 0 0 24px; font-size: 13px; color: #555; line-height: 1.5; }
  a.btn { display: block; background: #111; color: #fff; text-align: center; padding: 11px; font-size: 14px; text-decoration: none; }
  a.btn:hover { background: #333; }
  .note { margin: 12px 0 0; font-size: 12px; color: #aaa; text-align: center; }
</style>
</head>
<body>
<div class="box">
  <h2>Get your key</h2>
  <p>Complete a short task to receive your 24-hour key.<br>Next time you visit, your key will appear automatically.</p>
  <a class="btn" href="/get/{{ pt }}">Continue</a>
  <p class="note">Redirects through a verification step</p>
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
  body { margin: 0; background: #fff; font-family: Arial, sans-serif; color: #111; display: flex; align-items: center; justify-content: center; min-height: 100vh; }
  .box { width: 360px; padding: 32px; border: 1px solid #ddd; }
  h2 { margin: 0 0 6px; font-size: 18px; font-weight: bold; }
  p { margin: 0 0 16px; font-size: 13px; color: #555; }
  .key { font-family: 'Courier New', monospace; font-size: 20px; letter-spacing: 3px; background: #f5f5f5; border: 1px solid #ccc; padding: 14px 16px; cursor: pointer; user-select: all; margin-bottom: 8px; }
  .key:hover { background: #eee; }
  .hint { font-size: 12px; color: #aaa; margin: 0 0 16px; }
  .timer { font-size: 12px; color: #888; border-top: 1px solid #eee; padding-top: 14px; margin: 0; }
</style>
</head>
<body>
<div class="box">
  <h2>Your key</h2>
  <p>Click to copy, then paste it into the script.</p>
  <div class="key" onclick="copyKey(this)">{{ key }}</div>
  <p class="hint" id="h">click to copy</p>
  <p class="timer">Expires in {{ hours }}h {{ minutes }}m</p>
</div>
<script>
function copyKey(el) {
  navigator.clipboard.writeText(el.textContent.trim());
  var h = document.getElementById('h');
  h.textContent = 'copied!';
  setTimeout(function(){ h.textContent = 'click to copy'; }, 2000);
}
</script>
</body>
</html>"""


ERROR_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Error</title>
<style>
  body { margin: 0; background: #fff; font-family: Arial, sans-serif; color: #111; display: flex; align-items: center; justify-content: center; min-height: 100vh; }
  .box { width: 360px; padding: 32px; border: 1px solid #ddd; }
  h2 { margin: 0 0 8px; font-size: 18px; }
  p { margin: 0; font-size: 13px; color: #555; line-height: 1.6; }
  a { color: #111; }
</style>
</head>
<body>
<div class="box">
  <h2>Link expired</h2>
  <p>This link is no longer valid. <a href="/">Go back</a> to get a new one.</p>
</div>
</body>
</html>"""


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ip_cache (
            ip         TEXT PRIMARY KEY,
            key        TEXT NOT NULL,
            expires_at INTEGER NOT NULL
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
    conn.execute("DELETE FROM ip_cache WHERE expires_at < ?", (int(time.time()),))
    conn.commit()
    conn.close()


def get_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr).split(",")[0].strip()


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
    ip = get_ip()
    cleanup_expired()
    conn = get_db()

    # Если с этого IP уже есть действующий ключ — сразу показываем
    cached = conn.execute(
        "SELECT * FROM ip_cache WHERE ip=? AND expires_at>?",
        (ip, int(time.time()))
    ).fetchone()
    if cached:
        row = conn.execute(
            "SELECT * FROM keys WHERE key=? AND expires_at>?",
            (cached["key"], int(time.time()))
        ).fetchone()
        if row:
            remaining = row["expires_at"] - int(time.time())
            conn.close()
            return render_template_string(KEY_PAGE,
                key=row["key"],
                hours=remaining // 3600,
                minutes=(remaining % 3600) // 60
            )

    pt = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO pass_tokens (token, user_id, expires_at) VALUES (?,?,?)",
        (pt, user_id, int(time.time()) + 900)
    )
    conn.commit()
    conn.close()
    return render_template_string(LANDING_PAGE, user_id=user_id, pt=pt)


@app.route("/reveal/<user_id>/<pt>")
def reveal_key(user_id, pt):
    ip = get_ip()
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
        key = row["key"]
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
    else:
        key = make_key()
        token = uuid.uuid4().hex
        now = int(time.time())
        conn.execute(
            "INSERT INTO keys (key, user_id, token, created_at, expires_at) VALUES (?,?,?,?,?)",
            (key, user_id, token, now, now + KEY_TTL)
        )
        conn.commit()
        hours, minutes = 23, 59

    # Сохраняем IP → ключ
    conn.execute(
        "INSERT OR REPLACE INTO ip_cache (ip, key, expires_at) VALUES (?,?,?)",
        (ip, key, int(time.time()) + KEY_TTL)
    )
    conn.commit()
    conn.close()
    return render_template_string(KEY_PAGE, key=key, hours=hours, minutes=minutes)


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
<title>Key System</title>
<script src="https://publisher.linkvertise.com/cdn/linkvertise.js"></script>
<script>linkvertise(4260771, {whitelist: [], blacklist: [""]});</script>
<style>
  body { margin: 0; background: #fff; font-family: Arial, sans-serif; color: #111; display: flex; align-items: center; justify-content: center; min-height: 100vh; }
  .box { width: 360px; padding: 32px; border: 1px solid #ddd; }
  h2 { margin: 0 0 6px; font-size: 18px; font-weight: bold; }
  p { margin: 0 0 24px; font-size: 13px; color: #555; line-height: 1.5; }
  a.btn { display: block; background: #111; color: #fff; text-align: center; padding: 11px; font-size: 14px; text-decoration: none; }
  a.btn:hover { background: #333; }
  .note { margin: 12px 0 0; font-size: 12px; color: #aaa; text-align: center; }
</style>
</head>
<body>
<div class="box">
  <h2>Get your key</h2>
  <p>Complete a short task to receive your 24-hour key.<br>You only need to do this once per day.</p>
  <a class="btn" href="/reveal/{{ user_id }}/{{ pt }}">Continue</a>
  <p class="note">Redirects through a verification step</p>
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
  body { margin: 0; background: #fff; font-family: Arial, sans-serif; color: #111; display: flex; align-items: center; justify-content: center; min-height: 100vh; }
  .box { width: 360px; padding: 32px; border: 1px solid #ddd; }
  h2 { margin: 0 0 6px; font-size: 18px; font-weight: bold; }
  p { margin: 0 0 16px; font-size: 13px; color: #555; }
  .key { font-family: 'Courier New', monospace; font-size: 20px; letter-spacing: 3px; background: #f5f5f5; border: 1px solid #ccc; padding: 14px 16px; cursor: pointer; user-select: all; margin-bottom: 8px; }
  .key:hover { background: #eee; }
  .hint { font-size: 12px; color: #aaa; margin: 0 0 16px; }
  .timer { font-size: 12px; color: #888; border-top: 1px solid #eee; padding-top: 14px; margin: 0; }
</style>
</head>
<body>
<div class="box">
  <h2>Your key</h2>
  <p>Click to copy, then paste it into the script.</p>
  <div class="key" onclick="copyKey(this)">{{ key }}</div>
  <p class="hint" id="h">click to copy</p>
  <p class="timer">Expires in {{ hours }}h {{ minutes }}m</p>
</div>
<script>
function copyKey(el) {
  navigator.clipboard.writeText(el.textContent.trim());
  var h = document.getElementById('h');
  h.textContent = 'copied!';
  setTimeout(function(){ h.textContent = 'click to copy'; }, 2000);
}
</script>
</body>
</html>"""


ERROR_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Error</title>
<style>
  body { margin: 0; background: #fff; font-family: Arial, sans-serif; color: #111; display: flex; align-items: center; justify-content: center; min-height: 100vh; }
  .box { width: 360px; padding: 32px; border: 1px solid #ddd; }
  h2 { margin: 0 0 8px; font-size: 18px; }
  p { margin: 0; font-size: 13px; color: #555; line-height: 1.6; }
</style>
</head>
<body>
<div class="box">
  <h2>Link expired</h2>
  <p>This link is no longer valid. Request a new one from the Discord bot.</p>
</div>
</body>
</html>"""


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)   
