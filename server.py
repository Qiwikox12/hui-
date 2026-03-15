from flask import Flask, request, jsonify, render_template_string, redirect
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
            label      TEXT DEFAULT '',
            ip         TEXT NOT NULL DEFAULT '',
            pt         TEXT DEFAULT '',
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


# ── Public routes ────────────────────────────────────────────────────────────

@app.route("/")
def index():
    ip = get_ip()
    cleanup_expired()
    conn = get_db()
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
    conn.execute("DELETE FROM pass_tokens WHERE token=?", (pt,))
    cleanup_expired()
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


# ── Admin routes ─────────────────────────────────────────────────────────────

def admin_auth():
    return request.args.get("s") == ADMIN_SECRET or request.form.get("s") == ADMIN_SECRET


@app.route("/admin")
def admin():
    if not admin_auth():
        return "Forbidden", 403
    cleanup_expired()
    conn = get_db()
    rows = conn.execute("SELECT * FROM keys ORDER BY created_at DESC").fetchall()
    conn.close()
    now = int(time.time())
    keys = [{
        "id": r["id"],
        "key": r["key"],
        "label": r["label"] or "",
        "ip": r["ip"] or "—",
        "expires_at": r["expires_at"],
        "expires_h": max(0, r["expires_at"] - now) // 3600,
        "expires_m": (max(0, r["expires_at"] - now) % 3600) // 60,
    } for r in rows]
    s = ADMIN_SECRET
    return render_template_string(ADMIN_PAGE, keys=keys, s=s, total=len(keys))


@app.route("/admin/delete/<int:key_id>", methods=["POST"])
def admin_delete(key_id):
    if not admin_auth():
        return "Forbidden", 403
    conn = get_db()
    conn.execute("DELETE FROM keys WHERE id=?", (key_id,))
    conn.commit()
    conn.close()
    return redirect(f"/admin?s={ADMIN_SECRET}")


@app.route("/admin/delete_all", methods=["POST"])
def admin_delete_all():
    if not admin_auth():
        return "Forbidden", 403
    conn = get_db()
    conn.execute("DELETE FROM keys")
    conn.commit()
    conn.close()
    return redirect(f"/admin?s={ADMIN_SECRET}")


@app.route("/admin/create", methods=["POST"])
def admin_create():
    if not admin_auth():
        return "Forbidden", 403
    custom_key = request.form.get("key", "").strip().upper()
    label = request.form.get("label", "").strip()
    days = int(request.form.get("days", 1))
    if not custom_key:
        custom_key = make_key()
    now = int(time.time())
    expires = now + days * 86400
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO keys (key, label, ip, pt, created_at, expires_at) VALUES (?,?,?,?,?,?)",
            (custom_key, label, "admin", "admin", now, expires)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()
    return redirect(f"/admin?s={ADMIN_SECRET}")


# ── Pages ─────────────────────────────────────────────────────────────────────

