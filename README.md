# DevSpace 🚀

**Self-hosted deployment panel** — Push your code with git, DevSpace handles the rest.

Deploy Python, Node.js, and PHP projects to your own VPS with zero CI/CD complexity. Built-in SSH server monitor, AI-powered anomaly detection, and multi-level security.

## Features

- **Git Push Deploy** — Push to a bare repo, post-receive hook auto-deploys
- **Multi-Language** — Python (pip), Node.js (npm), PHP (composer)
- **Live SSH Terminal** — Browse & manage servers directly from the panel
- **AI Monitor** — 24/7 anomaly detection on CPU, memory, disk, processes
- **Python Monitor** — Real-time scanning of all running Python apps on your servers
- **Security Suite** — 2FA/TOTP, session management, IP binding, security event log
- **Email OTP Login** — Passwordless login via email one-time code
- **Forgot Password** — Token-based password reset via email
- **Nginx Reverse Proxy** — One-click SSL + domain setup
- **Dark UI** — Premium dark theme with responsive sidebar layout

## Tech Stack

- **Backend:** Flask + SQLAlchemy + Flask-Login
- **Frontend:** Bootstrap 5 + Chart.js + vanilla JS
- **SSH:** Paramiko
- **Database:** SQLite (default) / MySQL
- **Encryption:** Fernet (AES-128-CBC + HMAC-SHA256)

## Quick Start

```bash
git clone https://github.com/YOUR_USERNAME/devspace.git
cd devspace
pip install -r requirements.txt
cp .env.example .env
python run.py
```

Open http://127.0.0.1:5000 and register your first account.

## Production Deployment

See [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) for VPS setup with systemd + gunicorn.

## License

MIT
