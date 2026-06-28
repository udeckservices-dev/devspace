"""
monitor_service.py
------------------
Periodically checks all servers for running Python applications.
Sends email alerts when a previously-running app goes down.
State is persisted to a JSON file so it survives restarts.
"""

import os
import json
import time
from datetime import datetime
from pathlib import Path

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'monitor_state.json')

def _state_path():
    return os.path.normpath(STATE_FILE)


def _load_state():
    path = _state_path()
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except:
            pass
    return {'last_check': None, 'previous_services': {}, 'previous_processes': {}}


def _save_state(state):
    path = _state_path()
    try:
        with open(path, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"[monitor] Failed to save state: {e}")


def check_and_alert(app=None):
    """
    Scan all servers for running Python services/processes,
    compare with previous state, and send alerts for anything that stopped.
    Returns a dict with check results.
    """
    import paramiko
    from io import StringIO
    from flask import current_app
    from models import Server, EmailConfig
    from services.crypto_service import decrypt_data
    from services.mail_service import notify_app_down, _get_config

    cfg = _get_config()
    email_enabled = cfg and cfg.enabled and cfg.notify_app_stop

    state = _load_state()
    previous_services = state.get('previous_services', {})
    current_services = {}
    current_processes = {}

    servers = Server.query.all()
    alerts = []
    errors = []

    for svr in servers:
        key = f"{svr.id}:{svr.name}"
        current_services[key] = []
        current_processes[key] = []

        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            password = decrypt_data(svr.password_enc) if svr.password_enc else None
            ssh_key = decrypt_data(svr.ssh_key_enc) if svr.ssh_key_enc else None

            if ssh_key:
                pkey = paramiko.RSAKey.from_private_key(StringIO(ssh_key))
                ssh.connect(svr.ip, port=svr.ssh_port, username=svr.username, pkey=pkey, timeout=10)
            elif password:
                ssh.connect(svr.ip, port=svr.ssh_port, username=svr.username, password=password, timeout=10)
            else:
                errors.append(f"{svr.name}: No credentials")
                continue

            # Get systemd services
            stdin, stdout, stderr = ssh.exec_command(
                r"""systemctl list-units --type=service --all --no-pager 2>/dev/null | awk '/loaded/ {print $1, $3, $4}' | grep -iE 'python|gunicorn|flask|django|app|deploy|DevSpace|celery|daphne|uvicorn|fastapi|smm|webmail|backend|hrms' || echo 'NONE'""",
                timeout=10
            )
            for line in stdout.read().decode('utf-8', errors='replace').splitlines():
                line = line.strip()
                if line == 'NONE' or not line:
                    continue
                parts = line.split(None, 2)
                if len(parts) >= 3:
                    running = 'running' in parts[2]
                    current_services[key].append({
                        'name': parts[0],
                        'status': 'running' if running else 'stopped',
                    })

            # Get running Python process count
            stdin2, stdout2, stderr2 = ssh.exec_command(
                r"""ps aux | grep -E 'python|gunicorn|uvicorn|daphne|celery|manage.py|flask|fastapi' | grep -v grep | grep -v 'python3 -c' | grep -v firewalld | grep -v fail2ban | wc -l""",
                timeout=10
            )
            proc_count = stdout2.read().decode('utf-8', errors='replace').strip()
            current_processes[key] = int(proc_count) if proc_count.isdigit() else 0

            ssh.close()
        except Exception as e:
            current_services[key] = []
            current_processes[key] = 0
            errors.append(f"{svr.name}: {str(e)}")

    # Compare with previous state and generate alerts
    for key, services in current_services.items():
        prev = previous_services.get(key, [])
        prev_map = {s['name']: s['status'] for s in prev}
        curr_map = {s['name']: s['status'] for s in services}

        for s in services:
            svc_name = s['name']
            if s['status'] == 'running':
                continue
            # Service is stopped â€” was it running before?
            if svc_name in prev_map and prev_map[svc_name] == 'running':
                # Was running, now stopped â€” alert!
                server_name = key.split(':', 1)[1] if ':' in key else key
                alerts.append({
                    'server': server_name,
                    'service': svc_name,
                    'type': 'service',
                })
                if email_enabled and app:
                    try:
                        notify_app_down(app, server_name, svc_name, 'service')
                    except Exception as e:
                        print(f"[monitor] Email send failed: {e}")

    # Save current state for next check
    state['last_check'] = datetime.utcnow().isoformat()
    state['previous_services'] = current_services
    state['previous_processes'] = current_processes
    _save_state(state)

    return {
        'ok': True,
        'timestamp': state['last_check'],
        'alerts': alerts,
        'errors': errors,
        'servers_checked': len(servers),
        'email_sent': email_enabled and len(alerts) > 0,
    }


def get_monitor_status():
    """Return the current monitor state without running a check."""
    state = _load_state()
    alerts_count = len(state.get('alerts', []))
    return {
        'last_check': state.get('last_check'),
        'services_tracked': sum(len(v) for v in state.get('previous_services', {}).values()),
        'servers_tracked': len(state.get('previous_services', {})),
    }
