"""
monitor_engine.py
-----------------
24/7 AI-powered monitoring engine.
Collects CPU, memory, disk, and process metrics from all servers
every N seconds, detects anomalies using statistical analysis,
and sends intelligent email alerts.

Run as a standalone daemon:
    python services/monitor_engine.py

Or via systemd:
    systemctl start DevSpace-monitor
"""

import os, sys, json, time, math, threading
from datetime import datetime, timedelta
from collections import deque


# â”€â”€ Ensure project root is on sys.path â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_PROJ = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)

os.environ.setdefault('FLASK_ENV', 'production')
os.environ.setdefault('USE_SQLITE', 'true')

from models import db, Server, MonitorMetric, MonitorAnomaly, MonitorConfig, EmailConfig
from services.mail_service import _send_async, _admin_emails
from services.crypto_service import decrypt_data

# â”€â”€ Config defaults (overridden from MonitorConfig DB row) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
INTERVAL_SEC  = 60
CPU_WARN      = 75.0
CPU_CRIT      = 90.0
MEM_WARN      = 75.0
MEM_CRIT      = 90.0
DISK_WARN     = 80.0
DISK_CRIT     = 92.0

# Rolling window for baseline calculation
BASELINE_WINDOW = 30  # number of data points


def _load_config():
    """Load MonitorConfig from DB into module globals."""
    global INTERVAL_SEC, CPU_WARN, CPU_CRIT, MEM_WARN, MEM_CRIT, DISK_WARN, DISK_CRIT
    try:
        cfg = MonitorConfig.query.first()
        if cfg:
            INTERVAL_SEC = cfg.interval_sec or 60
            CPU_WARN     = cfg.cpu_warn  or 75
            CPU_CRIT     = cfg.cpu_crit  or 90
            MEM_WARN     = cfg.mem_warn  or 75
            MEM_CRIT     = cfg.mem_crit  or 90
            DISK_WARN    = cfg.disk_warn or 80
            DISK_CRIT    = cfg.disk_crit or 92
    except Exception:
        pass


# â”€â”€ SSH helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _ssh_connect(server):
    try:
        import paramiko
        from io import StringIO
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        password = decrypt_data(server.password_enc) if server.password_enc else None
        ssh_key = decrypt_data(server.ssh_key_enc) if server.ssh_key_enc else None
        if ssh_key:
            pkey = paramiko.RSAKey.from_private_key(StringIO(ssh_key))
            ssh.connect(server.ip, port=server.ssh_port, username=server.username,
                        pkey=pkey, timeout=15)
        else:
            ssh.connect(server.ip, port=server.ssh_port, username=server.username,
                        password=password, timeout=15)
        return ssh
    except Exception as e:
        return None


def _exec(ssh, cmd):
    try:
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=10)
        return stdout.read().decode('utf-8', errors='replace').strip()
    except Exception:
        return ''


def _collect_metrics(ssh):
    """Collect CPU%, memory%, disk%, loadavg, process count from a server."""
    cpu = 0.0
    mem = 0.0
    disk = 0.0
    load1 = 0.0
    procs = 0

    out = _exec(ssh, "cat /proc/stat | head -1")
    if out:
        parts = out.split()
        if len(parts) >= 5:
            try:
                total = sum(int(v) for v in parts[1:])
                idle = int(parts[4])
                # Read again after a brief pause for delta
                time.sleep(0.3)
                out2 = _exec(ssh, "cat /proc/stat | head -1")
                if out2:
                    parts2 = out2.split()
                    if len(parts2) >= 5:
                        total2 = sum(int(v) for v in parts2[1:])
                        idle2 = int(parts2[4])
                        delta_total = total2 - total
                        delta_idle = idle2 - idle
                        if delta_total > 0:
                            cpu = round(100.0 * (delta_total - delta_idle) / delta_total, 1)
            except (ValueError, IndexError):
                pass

    out = _exec(ssh, "free -m | awk '/Mem:/ {print $2, $3}'")
    if out:
        parts = out.split()
        if len(parts) >= 2:
            try:
                total_mem = float(parts[0])
                used_mem = float(parts[1])
                if total_mem > 0:
                    mem = round(100.0 * used_mem / total_mem, 1)
            except (ValueError, IndexError):
                pass

    out = _exec(ssh, "df / | awk 'NR==2 {print $5}' | tr -d '%'")
    if out:
        try:
            disk = float(out)
        except (ValueError, IndexError):
            pass

    out = _exec(ssh, "cat /proc/loadavg | awk '{print $1}'")
    if out:
        try:
            load1 = float(out)
        except (ValueError, IndexError):
            pass

    out = _exec(ssh, "ps aux | wc -l")
    if out:
        try:
            procs = int(out)
        except (ValueError, IndexError):
            pass

    return cpu, mem, disk, load1, procs


