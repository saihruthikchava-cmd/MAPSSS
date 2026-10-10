"""Campus & City Safe-Route Navigator REST backend.

SQLite is created automatically as waywise.db beside this file.
This is a demo backend: user profiles are stored, but login/authentication is not implemented.
"""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import os
import re
import sqlite3
import urllib.error
import urllib.request
from flask import Flask, jsonify, request, render_template, session
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import secrets
import smtplib
import hashlib
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")
app = Flask(__name__)
# Set WAYWISE_SECRET_KEY in .env or the environment for stable, secure sessions.
app.secret_key = os.environ.get("WAYWISE_SECRET_KEY") or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=os.environ.get("WAYWISE_HTTPS", "0") == "1")
DB_PATH = Path(os.environ.get("WAYWISE_DB_PATH", str(Path(__file__).resolve().parent / "waywise.db")))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
HAZARD_TYPES = {
    "Poor lighting", "Waterlogging", "Accident spot",
    "Road damage / obstruction", "Isolated area", "Unsafe crossing", "Other"
}
FEEDBACK_TYPES = {"Suggestion", "Bug report", "Route feedback", "Map feedback", "Other"}


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db():
    with connect_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL CHECK(length(full_name) <= 100),
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            phone TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS auth_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            email TEXT UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            email_verified INTEGER NOT NULL DEFAULT 1,
            disabled_until TEXT
        );
        CREATE TABLE IF NOT EXISTS auth_pending_registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT NOT NULL UNIQUE,
            username TEXT NOT NULL,
            email TEXT NOT NULL COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS auth_otps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL COLLATE NOCASE,
            purpose TEXT NOT NULL,
            otp_hash TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS hazard_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            type TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS user_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            category TEXT NOT NULL,
            rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_hazards_created ON hazard_reports(created_at);
        CREATE INDEX IF NOT EXISTS idx_feedback_created ON user_feedback(created_at);
        """)
        # Migrate existing databases created before email was added to auth accounts.
        columns = {row[1] for row in db.execute("PRAGMA table_info(auth_accounts)").fetchall()}
        if "email" not in columns:
            db.execute("ALTER TABLE auth_accounts ADD COLUMN email TEXT")
        if "role" not in columns:
            db.execute("ALTER TABLE auth_accounts ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
        if "email_verified" not in columns:
            db.execute("ALTER TABLE auth_accounts ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 1")
        if "disabled_until" not in columns:
            db.execute("ALTER TABLE auth_accounts ADD COLUMN disabled_until TEXT")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_accounts_email ON auth_accounts(email COLLATE NOCASE) WHERE email IS NOT NULL")
        # Bootstrap the requested administrator once. Change ADMIN_PASSWORD before deployment.
        admin_password = os.environ.get("WAYWISE_ADMIN_PASSWORD", "ADMIN1234")
        admin = db.execute("SELECT id FROM auth_accounts WHERE username='ADMIN' COLLATE NOCASE").fetchone()
        if not admin:
            db.execute("INSERT INTO auth_accounts(username,email,password_hash,created_at,role,email_verified) VALUES(?,?,?,?,?,1)",
                       ("ADMIN", os.environ.get("WAYWISE_ADMIN_EMAIL", "admin@localhost"), generate_password_hash(admin_password), now_utc(), "admin"))
        else:
            db.execute("UPDATE auth_accounts SET role='admin', email_verified=1 WHERE username='ADMIN' COLLATE NOCASE")


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None
    return data


@app.get("/")
def index():
    """Serve the WayWise frontend at the root URL."""
    return render_template("index.html")


def _send_otp(email, purpose):
    """Send a short-lived OTP using SMTP settings supplied via environment variables."""
    host = os.environ.get("WAYWISE_SMTP_HOST", "").strip()
    user = os.environ.get("WAYWISE_SMTP_USER", "").strip()
    password = os.environ.get("WAYWISE_SMTP_PASSWORD", "")
    sender = os.environ.get("WAYWISE_SMTP_FROM", user).strip()
    if not host or not user or not password or not sender:
        return False, "Email delivery is not configured. Set WAYWISE_SMTP_HOST, WAYWISE_SMTP_USER, WAYWISE_SMTP_PASSWORD, and WAYWISE_SMTP_FROM."
    otp = f"{secrets.randbelow(1_000_000):06d}"
    digest = hashlib.sha256(otp.encode()).hexdigest()
    created = datetime.now(timezone.utc)
    expires = (created + timedelta(minutes=10)).isoformat(timespec="seconds")
    with connect_db() as db:
        db.execute("DELETE FROM auth_otps WHERE email=? COLLATE NOCASE AND purpose=?", (email, purpose))
        db.execute("INSERT INTO auth_otps(email,purpose,otp_hash,expires_at,created_at) VALUES(?,?,?,?,?)",
                   (email, purpose, digest, expires, created.isoformat(timespec="seconds")))
    label = "verify your WayWise account" if purpose == "register" else "reset your WayWise password"
    msg = EmailMessage()
    msg["Subject"] = "Your WayWise verification code"
    msg["From"] = sender
    msg["To"] = email
    msg.set_content(f"Your code to {label} is: {otp}\n\nIt expires in 10 minutes. If you did not request this, ignore this email.")
    try:
        port = int(os.environ.get("WAYWISE_SMTP_PORT", "587"))
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.starttls()
            smtp.login(user, password)
            smtp.send_message(msg)
    except (OSError, smtplib.SMTPException, ValueError):
        app.logger.exception("Unable to send authentication OTP")
        with connect_db() as db:
            db.execute("DELETE FROM auth_otps WHERE email=? COLLATE NOCASE AND purpose=?", (email, purpose))
        return False, "Could not send the email. Check SMTP settings and try again."
    return True, None


def _valid_otp(email, purpose, otp):
    if not re.fullmatch(r"\d{6}", otp):
        return False
    with connect_db() as db:
        row = db.execute("SELECT * FROM auth_otps WHERE email=? COLLATE NOCASE AND purpose=? ORDER BY id DESC LIMIT 1",
                         (email, purpose)).fetchone()
        if not row or row["attempts"] >= 5:
            return False
        if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
            db.execute("DELETE FROM auth_otps WHERE id=?", (row["id"],))
            return False
        db.execute("UPDATE auth_otps SET attempts=attempts+1 WHERE id=?", (row["id"],))
        return secrets.compare_digest(row["otp_hash"], hashlib.sha256(otp.encode()).hexdigest())


def _admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if session.get("auth_role") != "admin":
            return jsonify(error="Administrator access required."), 403
        return fn(*args, **kwargs)
    return wrapped


@app.get("/admin")
def admin_page():
    if session.get("auth_role") != "admin":
        return render_template("admin.html", needs_login=True), 200
    return render_template("admin.html", needs_login=False), 200


@app.get("/api/auth/status")
def auth_status():
    if session.get("auth_user_id"):
        return jsonify(authenticated=True, username=session.get("auth_username"), role=session.get("auth_role"))
    return jsonify(authenticated=False)


@app.post("/api/auth/register/request-otp")
def auth_register_request_otp():
    data = body()
    if data is None:
        return jsonify(error="Send a JSON object."), 400
    username = str(data.get("username", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,30}", username):
        return jsonify(error="Username must be 3–30 characters and use letters, numbers, dot, underscore, or hyphen."), 400
    if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        return jsonify(error="Enter a valid email address."), 400
    if len(password) < 8 or len(password) > 128:
        return jsonify(error="Password must be between 8 and 128 characters."), 400
    with connect_db() as db:
        if db.execute("SELECT 1 FROM auth_accounts WHERE username=? COLLATE NOCASE", (username,)).fetchone():
            return jsonify(error="That username is already taken."), 409
        if db.execute("SELECT 1 FROM auth_accounts WHERE email=? COLLATE NOCASE", (email,)).fetchone():
            return jsonify(error="That email address is already registered."), 409
    ok, error = _send_otp(email, "register")
    if not ok:
        return jsonify(error=error), 503
    pending_token = secrets.token_urlsafe(32)
    with connect_db() as db:
        db.execute("INSERT INTO auth_pending_registrations(token,username,email,password_hash,expires_at) VALUES(?,?,?,?,?)",
                   (pending_token, username, email, generate_password_hash(password),
                    (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(timespec="seconds")))
    session["pending_register_token"] = pending_token
    return jsonify(message="A 6-digit verification code was sent to your email. It expires in 10 minutes.")


@app.post("/api/auth/register/verify")
def auth_register_verify():
    data = body() or {}
    pending_token = session.get("pending_register_token")
    otp = str(data.get("otp", "")).strip()
    if not pending_token:
        return jsonify(error="Request a new registration code first."), 400
    with connect_db() as db:
        pending = db.execute("SELECT * FROM auth_pending_registrations WHERE token=?", (pending_token,)).fetchone()
    if not pending or datetime.fromisoformat(pending["expires_at"]) < datetime.now(timezone.utc):
        session.pop("pending_register_token", None)
        return jsonify(error="Registration request expired. Please register again."), 400
    if not _valid_otp(pending["email"], "register", otp):
        return jsonify(error="Invalid or expired code. You have up to 5 attempts; request a new code if needed."), 400
    try:
        with connect_db() as db:
            cur = db.execute("INSERT INTO auth_accounts(username,email,password_hash,created_at,role,email_verified) VALUES(?,?,?,?, 'user',1)",
                             (pending["username"], pending["email"], pending["password_hash"], now_utc()))
            user_id = cur.lastrowid
            db.execute("DELETE FROM auth_otps WHERE email=? COLLATE NOCASE AND purpose='register'", (pending["email"],))
            db.execute("DELETE FROM auth_pending_registrations WHERE token=?", (pending_token,))
    except sqlite3.IntegrityError:
        with connect_db() as db:
            db.execute("DELETE FROM auth_pending_registrations WHERE token=?", (pending_token,))
        session.pop("pending_register_token", None)
        return jsonify(error="Username or email is already registered. Try logging in."), 409
    session.clear()
    session["auth_user_id"] = user_id
    session["auth_username"] = pending["username"]
    session["auth_role"] = "user"
    return jsonify(authenticated=True, username=pending["username"], message="Email verified and account created."), 201


@app.post("/api/auth/login")
def auth_login():
    data = body()
    if data is None:
        return jsonify(error="Send a JSON object."), 400
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    with connect_db() as db:
        row = db.execute("SELECT id,username,email,password_hash,role,email_verified,disabled_until FROM auth_accounts WHERE username=? COLLATE NOCASE", (username,)).fetchone()
    if row is None or not check_password_hash(row["password_hash"], password):
        return jsonify(error="Incorrect username or password."), 401
    if row["disabled_until"]:
        try:
            if datetime.fromisoformat(row["disabled_until"]) > datetime.now(timezone.utc):
                return jsonify(error=f"This account is temporarily disabled until {row['disabled_until']} UTC."), 403
        except ValueError:
            pass
    if not row["email_verified"] and row["role"] != "admin":
        return jsonify(error="Verify your email address before logging in."), 403
    session.clear()
    session["auth_user_id"] = row["id"]
    session["auth_username"] = row["username"]
    session["auth_role"] = row["role"]
    return jsonify(authenticated=True, username=row["username"], role=row["role"], message="Logged in successfully.")


@app.post("/api/auth/forgot/request-otp")
def auth_forgot_request_otp():
    data = body() or {}
    email = str(data.get("email", "")).strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        return jsonify(error="Enter a valid email address."), 400
    with connect_db() as db:
        row = db.execute("SELECT id FROM auth_accounts WHERE email=? COLLATE NOCASE AND role='user'", (email,)).fetchone()
    if not row:
        return jsonify(error="If that email belongs to an account, a code can be sent. Check the address or contact support."), 200
    ok, error = _send_otp(email, "reset")
    if not ok:
        return jsonify(error=error), 503
    return jsonify(message="If that email belongs to an account, a 6-digit code has been sent. It expires in 10 minutes.")


@app.post("/api/auth/forgot/reset")
def auth_forgot_reset():
    data = body() or {}
    email = str(data.get("email", "")).strip().lower()
    otp = str(data.get("otp", "")).strip()
    password = str(data.get("password", ""))
    if len(password) < 8 or len(password) > 128:
        return jsonify(error="New password must be between 8 and 128 characters."), 400
    if not _valid_otp(email, "reset", otp):
        return jsonify(error="Invalid or expired code."), 400
    with connect_db() as db:
        cur = db.execute("UPDATE auth_accounts SET password_hash=? WHERE email=? COLLATE NOCASE AND role='user'",
                         (generate_password_hash(password), email))
        db.execute("DELETE FROM auth_otps WHERE email=? COLLATE NOCASE AND purpose='reset'", (email,))
    if cur.rowcount != 1:
        return jsonify(error="Unable to reset password for this account."), 400
    return jsonify(message="Password reset successfully. You can now log in.")


@app.get("/api/admin/accounts")
@_admin_required
def admin_accounts():
    with connect_db() as db:
        rows = db.execute("SELECT id,username,email,created_at,email_verified,disabled_until FROM auth_accounts WHERE role='user' ORDER BY id DESC").fetchall()
    return jsonify([dict(row) for row in rows])


@app.post("/api/admin/accounts/<int:user_id>/disable")
@_admin_required
def admin_disable_account(user_id):
    data = body() or {}
    try:
        hours = int(data.get("hours", 0))
    except (TypeError, ValueError):
        return jsonify(error="Hours must be a whole number."), 400
    if not 1 <= hours <= 8760:
        return jsonify(error="Choose a duration between 1 hour and 365 days."), 400
    until = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(timespec="seconds")
    with connect_db() as db:
        cur = db.execute("UPDATE auth_accounts SET disabled_until=? WHERE id=? AND role='user'", (until, user_id))
    if cur.rowcount != 1:
        return jsonify(error="User account not found."), 404
    return jsonify(message=f"Account disabled until {until} UTC.", disabled_until=until)


@app.post("/api/admin/accounts/<int:user_id>/enable")
@_admin_required
def admin_enable_account(user_id):
    with connect_db() as db:
        cur = db.execute("UPDATE auth_accounts SET disabled_until=NULL WHERE id=? AND role='user'", (user_id,))
    if cur.rowcount != 1:
        return jsonify(error="User account not found."), 404
    return jsonify(message="Account enabled.")


@app.post("/api/auth/logout")
def auth_logout():
    session.clear()
    return jsonify(authenticated=False, message="Logged out.")


@app.get("/api/health")
def health():
    with connect_db() as db:
        db.execute("SELECT 1")
    return jsonify({"status": "ok", "database": "connected", "database_file": DB_PATH.name})


@app.post("/api/users")
def create_user():
    data = body()
    if data is None:
        return jsonify(error="Send a JSON object."), 400
    name = str(data.get("full_name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    phone = str(data.get("phone", "")).strip()
    if not name or len(name) > 100:
        return jsonify(error="full_name is required and must be 100 characters or fewer."), 400
    if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        return jsonify(error="Enter a valid email address."), 400
    if len(phone) > 30:
        return jsonify(error="phone must be 30 characters or fewer."), 400
    created = now_utc()
    try:
        with connect_db() as db:
            cur = db.execute("INSERT INTO users(full_name,email,phone,created_at) VALUES(?,?,?,?)",
                             (name, email, phone, created))
            user_id = cur.lastrowid
    except sqlite3.IntegrityError:
        return jsonify(error="That email address is already registered."), 409
    return jsonify(id=user_id, full_name=name, email=email, phone=phone, created_at=created), 201


@app.get("/api/users/<int:user_id>")
def get_user(user_id):
    with connect_db() as db:
        row = db.execute("SELECT id,full_name,email,phone,created_at FROM users WHERE id=?", (user_id,)).fetchone()
    if row is None:
        return jsonify(error="User not found."), 404
    return jsonify(dict(row))


@app.post("/api/hazards")
def create_hazard():
    if not session.get("auth_user_id"):
        return jsonify(error="Please log in to use this feature."), 401
    data = body()
    if data is None:
        return jsonify(error="Send a JSON object."), 400
    kind = str(data.get("type", "")).strip()
    description = str(data.get("description", "")).strip()
    try:
        lat, lon = float(data.get("lat")), float(data.get("lon"))
        user_id = int(data["user_id"]) if data.get("user_id") not in (None, "") else None
    except (TypeError, ValueError):
        return jsonify(error="lat and lon must be valid numbers; user_id must be an integer."), 400
    if kind not in HAZARD_TYPES:
        return jsonify(error="Choose a valid hazard type."), 400
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return jsonify(error="Coordinates are out of range."), 400
    if len(description) > 500:
        return jsonify(error="description must be 500 characters or fewer."), 400
    created = now_utc()
    try:
        with connect_db() as db:
            cur = db.execute("INSERT INTO hazard_reports(user_id,type,description,lat,lon,created_at) VALUES(?,?,?,?,?,?)",
                             (user_id, kind, description, lat, lon, created))
            report_id = cur.lastrowid
    except sqlite3.IntegrityError:
        return jsonify(error="The specified user_id does not exist."), 400
    return jsonify(id=report_id, user_id=user_id, type=kind, description=description,
                   lat=lat, lon=lon, created_at=created), 201


@app.get("/api/hazards")
def list_hazards():
    with connect_db() as db:
        rows = db.execute("SELECT id,user_id,type,description,lat,lon,created_at FROM hazard_reports ORDER BY id DESC").fetchall()
    return jsonify([dict(row) for row in rows])


@app.post("/api/feedback")
def create_feedback():
    if not session.get("auth_user_id"):
        return jsonify(error="Please log in to use this feature."), 401
    data = body()
    if data is None:
        return jsonify(error="Send a JSON object."), 400
    category = str(data.get("category", "")).strip()
    message = str(data.get("message", "")).strip()
    try:
        rating = int(data.get("rating"))
        user_id = int(data["user_id"]) if data.get("user_id") not in (None, "") else None
    except (TypeError, ValueError):
        return jsonify(error="rating must be an integer from 1 to 5; user_id must be an integer."), 400
    if category not in FEEDBACK_TYPES:
        return jsonify(error="Choose a valid feedback category."), 400
    if not 1 <= rating <= 5:
        return jsonify(error="rating must be from 1 to 5."), 400
    if not message or len(message) > 1000:
        return jsonify(error="message is required and must be 1,000 characters or fewer."), 400
    created = now_utc()
    try:
        with connect_db() as db:
            cur = db.execute("INSERT INTO user_feedback(user_id,category,rating,message,created_at) VALUES(?,?,?,?,?)",
                             (user_id, category, rating, message, created))
            feedback_id = cur.lastrowid
    except sqlite3.IntegrityError:
        return jsonify(error="The specified user_id does not exist."), 400
    return jsonify(id=feedback_id, user_id=user_id, category=category, rating=rating,
                   message=message, created_at=created), 201



def _rule_based_reply(message, history=None):
    """Helpful no-key fallback. Never claims to perform actions the prototype cannot do."""
    q = re.sub(r"\s+", " ", message.casefold()).strip()
    history = history if isinstance(history, list) else []

    if re.search(r"\b(hi|hello|hey|good morning|good afternoon|good evening)\b", q) and len(q) < 70:
        return ("Hi! I’m WayWise, your route and community-safety assistant. I can help with route planning, "
                "map controls, nearby-place searches, hazard reports, voice features, and privacy. What do you need?")
    if re.search(r"\b(thanks|thank you|thx)\b", q):
        return "You’re welcome! If you tell me your goal, I’ll walk you through the next step."
    if re.search(r"\b(capabilities|what can you do|features|help menu|how can you help)\b", q):
        return ("Here’s what I can help with:\n• Plan a route: enter a start and destination, then choose Find my route.\n"
                "• Map: zoom, reset the map, use your location, and view community hazard markers.\n"
                "• Hazards: select a map location, choose a category, add factual details, and submit.\n"
                "• Nearby places: search a place name in the route fields.\n• Voice: tap the microphone to dictate, or use Voice on to hear replies.\n"
                "I cannot dispatch emergency services, verify reports, or guarantee that any route is safe.")
    if re.search(r"\b(sos|emergency|in danger|being followed|threatened|unsafe right now|help me now)\b", q):
        return ("If you may be in immediate danger, move toward a populated, well-lit place if you can do so safely and contact local emergency services or a trusted person. "
                "In India, call 112 for emergencies. WayWise is not an emergency service and cannot send responders or share your location automatically.")
    if re.search(r"\b(route|direction|navigate|destination|travel time|shortest|fastest|how do i go|go to)\b", q):
        return ("To plan a trip:\n1. In FROM, enter your starting point (or choose Use my current location).\n"
                "2. In TO, enter the destination and choose a suggestion if one appears.\n3. Select Find my route.\n"
                "4. Compare the available route options and choose one.\n\nRoute times are estimates, not live-traffic predictions. Check the road conditions yourself and do not interact with the map while driving.")
    if re.search(r"\b(nearby|near me|restaurant|hospital|pharmacy|atm|petrol|gas station|shop|cafe|school|police station)\b", q):
        return ("For a place, type its name or category into the TO field (for example, ‘hospital’ or ‘café’) and choose a search suggestion. "
                "Nearby discovery depends on the map search provider and internet access; this prototype does not guarantee a complete list or opening hours. "
                "For an urgent medical emergency, contact emergency services rather than relying on search results.")
    if re.search(r"\b(hazard|report|waterlogging|poor lighting|road damage|obstruction|unsafe crossing|accident spot|isolated area)\b", q):
        return ("To report a hazard:\n1. Click the relevant location on the map.\n2. Choose the hazard category.\n3. Add a short, factual note without personal accusations or private information.\n4. Submit the community report.\n\nReports may be outdated or unverified. Avoid putting yourself at risk to collect details.")
    if re.search(r"\b(microphone|mic|voice input|speech|not hearing|not recognising|not recognizing|words.*appear|dictation)\b", q):
        return ("For voice input, use an up-to-date Chrome or Edge browser, open the site on localhost or HTTPS, and allow microphone access in the address-bar site settings. "
                "Click the microphone, wait for the ‘Listening’ status, speak clearly, then click it again to finish. If no words appear, check the selected Windows input microphone and internet connection; browser speech recognition may rely on an online service. You can always type instead.")
    if re.search(r"\b(voice reply|speak aloud|read aloud|audio reply|sound)\b", q):
        return "Use the Voice on button in the chat header to enable or disable spoken replies. If there is no sound, check your device volume and browser audio settings."
    if re.search(r"\b(privacy|private|location|track me|data|personal information)\b", q):
        return ("Location permission is optional for this prototype. Only share the location information needed for a route or report. Do not include passwords, personal identifiers, or sensitive details in chat or hazard notes. "
                "This demo does not provide a complete account-security or production privacy system.")
    if re.search(r"\b(map|zoom|fullscreen|marker|layer|reset map|current location)\b", q):
        return ("Use the map controls to zoom, reset the view, switch to fullscreen, or focus on hazard reports. You can click the map to select a hazard-report location. "
                "Use my current location asks your browser for location permission. Map and report data may be incomplete.")
    if re.search(r"\b(not working|broken|error|failed|doesn't work|does not work)\b", q):
        return ("Let’s troubleshoot: refresh the page, confirm the Flask server is running, and check that the site can reach its /api endpoints. "
                "For voice issues, check browser microphone permissions; for route search, check your internet connection. If you share the exact error shown in the page or browser Console, I can help narrow it down.")
    return ("I can help with routes, map controls, nearby-place searches, hazard reporting, voice input, and basic safety. "
            "I may not know the answer to unrelated or highly specific questions in this demo. Try asking ‘How do I plan a route?’, ‘How do I report a hazard?’, or ‘Why is my microphone not working?’")


def _ai_reply(message, history):
    """Optional OpenAI-compatible chat completion. API credentials stay server-side."""
    api_key = os.getenv("WAYWISE_AI_API_KEY", "").strip()
    if not api_key:
        return None
    base_url = os.getenv("WAYWISE_AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("WAYWISE_AI_MODEL", "gpt-4o-mini").strip()
    system_prompt = (
        "You are WayWise, a concise, friendly assistant for a route-planning and community hazard-reporting website. "
        "Explain only features the prototype can actually perform: route form, map controls, place search suggestions, hazard reports, and browser voice chat. "
        "Never claim to book routes, verify hazards, contact authorities, or share location automatically. "
        "For immediate danger, advise contacting local emergency services; in India, 112 is the emergency number. "
        "Do not encourage unsafe travel or expose private data. Clearly state when information is uncertain. Use short steps when helpful."
    )
    messages = [{"role": "system", "content": system_prompt}]
    for item in history[-8:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            messages.append({"role": role, "content": content[:1000]})
    messages.append({"role": "user", "content": message})
    payload = json.dumps({"model": model, "messages": messages, "temperature": 0.4, "max_tokens": 450}).encode("utf-8")
    req = urllib.request.Request(base_url + "/chat/completions", data=payload, headers={
        "Authorization": "Bearer " + api_key,
        "Content-Type": "application/json",
    }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            data = json.loads(response.read().decode("utf-8"))
        answer = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return answer.strip()[:5000] if isinstance(answer, str) and answer.strip() else None
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError, TypeError):
        app.logger.warning("Optional AI provider failed; using built-in assistant.")
        return None


@app.post("/api/chat")
def chat_reply():
    if not session.get("auth_user_id"):
        return jsonify(error="Please log in to use this feature."), 401
    """Context-aware assistant with a dependable fallback and optional server-side AI."""
    data = body()
    if data is None:
        return jsonify(error="Send a JSON object."), 400
    message = str(data.get("message", "")).strip()
    if not message or len(message) > 1000:
        return jsonify(error="Message is required and must be 1,000 characters or fewer."), 400
    raw_history = data.get("history", [])
    history = raw_history if isinstance(raw_history, list) else []
    history = history[-8:]
    reply = _ai_reply(message, history)
    mode = "ai" if reply else "built-in"
    if not reply:
        reply = _rule_based_reply(message, history)
    return jsonify(reply=reply, mode=mode, suggestions=[
        "How do I plan a route?", "How do I report a hazard?", "Why is voice input not working?"
    ])


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5000, debug=False)
else:
    init_db()
