"""
mail_service.py
---------------
Sends notification emails for deploy events and app control actions.
Config is loaded from the EmailConfig DB row (set by admin).
All sends are fire-and-forget in a background thread so they never
block the web request.
"""

import threading
from datetime import datetime


def _get_config():
    """Load EmailConfig from DB. Returns None if not configured."""
    try:
        from models import EmailConfig
        return EmailConfig.query.first()
    except Exception:
        return None


def _build_mailer(cfg):
    """Return a configured Flask-Mail Mail instance, or None on failure."""
    try:
        from flask_mail import Mail
        from flask import current_app
        current_app.config.update(
            MAIL_SERVER   = cfg.smtp_host,
            MAIL_PORT     = cfg.smtp_port,
            MAIL_USE_TLS  = cfg.use_tls,
            MAIL_USE_SSL  = cfg.use_ssl,
            MAIL_USERNAME = cfg.smtp_user,
            MAIL_PASSWORD = cfg.smtp_password,
            MAIL_DEFAULT_SENDER = (cfg.from_name, cfg.from_email),
        )
        return Mail(current_app)
    except Exception:
        return None


def _send_async(app, subject, html_body, recipients):
    """Send email in a background thread so it never blocks a request."""
    def _worker():
        with app.app_context():
            cfg = _get_config()
            if not cfg or not cfg.enabled or not cfg.smtp_host or not cfg.from_email:
                return
            try:
                from flask_mail import Mail, Message
                app.config.update(
                    MAIL_SERVER   = cfg.smtp_host,
                    MAIL_PORT     = cfg.smtp_port,
                    MAIL_USE_TLS  = cfg.use_tls,
                    MAIL_USE_SSL  = cfg.use_ssl,
                    MAIL_USERNAME = cfg.smtp_user,
                    MAIL_PASSWORD = cfg.smtp_password,
                    MAIL_DEFAULT_SENDER = (cfg.from_name or 'DevSpace', cfg.from_email),
                )
                mail = Mail(app)
                msg  = Message(subject=subject,
                               recipients=recipients,
                               html=html_body)
                with app.extensions.get('mail', mail).connect() as conn:
                    conn.send(msg)
            except Exception as e:
                print(f"[mail] Failed to send '{subject}': {e}")

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


def _admin_emails(cfg):
    """Return list of admin email addresses."""
    from models import User
    if not cfg or not cfg.notify_admin:
        return []
    admins = User.query.filter_by(role='admin').all()
    return [u.email for u in admins if u.email]


