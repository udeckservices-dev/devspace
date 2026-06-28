import os
import urllib.request
import urllib.parse
import json
import threading
from datetime import datetime
from services.mail_service import notify_deploy as mail_notify_deploy, notify_app_control as mail_notify_app_control, _get_config

def _send_telegram(token, chat_id, message):
    def _worker():
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            data = urllib.parse.urlencode({'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML'}).encode('utf-8')
            req = urllib.request.Request(url, data=data)
            with urllib.request.urlopen(req, timeout=10) as response:
                response.read()
        except Exception as e:
            print(f"[notification] Failed to send Telegram: {e}")
            
    threading.Thread(target=_worker, daemon=True).start()

def _send_whatsapp(api_key, phone_number, message):
    def _worker():
        try:
            # Mock or premium HTTP call to a generic WhatsApp API Gateway (e.g. Twilio or similar)
            # For demonstration and extensibility, we write to a standard endpoint or log it
            url = "https://api.twilio.com/2010-04-01/Accounts/" # placeholder for standard gateway
            print(f"[notification] sending WhatsApp message to {phone_number} via API Key {api_key[:6]}...: {message}")
        except Exception as e:
            print(f"[notification] Failed to send WhatsApp: {e}")
            
    threading.Thread(target=_worker, daemon=True).start()

def dispatch_notification(subject, plain_text_msg, html_body=None, project=None, status=None, app=None):
    """Unified notification dispatcher. Sends via Email, Telegram, and WhatsApp depending on configurations."""
    cfg = _get_config()
    if not cfg or not cfg.enabled:
        return
        
    # 1. Telegram
    if cfg.telegram_bot_token and cfg.telegram_chat_id:
        tg_message = f"<b>{subject}</b>\n\n{plain_text_msg}"
        _send_telegram(cfg.telegram_bot_token, cfg.telegram_chat_id, tg_message)
        
    # 2. WhatsApp
    if cfg.whatsapp_api_key and cfg.whatsapp_phone_number:
        _send_whatsapp(cfg.whatsapp_api_key, cfg.whatsapp_phone_number, f"{subject}: {plain_text_msg}")

    # 3. Email (via background thread as implemented in mail_service)
    if app and project and status:
        try:
            mail_notify_deploy(app, project, None, status)
        except Exception as e:
            print(f"[notification] Email notification failed: {e}")

def notify_deploy(app, project, deployment, status: str):
    """Triggers unified deploy notification."""
    # Send Email first (fire-and-forget inside mail_service)
    mail_notify_deploy(app, project, deployment, status)
    
    # Send Telegram / WhatsApp
    emoji = "✅" if status == "success" else "❌"
    subject = f"{emoji} Deployment {status.upper()} — {project.name}"
    msg = (
        f"Project: {project.name}\n"
        f"Status: {status.upper()}\n"
        f"Branch: {project.branch}\n"
        f"Deploy Path: {project.deploy_path}\n"
    )
    if deployment and deployment.commit_message:
        msg += f"Commit: {deployment.commit_message[:100]}"
        
    dispatch_notification(subject, msg, project=project, status=status, app=app)

def notify_app_control(app, project, action: str, success: bool, actor_email: str = None):
    """Triggers unified app control notification."""
    mail_notify_app_control(app, project, action, success, actor_email)
    
    label = action.upper()
    emoji = "🟢" if action == "start" else "🔴" if action == "stop" else "🔄"
    result = "SUCCESS" if success else "FAILED"
    subject = f"{emoji} App {label} — {project.name}"
    msg = (
        f"Project: {project.name}\n"
        f"Action: {label}\n"
        f"Result: {result}\n"
        f"By: {actor_email or 'system'}\n"
    )
    dispatch_notification(subject, msg)

def notify_server_alert(server_name, ip, metric, value, threshold):
    """Server resource usage alert (CPU, Disk, RAM)."""
    subject = f"⚠️ Server Alert: High {metric} on {server_name}"
    msg = (
        f"Server: {server_name} ({ip})\n"
        f"Alert: High {metric} detected!\n"
        f"Current: {value}%\n"
        f"Threshold: {threshold}%\n"
        f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}"
    )
    dispatch_notification(subject, msg)