LANDING_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Key System</title>
<script src="https://publisher.linkvertise.com/cdn/linkvertise.js"></script>
<script>linkvertise(4260771, {whitelist: [], blacklist: [""]});</script>
<style>
  body{margin:0;background:#fff;font-family:Arial,sans-serif;color:#111;display:flex;align-items:center;justify-content:center;min-height:100vh}
  .box{width:360px;padding:32px;border:1px solid #ddd}
  h2{margin:0 0 6px;font-size:18px}
  p{margin:0 0 24px;font-size:13px;color:#555;line-height:1.5}
  a.btn{display:block;background:#111;color:#fff;text-align:center;padding:11px;font-size:14px;text-decoration:none}
  a.btn:hover{background:#333}
  .note{margin:12px 0 0;font-size:12px;color:#aaa;text-align:center}
</style>
</head>
<body>
<div class="box">
  <h2>Get your key</h2>
  <p>Complete a short task to receive your 24-hour key.<br>Next visit your key appears automatically.</p>
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
  body{margin:0;background:#fff;font-family:Arial,sans-serif;color:#111;display:flex;align-items:center;justify-content:center;min-height:100vh}
  .box{width:360px;padding:32px;border:1px solid #ddd}
  h2{margin:0 0 6px;font-size:18px}
  p{margin:0 0 16px;font-size:13px;color:#555}
  .key{font-family:'Courier New',monospace;font-size:20px;letter-spacing:3px;background:#f5f5f5;border:1px solid #ccc;padding:14px 16px;cursor:pointer;user-select:all;margin-bottom:8px}
  .key:hover{background:#eee}
  .hint{font-size:12px;color:#aaa;margin:0 0 16px}
  .timer{font-size:12px;color:#888;border-top:1px solid #eee;padding-top:14px;margin:0}
</style>
</head>
<body>
<div class="box">
  <h2>Your key</h2>
  <p>Click to copy, then paste into the script.</p>
  <div class="key" onclick="copyKey(this)">{{ key }}</div>
  <p class="hint" id="h">click to copy</p>
  <p class="timer">Expires in {{ hours }}h {{ minutes }}m</p>
</div>
<script>
function copyKey(el){
  navigator.clipboard.writeText(el.textContent.trim());
  var h=document.getElementById('h');
  h.textContent='copied!';
  setTimeout(function(){h.textContent='click to copy'},2000);
}
</script>
</body>
</html>"""

ERROR_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Error</title>
<style>
  body{margin:0;background:#fff;font-family:Arial,sans-serif;color:#111;display:flex;align-items:center;justify-content:center;min-height:100vh}
  .box{width:360px;padding:32px;border:1px solid #ddd}
  h2{margin:0 0 8px;font-size:18px}
  p{margin:0;font-size:13px;color:#555}
  a{color:#111}
</style>
</head>
<body>
<div class="box">
  <h2>Link expired</h2>
  <p>This link is no longer valid. <a href="/">Go back</a>.</p>
</div>
</body>
</html>"""

ADMIN_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin</title>
<style>
  *{box-sizing:border-box}
  body{margin:0;font-family:Arial,sans-serif;font-size:14px;background:#f7f7f7;color:#111}
  .top{background:#fff;border-bottom:1px solid #ddd;padding:14px 24px;display:flex;align-items:center;gap:16px}
  .top h1{margin:0;font-size:16px;font-weight:bold}
  .stat{font-size:13px;color:#555}
  .wrap{padding:24px}
  .card{background:#fff;border:1px solid #ddd;padding:20px;margin-bottom:20px}
  .card h3{margin:0 0 14px;font-size:14px;font-weight:bold}
  table{width:100%;border-collapse:collapse}
  th{text-align:left;font-size:12px;color:#888;font-weight:normal;padding:6px 8px;border-bottom:1px solid #eee}
  td{padding:7px 8px;border-bottom:1px solid #f0f0f0;font-size:13px}
  tr:last-child td{border-bottom:none}
  .key-val{font-family:'Courier New',monospace;font-size:13px}
  .label{display:inline-block;background:#f0f0f0;padding:2px 7px;font-size:11px}
  form{display:inline}
  .del{background:none;border:none;color:#c00;cursor:pointer;font-size:12px;padding:0}
  .del:hover{text-decoration:underline}
  .form-row{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px}
  input[type=text],input[type=number]{border:1px solid #ccc;padding:7px 10px;font-size:13px;width:160px}
  input[type=number]{width:70px}
  .btn-create{background:#111;color:#fff;border:none;padding:8px 16px;cursor:pointer;font-size:13px}
  .btn-create:hover{background:#333}
  .btn-danger{background:#fff;color:#c00;border:1px solid #c00;padding:7px 14px;cursor:pointer;font-size:13px}
  .btn-danger:hover{background:#fff0f0}
</style>
</head>
<body>
<div class="top">
  <h1>Admin panel</h1>
  <span class="stat">{{ total }} active key{{ 's' if total != 1 else '' }}</span>
</div>
<div class="wrap">

  <div class="card">
    <h3>Create key</h3>
    <form method="POST" action="/admin/create">
      <input type="hidden" name="s" value="{{ s }}">
      <div class="form-row">
        <input type="text" name="key" placeholder="Custom key (optional)">
        <input type="text" name="label" placeholder="Label (e.g. pighubkey)">
        <input type="number" name="days" value="1" min="1" max="365"> days
        <button class="btn-create" type="submit">Create</button>
      </div>
    </form>
  </div>

  <div class="card">
    <h3>
      Keys
      <form method="POST" action="/admin/delete_all" style="display:inline;float:right">
        <input type="hidden" name="s" value="{{ s }}">
        <button class="btn-danger" type="submit" onclick="return confirm('Delete all keys?')">Delete all</button>
      </form>
    </h3>
    {% if keys %}
    <table>
      <tr>
        <th>Key</th>
        <th>Label</th>
        <th>IP</th>
        <th>Expires in</th>
        <th></th>
      </tr>
      {% for k in keys %}
      <tr>
        <td class="key-val">{{ k.key }}</td>
        <td>{% if k.label %}<span class="label">{{ k.label }}</span>{% else %}—{% endif %}</td>
        <td>{{ k.ip }}</td>
        <td>{{ k.expires_h }}h {{ k.expires_m }}m</td>
        <td>
          <form method="POST" action="/admin/delete/{{ k.id }}">
            <input type="hidden" name="s" value="{{ s }}">
            <button class="del" type="submit">delete</button>
          </form>
        </td>
      </tr>
      {% endfor %}
    </table>
    {% else %}
    <p style="color:#aaa;font-size:13px;margin:0">No active keys.</p>
    {% endif %}
  </div>

</div>
</body>
</html>"""


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