# â”€â”€ Anomaly Detection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _baseline(server_id, metric_attr, window=BASELINE_WINDOW):
    """Compute mean and std deviation of recent metric values."""
    rows = (MonitorMetric.query
            .filter_by(server_id=server_id)
            .order_by(MonitorMetric.created_at.desc())
            .limit(window)
            .all())
    if len(rows) < 3:
        return None, None

    vals = [getattr(r, metric_attr) for r in rows if getattr(r, metric_attr) is not None]
    if not vals:
        return None, None

    n = len(vals)
    mean = sum(vals) / n
    variance = sum((v - mean) ** 2 for v in vals) / n
    std = math.sqrt(variance)
    return mean, std


def _check_anomaly(server_id, metric_type, value, warn_thresh, crit_thresh):
    """Check if a metric value exceeds thresholds or deviates from baseline."""
    anomalies = []

    # Threshold-based alerts
    if value >= crit_thresh:
        anomalies.append({
            'metric_type': metric_type,
            'severity': 'critical',
            'title': f'Critical {metric_type.upper()} usage',
            'message': f'{metric_type.upper()} usage is {value}% (threshold: {crit_thresh}%)',
            'value': value,
            'threshold': crit_thresh,
        })
    elif value >= warn_thresh:
        anomalies.append({
            'metric_type': metric_type,
            'severity': 'warning',
            'title': f'High {metric_type.upper()} usage',
            'message': f'{metric_type.upper()} usage is {value}% (threshold: {warn_thresh}%)',
            'value': value,
            'threshold': warn_thresh,
        })

    # Baseline deviation check (z-score > 3)
    mean, std = _baseline(server_id, f'{metric_type}_pct')
    if mean is not None and std > 1 and len(MonitorMetric.query.filter_by(server_id=server_id).all()) >= 10:
        z = (value - mean) / std if std > 0 else 0
        if z > 3:
            anomalies.append({
                'metric_type': metric_type,
                'severity': 'warning' if value < crit_thresh else 'critical',
                'title': f'Unusual {metric_type.upper()} spike detected',
                'message': (f'{metric_type.upper()} jumped to {value}% '
                           f'(avg: {mean:.1f}%, std: {std:.1f}, z-score: {z:.1f})'),
                'value': value,
                'threshold': round(mean + 3 * std, 1),
            })

    return anomalies