# â”€â”€ Email templates â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_BASE_STYLE = """
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background:#0e1117; color:#e8ecf0; margin:0; padding:0; }
  .wrap { max-width:560px; margin:32px auto; background:#181d28;
          border:1px solid rgba(255,255,255,.08); border-radius:12px; overflow:hidden; }
  .header { padding:24px 28px; border-bottom:1px solid rgba(255,255,255,.08); }
  .header h2 { margin:0; font-size:18px; }
  .body { padding:24px 28px; }
  .row { display:flex; gap:12px; margin-bottom:10px; font-size:14px; }
  .label { color:#4e5768; width:120px; flex-shrink:0; }
  .val { color:#e8ecf0; font-family:monospace; word-break:break-all; }
  .badge { display:inline-block; padding:3px 10px; border-radius:99px;
           font-size:12px; font-weight:700; }
  .badge-success { background:rgba(34,197,94,.15); color:#22c55e; }
  .badge-danger  { background:rgba(248,113,113,.15); color:#f87171; }
  .badge-blue    { background:rgba(96,165,250,.15);  color:#60a5fa; }
  .badge-yellow  { background:rgba(251,191,36,.15);  color:#fbbf24; }
  .footer { padding:16px 28px; border-top:1px solid rgba(255,255,255,.06);
            font-size:12px; color:#4e5768; }
  .logs { background:#0e1117; border:1px solid rgba(255,255,255,.08);
          border-radius:8px; padding:14px 16px; font-family:monospace;
          font-size:12px; color:#8b95a5; white-space:pre-wrap;
          max-height:260px; overflow:hidden; margin-top:14px; }
</style>
"""


def _wrap(header_html, body_html):
    ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    return f"""<!DOCTYPE html><html><head>{_BASE_STYLE}</head><body>
<div class="wrap">
  <div class="header">{header_html}</div>
  <div class="body">{body_html}</div>
  <div class="footer">DevSpace &nbsp;Â·&nbsp; {ts}</div>
</div></body></html>"""


# â”€â”€ Public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def notify_deploy(app, project, deployment, status: str):
    """
    Send deploy notification to project owner + admin.
    status: 'success' | 'failed'
    """
    cfg = _get_config()
    if not cfg or not cfg.enabled:
        return
    if status == 'success' and not cfg.notify_deploy_success:
        return
    if status == 'failed' and not cfg.notify_deploy_fail:
        return

    ok      = status == 'success'
    emoji   = 'âœ…' if ok else 'âŒ'
    badge   = f'<span class="badge badge-{"success" if ok else "danger"}">{status.upper()}</span>'
    subject = f'{emoji} Deploy {status.upper()} â€” {project.name}'

    # Truncate logs to last 40 lines
    log_text = ''
    if deployment and deployment.logs:
        lines = deployment.logs.strip().splitlines()
        log_text = '\n'.join(lines[-40:])

    body = f"""
    <div class="row"><span class="label">Project</span><span class="val">{project.name}</span></div>
    <div class="row"><span class="label">Status</span><span class="val">{badge}</span></div>
    <div class="row"><span class="label">Branch</span><span class="val">{project.branch}</span></div>
    <div class="row"><span class="label">Deploy Path</span><span class="val">{project.deploy_path}</span></div>
    {f'<div class="row"><span class="label">Commit</span><span class="val">{deployment.commit_message[:80]}</span></div>' if deployment and deployment.commit_message else ''}
    {f'<div class="logs">{log_text}</div>' if log_text else ''}
    """

    header = f'<h2>{emoji} Deployment {status.upper()}</h2>'
    html   = _wrap(header, body)

    # Collect recipients: project owner + admins
    recipients = set()
    if project.user and project.user.email:
        recipients.add(project.user.email)
    for e in _admin_emails(cfg):
        recipients.add(e)

    if recipients:
        _send_async(app, subject, html, list(recipients))


def notify_app_control(app, project, action: str, success: bool, actor_email: str = None):
    """
    Send notification when app is started/stopped/restarted.
    action: 'start' | 'stop' | 'restart'
    """
    cfg = _get_config()
    if not cfg or not cfg.enabled:
        return
    if action in ('start',) and not cfg.notify_app_start:
        return
    if action in ('stop',) and not cfg.notify_app_stop:
        return

    action_labels = {'start': 'Started', 'stop': 'Stopped', 'restart': 'Restarted'}
    emojis        = {'start': 'ðŸŸ¢', 'stop': 'ðŸ”´', 'restart': 'ðŸ”„'}
    badge_cls     = {'start': 'success', 'stop': 'danger', 'restart': 'blue'}

    label  = action_labels.get(action, action.title())
    emoji  = emojis.get(action, 'âš™ï¸')
    bcls   = badge_cls.get(action, 'blue')
    status = 'OK' if success else 'FAILED'
    badge  = f'<span class="badge badge-{bcls}">{label}</span>'

    subject = f'{emoji} App {label} â€” {project.name}'
    body = f"""
    <div class="row"><span class="label">Project</span><span class="val">{project.name}</span></div>
    <div class="row"><span class="label">Action</span><span class="val">{badge}</span></div>
    <div class="row"><span class="label">Result</span>
      <span class="val"><span class="badge badge-{'success' if success else 'danger'}">{status}</span></span>
    </div>
    {f'<div class="row"><span class="label">By</span><span class="val">{actor_email}</span></div>' if actor_email else ''}
    {f'<div class="row"><span class="label">Service</span><span class="val">{project.service_name}</span></div>' if project.service_name else ''}
    """

    header = f'<h2>{emoji} App {label} â€” {project.name}</h2>'
    html   = _wrap(header, body)

    recipients = set()
    if project.user and project.user.email:
        recipients.add(project.user.email)
    for e in _admin_emails(cfg):
        recipients.add(e)

    if recipients:
        _send_async(app, subject, html, list(recipients))


_ALERT_STYLE = """
<style>
  body { margin:0; padding:0; background:#04060a; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; }
  .wrap { max-width:600px; margin:28px auto; background:#0c1220; border:1px solid rgba(239,68,68,.15); border-radius:14px; overflow:hidden; box-shadow:0 8px 32px rgba(0,0,0,.5); }

  .alert-banner { background:linear-gradient(135deg,rgba(239,68,68,.18),rgba(239,68,68,.06)); padding:28px 32px 22px; text-align:center; border-bottom:1px solid rgba(239,68,68,.12); }
  .alert-banner .icon { font-size:42px; line-height:1; margin-bottom:8px; }
  .alert-banner h1 { margin:0; font-size:20px; font-weight:700; color:#f87171; letter-spacing:-.3px; }
  .alert-banner p { margin:6px 0 0; font-size:13px; color:#94a3b8; }

  .section { padding:22px 32px 18px; border-bottom:1px solid rgba(255,255,255,.05); }
  .section:last-child { border-bottom:none; }
  .section-title { font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:1px; color:#475569; margin-bottom:14px; }
  .info-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px 24px; }
  .info-item { }
  .info-label { font-size:11px; color:#475569; margin-bottom:2px; text-transform:uppercase; letter-spacing:.5px; }
  .info-value { font-size:14px; color:#e8ecf0; font-family:'SFMono-Regular',Consolas,monospace; font-weight:500; word-break:break-all; }
  .info-value.danger { color:#f87171; }
  .info-value.success { color:#22c55e; }
  .info-value.warning { color:#fbbf24; }
  .info-value.muted { color:#64748b; }

  .status-badge { display:inline-block; padding:4px 14px; border-radius:99px; font-size:12px; font-weight:700; background:rgba(239,68,68,.15); color:#f87171; border:1px solid rgba(239,68,68,.25); }

  .alert-box { background:rgba(239,68,68,.06); border:1px solid rgba(239,68,68,.12); border-radius:10px; padding:16px 20px; margin-top:4px; }
  .alert-box p { margin:0 0 8px; font-size:13px; color:#94a3b8; line-height:1.6; }
  .alert-box p:last-child { margin-bottom:0; }
  .alert-box strong { color:#f87171; }

  .footer { padding:18px 32px; background:rgba(255,255,255,.02); font-size:11px; color:#334155; }
  .footer strong { color:#64748b; }
</style>
"""

def _alert_wrap(html_body):
    ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    return f"""<!DOCTYPE html><html><head>{_ALERT_STYLE}</head><body>
<div class="wrap">
  <div class="alert-banner">
    <div class="icon">ðŸš¨</div>
    <h1>Application Down Alert</h1>
    <p>Critical â€” immediate attention required</p>
  </div>
  {html_body}
  <div class="footer">
    <strong>DevSpace</strong> &nbsp;Â·&nbsp; Monitor Service &nbsp;Â·&nbsp; {ts} &nbsp;Â·&nbsp;
    This is an automated alert â€” do not reply directly.
  </div>
</div></body></html>"""


def notify_app_down(app, server_name: str, app_name: str, app_type: str = 'service'):
    """Send alert when a monitored app/service goes down."""
    cfg = _get_config()
    if not cfg or not cfg.enabled or not cfg.notify_app_stop:
        return

    type_label = 'Systemd Service' if app_type == 'service' else 'Python Process'
    subject = f'ðŸš¨ CRITICAL: {app_name} stopped on {server_name}'

    body = f"""
    <div class="section">
      <div class="section-title">What Happened</div>
      <div class="alert-box">
        <p>
          <strong>ðŸš¨ {app_name}</strong> â€” a monitored {type_label.lower()} â€” was
          previously running on <strong>{server_name}</strong> but is now
          <strong>STOPPED</strong>. This requires immediate investigation.
        </p>
        <p>
          â± Detected at: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}
        </p>
      </div>
    </div>

    <div class="section">
      <div class="section-title">Affected Resource</div>
      <div class="info-grid">
        <div class="info-item">
          <div class="info-label">Server</div>
          <div class="info-value">{server_name}</div>
        </div>
        <div class="info-item">
          <div class="info-label">Application</div>
          <div class="info-value">{app_name}</div>
        </div>
        <div class="info-item">
          <div class="info-label">Type</div>
          <div class="info-value">{type_label}</div>
        </div>
        <div class="info-item">
          <div class="info-label">Status</div>
          <div class="info-value danger"><span class="status-badge">â›” STOPPED</span></div>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="section-title">Impact</div>
      <div class="info-grid">
        <div class="info-item">
          <div class="info-label">Service Unavailable</div>
          <div class="info-value muted">End users cannot access this application</div>
        </div>
        <div class="info-item">
          <div class="info-label">Business Impact</div>
          <div class="info-value muted">Potential downtime â€” check immediately</div>
        </div>
        <div class="info-item">
          <div class="info-label">Last Known</div>
          <div class="info-value muted">Previously running (now crashed/stopped)</div>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="section-title">Recommended Actions</div>
      <div class="alert-box">
        <p>ðŸ” <strong>Investigate:</strong> SSH into <strong>{server_name}</strong> and check service status with:</p>
        <p style="font-family:monospace; background:rgba(0,0,0,.3); padding:8px 12px; border-radius:6px; margin-bottom:12px; color:#e8ecf0; font-size:13px;">
          systemctl status {app_name}<br>
          journalctl -u {app_name} -n 50 --no-pager
        </p>
        <p>ðŸ”„ <strong>Restart:</strong> Try bringing the service back up:</p>
        <p style="font-family:monospace; background:rgba(0,0,0,.3); padding:8px 12px; border-radius:6px; margin-bottom:8px; color:#e8ecf0; font-size:13px;">
          sudo systemctl restart {app_name}
        </p>
        <p>ðŸ“‹ <strong>Prevent recurrence:</strong> Check logs for crash patterns and consider setting up auto-restart (Restart=always in systemd).</p>
      </div>
    </div>
    """

    html = _alert_wrap(body)

    recipients = set()
    if cfg.monitor_recipients:
        for email in cfg.monitor_recipients.split(','):
            email = email.strip()
            if email:
                recipients.add(email)
    if not recipients:
        for e in _admin_emails(cfg):
            recipients.add(e)

    if recipients:
        _send_async(app, subject, html, list(recipients))


def send_test_email(app, to_email: str) -> dict:
    """Send a test email synchronously. Returns {'ok', 'error'}."""
    cfg = _get_config()
    if not cfg or not cfg.smtp_host or not cfg.from_email:
        return {'ok': False, 'error': 'Email not configured.'}
    try:
        from flask_mail import Mail, Message
        app.config.update(
            MAIL_SERVER   = cfg.smtp_host,
            MAIL_PORT     = cfg.smtp_port,
            MAIL_USE_TLS  = cfg.use_tls,
            MAIL_USE_SSL  = cfg.use_ssl,
            MAIL_USERNAME = cfg.smtp_user,
            MAIL_PASSWORD = cfg.smtp_password,
            MAIL_DEFAULT_SENDER = (cfg.from_name or 'DevSpace', cfg.from_email),
        )
        mail = Mail(app)
        html = _wrap(
            '<h2>âœ… Test Email</h2>',
            '<p style="color:#8b95a5;">DevSpace email is configured correctly!</p>'
        )
        msg = Message(subject='âœ… DevSpace â€” Test Email',
                      recipients=[to_email], html=html)
        with app.app_context():
            mail.send(msg)
        return {'ok': True, 'error': None}
    except Exception as e:
        return {'ok': False, 'error': str(e)}
