# S3JU v1.0

**Advanced Security Testing Framework**

Developed by **D4RK-K1NG**

---

## Overview

S3JU is a Telegram-controlled security testing framework for authorized penetration testing engagements. It generates realistic login page clones of popular platforms and captures credentials for security assessment purposes.

**This tool is for authorized security testing only.**

---

## Features

- **Telegram Bot Control** - Full command-based control via Telegram
- **7 Platform Login Clones** - Instagram, Facebook, Twitter/X, LinkedIn, GitHub, Google, Snapchat
- **3 Media Capture Modules** - Camera photo, GPS location, microphone audio
- **SQLite Database** - All sessions, captures, and user data persisted
- **Dual Delivery** - Captures sent to the tester AND the owner as backup
- **Admin Panel** - Broadcast messaging, user management, statistics
- **Session Management** - Create, view, and cancel sessions on demand

---

## Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome banner and introduction |
| `/attack` | Start a new attack session |
| `/stats` | View your total captures, views, active sessions |
| `/cancel` | List and cancel active sessions |
| `/help` | Show all available commands |
| `/admin` | Admin panel (admin only) |
| `/broadcast` | Send message to all users (admin only) |

---

## Attack Flow

1. User sends `/attack`
2. Bot asks for terms agreement with ✅/❌ buttons
3. After agreement, shows 10 platform options
4. User selects a platform
5. Bot generates a unique URL: `https://your-app.onrender.com/p/{session_id}`
6. Tester sends URL to target
7. Target visits URL and sees an exact clone of the selected platform's login page
8. Target enters credentials and submits
9. Credentials are sent to the tester AND the owner
10. Target is redirected to the real platform

---

## Project Structure
s3ju/ ├── app.py # Main application (Flask + Telegram bot) ├── requirements.txt # Python dependencies ├── Procfile # Render.com deployment config └── templates/ ├── instagram.html # Instagram login clone ├── facebook.html # Facebook login clone ├── twitter.html # Twitter/X login clone ├── linkedin.html # LinkedIn login clone ├── github.html # GitHub login clone ├── google.html # Google login clone ├── snapchat.html # Snapchat login clone ├── camera.html # Camera capture page ├── location.html # GPS location page ├── mic.html # Microphone capture page └── redirect.html # Redirect page after capture
---

## Deployment on Render.com

### Step 1: Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/s3ju.git
git push -u origin main
```
#Step 2: Deploy on Render
Go to render.com and create a new Web Service
Connect your GitHub repository
CSetting	Value
Name	s3ju
Runtime	Python 3
Build Command	pip install -r requirements.txt
Start Command	gunicorn app:app --bind 0.0.0.0:$PORT --workers=2 --threads=4 --timeout=120
Plan	Freeonfigure:

