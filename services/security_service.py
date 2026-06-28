"""
security_service.py
-------------------
Multi-level security: event logging, 2FA/TOTP, session binding,
password policy, and IP reputation tracking.
"""

import re
import hmac
import time
import base64
import hashlib
from datetime import datetime, timedelta
from collections import defaultdict


# â”€â”€ Password Policy â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def check_password_strength(password):
    """
    Return (score: int 0-100, errors: list).
    Score >= 60 is acceptable, >= 80 is strong.
    """
    errors = []
    score = 0

    if not password or len(password) < 8:
        errors.append('Minimum 8 characters required')
    else:
        score += 25
        if len(password) >= 12:
            score += 10
        if len(password) >= 16:
            score += 5

    if re.search(r'[A-Z]', password or ''):
        score += 10
    else:
        errors.append('Add at least one uppercase letter')

    if re.search(r'[a-z]', password or ''):
        score += 10
    else:
        errors.append('Add at least one lowercase letter')

    if re.search(r'\d', password or ''):
        score += 15
    else:
        errors.append('Add at least one number')

    if re.search(r'[!@#$%^&*(),.?":{}|<>_\-]', password or ''):
        score += 15
    else:
        errors.append('Add at least one special character')

    if re.search(r'(.)\1{3,}', password or ''):
        errors.append('Avoid repeated characters (e.g., aaaa)')
        score -= 10

    if password and len(password) >= 8:
        common = ['password', '123456', 'admin', 'letmein', 'welcome',
                  'qwerty', 'abc123', 'monkey', 'dragon', 'master']
        if any(c in password.lower() for c in common):
            errors.append('Password contains common patterns')
            score -= 15

    return max(0, min(100, score)), errors


# â”€â”€ 2FA / TOTP â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def generate_totp_secret():
    """Generate a new base32-encoded TOTP secret."""
    try:
        import pyotp
        return pyotp.random_base32()
    except ImportError:
        return base64.b32encode(hashlib.sha256(
            str(time.time()).encode()
        ).digest()[:10]).decode()


def get_totp_uri(secret, email):
    """Get otpauth:// URI for QR code generation."""
    try:
        import pyotp
        return pyotp.totp.TOTP(secret).provisioning_uri(
            name=email, issuer_name='DevSpace'
        )
    except ImportError:
        return None


def verify_totp(secret, code):
    """Verify a TOTP code against the secret."""
    if not secret or not code:
        return False
    try:
        import pyotp
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=1)
    except ImportError:
        return False


def generate_backup_codes(count=8):
    """Generate backup recovery codes (8-digit hex)."""
    import secrets
    return [secrets.token_hex(4).upper() for _ in range(count)]


# â”€â”€ Session Security â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def bind_session(session_obj, ip_address, user_agent=''):
    """Store IP + User-Agent in session for binding verification."""
    session_obj['_ip'] = ip_address
    session_obj['_ua'] = hashlib.sha256(
        (user_agent or '').encode()
    ).hexdigest()[:16]
    session_obj['_bound_at'] = int(time.time())
    session_obj['_sid'] = hashlib.sha256(
        f"{ip_address}{user_agent}{time.time()}".encode()
    ).hexdigest()[:12]
    session_obj.permanent = True


def verify_session_binding(session_obj, ip_address, user_agent=''):
    """
    Verify that the session belongs to the same IP + User-Agent.
    Returns True if valid, False if hijacked.
    """
    bound_ip = session_obj.get('_ip')
    bound_ua = session_obj.get('_ua')
    if not bound_ip:
        return True

    if bound_ip != ip_address:
        return False

    expected_ua = hashlib.sha256(
        (user_agent or '').encode()
    ).hexdigest()[:16]
    if bound_ua != expected_ua:
        return False

    return True


# â”€â”€ Security Event Logging â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def log_event(db, user_id, action, ip_address='', user_agent='',
              details=None, severity='info'):
    """
    Log a security event to the database.

    severity: 'info', 'warning', 'critical'
    action: 'login', 'login_failed', 'logout', '2fa_enabled', '2fa_disabled',
            'password_changed', 'session_revoked', 'smtp_updated',
            'ssh_key_added', 'user_created', 'user_deleted', 'permission_change'
    """
    try:
        from models import SecurityEvent
        event = SecurityEvent(
            user_id=user_id,
            action=action,
            ip_address=ip_address[:45] if ip_address else '',
            user_agent=user_agent[:255] if user_agent else '',
            details=str(details)[:500] if details else None,
            severity=severity,
        )
        db.session.add(event)
        db.session.commit()
    except Exception:
        db.session.rollback()


def get_recent_events(db, limit=50, severity=None, action=None, hours=48):
    """Get recent security events."""
    from models import SecurityEvent
    query = SecurityEvent.query
    since = datetime.utcnow() - timedelta(hours=hours)
    query = query.filter(SecurityEvent.created_at >= since)
    if severity:
        query = query.filter_by(severity=severity)
    if action:
        query = query.filter_by(action=action)
    return query.order_by(SecurityEvent.created_at.desc()).limit(limit).all()


# â”€â”€ IP Reputation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# In-memory store for quick IP reputation checks
_failed_logins = defaultdict(list)  # ip -> [timestamps]

def is_ip_blocked(ip):
    """Check if an IP is temporarily blocked (10+ failures in 30 min)."""
    now = time.time()
    attempts = [t for t in _failed_logins[ip] if now - t < 1800]
    _failed_logins[ip] = attempts
    return len(attempts) >= 10


def record_failed_login(ip):
    """Record a failed login attempt for IP reputation."""
    _failed_logins[ip].append(time.time())
    # Keep only last 30 minutes
    cutoff = time.time() - 1800
    _failed_logins[ip] = [t for t in _failed_logins[ip] if t > cutoff]


def clear_failed_logins(ip):
    """Clear failed login attempts for an IP."""
    _failed_logins.pop(ip, None)


# â”€â”€ Rate limiting helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

SENSITIVE_ACTIONS = defaultdict(list)  # user_id -> [timestamps]

def check_action_rate(user_id, max_per_minute=5):
    """Check if a sensitive action is being performed too frequently."""
    now = time.time()
    actions = [t for t in SENSITIVE_ACTIONS[user_id] if now - t < 60]
    SENSITIVE_ACTIONS[user_id] = actions
    if len(actions) >= max_per_minute:
        return False
    SENSITIVE_ACTIONS[user_id].append(now)
    return True


# â”€â”€ Audit for sensitive operations â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def audit_sensitive(db, user_id, action, target=None, ip='', details=''):
    """
    Log a sensitive action with proper context.
    Returns the created SecurityEvent.
    """
    return log_event(
        db=db,
        user_id=user_id,
        action=action,
        ip_address=ip,
        details=f'{target}: {details}' if target else details,
        severity='warning' if 'failed' in action or 'revoked' in action else 'info',
    )