def _check_trend(server_id):
    """Detect gradual trends (e.g., memory leak)."""
    insights = []
    rows = (MonitorMetric.query
            .filter_by(server_id=server_id)
            .order_by(MonitorMetric.created_at.desc())
            .limit(15)
            .all())

    if len(rows) >= 10:
        recent_vals = [r.memory_pct for r in rows if r.memory_pct is not None]
        if len(recent_vals) >= 10:
            first_half = sum(recent_vals[len(recent_vals)//2:]) / len(recent_vals[len(recent_vals)//2:])
            second_half = sum(recent_vals[:len(recent_vals)//2]) / len(recent_vals[:len(recent_vals)//2])
            if second_half - first_half > 10:
                insights.append({
                    'metric_type': 'memory',
                    'severity': 'warning',
                    'title': 'Gradual memory increase detected',
                    'message': (f'Memory usage rose from {first_half:.1f}% to {second_half:.1f}% '
                               f'in recent checks â€” possible memory leak'),
                    'value': round(second_half, 1),
                    'threshold': round(first_half, 1),
                })

        cpu_vals = [r.cpu_pct for r in rows if r.cpu_pct is not None]
        if len(cpu_vals) >= 10:
            c_first = sum(cpu_vals[len(cpu_vals)//2:]) / len(cpu_vals[len(cpu_vals)//2:])
            c_second = sum(cpu_vals[:len(cpu_vals)//2]) / len(cpu_vals[:len(cpu_vals)//2])
            if c_second - c_first > 20:
                insights.append({
                    'metric_type': 'cpu',
                    'severity': 'warning',
                    'title': 'CPU usage trending upward',
                    'message': (f'CPU rose from {c_first:.1f}% to {c_second:.1f}% '
                               f'in recent checks'),
                    'value': round(c_second, 1),
                    'threshold': round(c_first, 1),
                })

    return insights


def _is_recent_anomaly(server_id, metric_type, minutes=10):
    """Check if a similar anomaly was reported recently (dedup)."""
    recent = (MonitorAnomaly.query
              .filter_by(server_id=server_id, metric_type=metric_type, resolved_at=None)
              .filter(MonitorAnomaly.created_at >= datetime.utcnow() - timedelta(minutes=minutes))
              .first())
    return recent is not None


# â”€â”€ Alert helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _send_alert(app, server, anomaly, metrics=None):
    """Send intelligent alert email with AI analysis."""
    prefix = 'Critical' if anomaly['severity'] == 'critical' else 'Warning'
    subject = f'[{prefix}] {anomaly["title"]} on {server.name}'

    extra = ''
    if metrics:
        extra = (
            f'<div class="section">'
            f'<div class="section-title">Current Server State</div>'
            f'<div class="info-grid">'
            f'<div class="info-item"><div class="info-label">CPU</div>'
            f'<div class="info-value {"danger" if metrics[0] >= CPU_CRIT else "warning" if metrics[0] >= CPU_WARN else ""}">{metrics[0]}%</div></div>'
            f'<div class="info-item"><div class="info-label">Memory</div>'
            f'<div class="info-value {"danger" if metrics[1] >= MEM_CRIT else "warning" if metrics[1] >= MEM_WARN else ""}">{metrics[1]}%</div></div>'
            f'<div class="info-item"><div class="info-label">Disk</div>'
            f'<div class="info-value {"danger" if metrics[2] >= DISK_CRIT else "warning" if metrics[2] >= DISK_WARN else ""}">{metrics[2]}%</div></div>'
            f'<div class="info-item"><div class="info-label">Processes</div>'
            f'<div class="info-value">{metrics[4]}</div></div>'
            f'</div></div>'
        )

    body = f"""
    <div class="section">
      <div class="section-title">AI Analysis</div>
      <div class="alert-box">
        <p><strong>ðŸ¤– Detected:</strong> {anomaly['message']}</p>
        <p><strong>ðŸ–¥ Server:</strong> {server.name} ({server.ip})</p>
        <p><strong>â± Time:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
      </div>
    </div>
    {extra}
    <div class="section">
      <div class="section-title">Impact & Recommended Action</div>
      <div class="alert-box">
        <p>ðŸ” <strong>Investigate:</strong> SSH into {server.name} and check:</p>
        <p style="font-family:monospace;background:rgba(0,0,0,.3);padding:8px 12px;border-radius:6px;color:#e8ecf0;font-size:13px;">
          htop<br>
          free -m<br>
          df -h<br>
          journalctl -xe -n 50
        </p>
        <p>ðŸ”„ <strong>{'Immediate action recommended' if anomaly["severity"] == "critical" else 'Monitor closely'}</strong></p>
        <p>ðŸ“Š <strong>AI Insight:</strong> This alert was triggered by {'threshold violation' if anomaly["threshold"] == crit_thresh else 'statistical anomaly'} in {anomaly["metric_type"].upper()} usage.</p>
      </div>
    </div>
    """

    alert_style = """
    <style>
      body { margin:0;padding:0;background:#04060a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; }
      .wrap { max-width:600px;margin:28px auto;background:#0c1220;border:1px solid rgba(59,130,246,.15);border-radius:14px;overflow:hidden;box-shadow:0 8px 32px rgba(0,0,0,.5); }
      .alert-banner { background:linear-gradient(135deg,rgba(59,130,246,.18),rgba(59,130,246,.06));padding:28px 32px 22px;text-align:center;border-bottom:1px solid rgba(59,130,246,.12); }
      .alert-banner.crit { background:linear-gradient(135deg,rgba(239,68,68,.18),rgba(239,68,68,.06)); }
      .alert-banner .icon { font-size:42px;line-height:1;margin-bottom:8px; }
      .alert-banner h1 { margin:0;font-size:20px;font-weight:700;color:#60a5fa;letter-spacing:-.3px; }
      .alert-banner.crit h1 { color:#f87171; }
      .alert-banner p { margin:6px 0 0;font-size:13px;color:#94a3b8; }
      .section { padding:22px 32px 18px;border-bottom:1px solid rgba(255,255,255,.05); }
      .section-title { font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#475569;margin-bottom:14px; }
      .info-grid { display:grid;grid-template-columns:1fr 1fr;gap:10px 24px; }
      .info-label { font-size:11px;color:#475569;margin-bottom:2px;text-transform:uppercase;letter-spacing:.5px; }
      .info-value { font-size:14px;color:#e8ecf0;font-family:monospace;font-weight:500; }
      .info-value.danger { color:#f87171; }
      .info-value.warning { color:#fbbf24; }
      .alert-box { background:rgba(59,130,246,.06);border:1px solid rgba(59,130,246,.12);border-radius:10px;padding:16px 20px;margin-top:4px; }
      .alert-box p { margin:0 0 8px;font-size:13px;color:#94a3b8;line-height:1.6; }
      .alert-box p:last-child { margin-bottom:0; }
      .alert-box strong { color:#60a5fa; }
      .footer { padding:18px 32px;background:rgba(255,255,255,.02);font-size:11px;color:#334155; }
    </style>
    """

    is_crit = anomaly['severity'] == 'critical'
    html = f"""<!DOCTYPE html><html><head>{alert_style}</head><body>
<div class="wrap">
  <div class="alert-banner {'crit' if is_crit else ''}">
    <div class="icon">{'ðŸš¨' if is_crit else 'âš ï¸'}</div>
    <h1>{'Critical Alert' if is_crit else 'Warning'}</h1>
    <p>{anomaly['title']}</p>
  </div>
  {body}
  <div class="footer">
    <strong>DevSpace AI Monitor</strong> &nbsp;Â·&nbsp; 24/7 Monitoring &nbsp;Â·&nbsp; {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
  </div>
</div></body></html>"""

    cfg = EmailConfig.query.first()
    if not cfg or not cfg.monitor_recipients:
        cfg2 = EmailConfig.query.first()
        recipients = _admin_emails(cfg) if cfg else []
    else:
        recipients = [e.strip() for e in cfg.monitor_recipients.split(',') if e.strip()]

    if recipients:
        _send_async(app, subject, html, recipients)


# â”€â”€ Main Engine â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_engine_app = None


def check_server(app, server, store_metrics=True):
    """Collect metrics from one server, detect anomalies, return state."""
    ssh = _ssh_connect(server)
    if not ssh:
        return None

    try:
        cpu, mem, disk, load1, procs = _collect_metrics(ssh)
    finally:
        try:
            ssh.close()
        except Exception:
            pass

    metric = MonitorMetric(
        server_id=server.id,
        cpu_pct=cpu,
        memory_pct=mem,
        disk_pct=disk,
        load_1m=load1,
        proc_count=procs,
        is_healthy=cpu < CPU_CRIT and mem < MEM_CRIT and disk < DISK_CRIT,
    )

    if store_metrics:
        try:
            db.session.add(metric)
            db.session.commit()
        except Exception:
            db.session.rollback()

    # Anomaly detection
    all_anomalies = []
    for mtype, val, w, c in [
        ('cpu', cpu, CPU_WARN, CPU_CRIT),
        ('memory', mem, MEM_WARN, MEM_CRIT),
        ('disk', disk, DISK_WARN, DISK_CRIT),
    ]:
        anomalies = _check_anomaly(server.id, mtype, val, w, c)
        for a in anomalies:
            if not _is_recent_anomaly(server.id, mtype):
                anomaly = MonitorAnomaly(
                    server_id=server.id,
                    metric_type=a['metric_type'],
                    severity=a['severity'],
                    title=a['title'],
                    message=a['message'],
                    value=a['value'],
                    threshold=a['threshold'],
                )
                db.session.add(anomaly)
                all_anomalies.append((server, a, (cpu, mem, disk, load1, procs)))

    # Trend detection
    trends = _check_trend(server.id)
    for a in trends:
        if not _is_recent_anomaly(server.id, a['metric_type'], minutes=30):
            anomaly = MonitorAnomaly(
                server_id=server.id,
                metric_type=a['metric_type'],
                severity=a['severity'],
                title=a['title'],
                message=a['message'],
                value=a['value'],
                threshold=a['threshold'],
            )
            db.session.add(anomaly)
            all_anomalies.append((server, a, (cpu, mem, disk, load1, procs)))

    # Commit anomalies
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[monitor-engine] DB commit error: {e}", flush=True)

    # Send alerts
    for svr, anomaly_data, m in all_anomalies:
        try:
            _send_alert(app, svr, anomaly_data, metrics=m)
        except Exception:
            pass

    return metric


def run_once(app):
    """Run a single monitoring cycle for all servers."""
    _load_config()
    servers = Server.query.all()
    results = []
    for svr in servers:
        try:
            m = check_server(app, svr)
            if m:
                results.append({'server': svr.name, 'ip': svr.ip, 'healthy': m.is_healthy})
        except Exception as e:
            results.append({'server': svr.name, 'ip': svr.ip, 'error': str(e)})
    return results


def run_forever(app):
    """Run monitoring in an infinite loop (for daemon use)."""
    global _engine_app
    _engine_app = app

    print(f"[monitor-engine] Starting 24/7 monitoring (interval: {INTERVAL_SEC}s)", flush=True)
    print(f"[monitor-engine] Thresholds â€” CPU: warn>{CPU_WARN}% crit>{CPU_CRIT}%, "
          f"Mem: warn>{MEM_WARN}% crit>{MEM_CRIT}%, "
          f"Disk: warn>{DISK_WARN}% crit>{DISK_CRIT}%", flush=True)

    while True:
        loop_start = time.time()
        try:
            with app.app_context():
                _load_config()
                results = run_once(app)
                healthy = sum(1 for r in results if r.get('healthy'))
                total = len(results)
                print(f"[monitor-engine] [{datetime.utcnow().strftime('%H:%M:%S')}] "
                      f"Scanned {total} server{'s' if total != 1 else ''}, "
                      f"{healthy} healthy, {total - healthy} issues", flush=True)
        except Exception as e:
            print(f"[monitor-engine] Error: {e}", flush=True)
            import traceback
            traceback.print_exc()

        elapsed = time.time() - loop_start
        sleep_for = max(1, INTERVAL_SEC - elapsed)
        time.sleep(sleep_for)


# â”€â”€ CLI entry point â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
    from app import create_app
    application = create_app('production')
    with application.app_context():
        db.create_all()
    print(f"[monitor-engine] DevSpace AI Monitor Engine starting (PID: {os.getpid()})...", flush=True)
    run_forever(application)
