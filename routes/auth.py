import re
import time
import hashlib
from datetime import datetime
from collections import defaultdict

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, current_app
from flask_login import login_user, logout_user, login_required, current_user
from models import db, User, UserSession, SecurityEvent
from functools import wraps
from markupsafe import escape, Markup

auth = Blueprint('auth', __name__)

csrf_exempt_views = set()

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role not in ('super_admin', 'admin'):
            flash('Admin access required.', 'danger')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def validate_email(email):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email)


# â”€â”€ Password strength validation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def validate_password_strength(password):
    errors = []
    if len(password) < 8:
        errors.append('Minimum 8 characters required')
    if not re.search(r'[A-Z]', password):
        errors.append('Add at least one uppercase letter')
    if not re.search(r'[a-z]', password):
        errors.append('Add at least one lowercase letter')
    if not re.search(r'\d', password):
        errors.append('Add at least one number')
    if not re.search(r'[!@#$%^&*(),.?":{}|<>_-]', password):
        errors.append('Add at least one special character')
    common = ['password', '123456', 'admin', 'letmein', 'qwerty', 'abc123']
    if any(c in password.lower() for c in common):
        errors.append('Password contains common patterns')
    return errors


# â”€â”€ Brute force / bot attack prevention â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
failed_attempts = defaultdict(list)  # ip -> list of timestamps

def is_ip_locked(ip):
    now = time.time()
    attempts = [t for t in failed_attempts[ip] if now - t < 600]
    failed_attempts[ip] = attempts
    return len(attempts) >= 5

def record_failed_attempt(ip):
    failed_attempts[ip].append(time.time())

def clear_failed_attempts(ip):
    if ip in failed_attempts:
        del failed_attempts[ip]


# â”€â”€ Session binding helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _record_session(user, ip, ua):
    """Record active session in DB and bind it."""
    sid = hashlib.sha256(f'{ip}{ua}{time.time()}{user.id}'.encode()).hexdigest()[:16]
    session['_sid'] = sid
    session['_ip'] = ip
    session['_ua'] = hashlib.sha256((ua or '').encode()).hexdigest()[:16]
    session['_bound_at'] = int(time.time())
    session.permanent = True

    try:
        existing = UserSession.query.filter_by(user_id=user.id, session_id=sid).first()
        if not existing:
            sess = UserSession(user_id=user.id, session_id=sid,
                             ip_address=ip, user_agent=(ua or '')[:255],
                             is_current=True)
            db.session.add(sess)
        else:
            existing.last_active = datetime.utcnow()
        db.session.commit()
    except Exception:
        db.session.rollback()


def _cleanup_old_sessions(user_id, keep=5):
    """Keep only N most recent sessions."""
    try:
        old = UserSession.query.filter_by(user_id=user_id).order_by(
            UserSession.last_active.desc()).offset(keep).all()
        for s in old:
            db.session.delete(s)
        db.session.commit()
    except Exception:
        db.session.rollback()


# â”€â”€ TOTP / 2FA helper â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _verify_2fa(user, code):
    """Verify TOTP code for a user."""
    if not user.tfa_enabled or not user.tfa_secret:
        return True
    try:
        import pyotp
        totp = pyotp.TOTP(user.tfa_secret)
        return totp.verify(code, valid_window=1)
    except ImportError:
        return False


# â”€â”€ Routes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@auth.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.role in ('super_admin', 'admin'):
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('main.dashboard'))

    # Check if user is in 2FA verification step
    if session.get('_2fa_user_id'):
        return _handle_2fa_step()

    if request.method == 'POST':
        client_ip = request.remote_addr or '0.0.0.0'
        ua = request.user_agent.string if request.user_agent else ''

        # Check lockout
        if is_ip_locked(client_ip):
            flash('Too many failed attempts. IP locked for 10 minutes.', 'danger')
            _log_event(None, 'login_blocked', client_ip, ua, f'IP locked: {client_ip}', 'warning')
            return render_template('login.html')

        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        if not email or not password:
            flash('Email and password are required.', 'danger')
            return render_template('login.html')

        if not validate_email(email):
            flash('Invalid email format.', 'danger')
            return render_template('login.html')

        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            clear_failed_attempts(client_ip)

            # If user has 2FA enabled, redirect to 2FA step
            if user.tfa_enabled:
                session['_2fa_user_id'] = user.id
                session['_2fa_ip'] = client_ip
                session['_2fa_ua'] = ua
                return redirect(url_for('auth.login'))

            # Complete login
            login_user(user, remember=True)
            _record_session(user, client_ip, ua)
            _log_event(user.id, 'login', client_ip, ua, 'Success', 'info')

            flash(f'Welcome back, {escape(user.name)}!', 'success')
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            if user.role in ('super_admin', 'admin'):
                return redirect(url_for('admin.dashboard'))
            return redirect(url_for('main.dashboard'))

        record_failed_attempt(client_ip)
        _log_event(None, 'login_failed', client_ip, ua, f'Failed login for {email}', 'warning')
        flash('Invalid email or password.', 'danger')

    return render_template('login.html')


def _handle_2fa_step():
    """Handle the 2FA verification step after password validation."""
    user_id = session.get('_2fa_user_id')
    client_ip = session.get('_2fa_ip', request.remote_addr or '')
    ua = session.get('_2fa_ua', request.user_agent.string if request.user_agent else '')

    user = User.query.get(user_id)
    if not user:
        session.pop('_2fa_user_id', None)
        session.pop('_2fa_ip', None)
        session.pop('_2fa_ua', None)
        flash('Session expired. Please log in again.', 'danger')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        code = request.form.get('totp_code', '').strip()
        if code and _verify_2fa(user, code):
            session.pop('_2fa_user_id', None)
            session.pop('_2fa_ip', None)
            session.pop('_2fa_ua', None)

            login_user(user, remember=True)
            _record_session(user, client_ip, ua)
            _log_event(user.id, 'login', client_ip, ua, 'Success (2FA)', 'info')

            flash(f'Welcome back, {escape(user.name)}!', 'success')
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            if user.role in ('super_admin', 'admin'):
                return redirect(url_for('admin.dashboard'))
            return redirect(url_for('main.dashboard'))
        else:
            _log_event(user.id, '2fa_failed', client_ip, ua, 'Invalid 2FA code', 'warning')
            flash('Invalid verification code. Try again.', 'danger')

    return render_template('login_2fa.html')


def _log_event(user_id, action, ip, ua, details, severity='info'):
    """Log a security event to the database."""
    try:
        event = SecurityEvent(
            user_id=user_id,
            action=action,
            ip_address=ip[:45] if ip else '',
            user_agent=(ua or '')[:255],
            details=str(details)[:500] if details else None,
            severity=severity,
        )
        db.session.add(event)
        db.session.commit()
    except Exception:
        db.session.rollback()


@auth.route('/register', methods=['GET', 'POST'])
def register():
    flash('Direct public registration is disabled for security. Please contact your system administrator to register an account.', 'warning')
    return redirect(url_for('auth.login'))


@auth.route('/logout', methods=['GET', 'POST'])
def logout():
    ip = request.remote_addr or ''
    ua = request.user_agent.string if request.user_agent else ''

    # 1. Clean up DB session record if logged in
    if current_user.is_authenticated:
        sid = session.get('_sid', '')
        try:
            sess = UserSession.query.filter_by(session_id=sid, user_id=current_user.id).first()
            if sess:
                db.session.delete(sess)
                db.session.commit()
        except Exception:
            db.session.rollback()
        try:
            _log_event(current_user.id, 'logout', ip, ua, 'Logout', 'info')
        except Exception:
            pass
        logout_user()

    # 2. Nuke the Flask session completely
    for k in list(session.keys()):
        del session[k]
    session.modified = True

    # 3. Create response & clear Flask-Login remember cookie
    response = redirect(url_for('auth.login'))
    response.delete_cookie('remember_token', path='/')

    # Also ensure Flask-Login's remember flag is gone
    if hasattr(current_user, 'login_remembered'):
        try:
            current_user.login_remembered = False
        except Exception:
            pass

    flash('You have been logged out.', 'info')
    return response


@auth.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')

        if not name:
            flash('Name is required.', 'danger')
            return render_template('profile.html')

        current_user.name = name
        db.session.commit()

        if current_password and new_password:
            if not current_user.check_password(current_password):
                flash('Current password is incorrect.', 'danger')
                return render_template('profile.html')

            errors = validate_password_strength(new_password)
            if errors:
                for e in errors:
                    flash(e, 'danger')
                return render_template('profile.html')

            current_user.set_password(new_password)
            db.session.commit()
            _log_event(current_user.id, 'password_changed', request.remote_addr or '',
                       request.user_agent.string if request.user_agent else '',
                       'Password changed', 'info')
            flash('Password updated successfully.', 'success')

        flash('Profile updated.', 'success')
        return redirect(url_for('auth.profile'))
    
    return render_template('profile.html')


# â”€â”€ Forgot Password / Reset â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@auth.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        user = User.query.filter_by(email=email).first()

        flash('If that email is registered, you will receive a password reset link shortly.', 'info')

        if user:
            try:
                from itsdangerous import URLSafeTimedSerializer
                s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
                token = s.dumps(email, salt='password-reset')

                reset_url = url_for('auth.reset_password', token=token, _external=True)

                body_html = f"""
                <div style="font-family:-apple-system,sans-serif;max-width:560px;margin:28px auto;background:#0c1220;border:1px solid rgba(59,130,246,.15);border-radius:14px;padding:32px;">
                  <div style="text-align:center;margin-bottom:20px;">
                    <div style="font-size:36px;">ðŸ”</div>
                    <h2 style="color:#e8ecf0;font-size:18px;margin:8px 0 4px;">Password Reset Request</h2>
                    <p style="color:#64748b;font-size:13px;">Click the button below to reset your password. This link expires in 30 minutes.</p>
                  </div>
                  <div style="text-align:center;margin:24px 0;">
                    <a href="{reset_url}" style="display:inline-block;padding:12px 28px;background:#3b82f6;color:#fff;border-radius:8px;text-decoration:none;font-weight:600;font-size:14px;">
                      Reset Password
                    </a>
                  </div>
                  <p style="color:#475569;font-size:12px;text-align:center;">
                    If you didn't request this, please ignore this email.<br>
                    DevSpace Â· Automated Security
                  </p>
                </div>
                """
                from services.mail_service import _send_async
                _send_async(current_app._get_current_object(),
                           'Password Reset â€” DevSpace',
                           body_html, [email])
                _log_event(user.id, 'password_reset_requested', request.remote_addr or '',
                          request.user_agent.string if request.user_agent else '',
                          'Password reset email sent', 'info')
            except Exception as e:
                print(f'[auth] Failed to send reset email: {e}')

        return redirect(url_for('auth.login'))

    return render_template('forgot_password.html')


@auth.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    try:
        from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        email = s.loads(token, salt='password-reset', max_age=1800)
    except SignatureExpired:
        flash('Password reset link has expired. Please request a new one.', 'danger')
        return redirect(url_for('auth.forgot_password'))
    except BadSignature:
        flash('Invalid password reset link.', 'danger')
        return redirect(url_for('auth.forgot_password'))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        if not password or not confirm:
            flash('Both fields are required.', 'danger')
            return render_template('reset_password.html', token=token)

        if password != confirm:
            flash('Passwords do not match.', 'danger')
            return render_template('reset_password.html', token=token)

        errors = validate_password_strength(password)
        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('reset_password.html', token=token)

        user.set_password(password)
        db.session.commit()

        _log_event(user.id, 'password_reset', request.remote_addr or '',
                  request.user_agent.string if request.user_agent else '',
                  'Password reset completed', 'info')
        flash('Password has been reset successfully. Please log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('reset_password.html', token=token)


# â”€â”€ Email OTP Login â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_otp_store = {}

import secrets
import time


@auth.route('/send-otp', methods=['POST'])
def send_otp():
    email = request.form.get('email', '').strip()

    if not email or not validate_email(email):
        return jsonify({'ok': False, 'error': 'Invalid email address'})

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({'ok': False, 'error': 'No account found with this email'})

    now = time.time()
    recent = _otp_store.get(email, {})
    otp_count = recent.get('count', 0)
    otp_first = recent.get('first_time', 0)

    if otp_count >= 3 and now - otp_first < 600:
        return jsonify({'ok': False, 'error': 'Too many OTP requests. Try again later.'})

    otp = f'{secrets.randbelow(900000) + 100000}'
    expires = now + 300

    _otp_store[email] = {
        'otp': otp,
        'expires': expires,
        'count': otp_count + 1,
        'first_time': otp_first if otp_first else now,
    }

    try:
        body_html = f"""
        <div style="font-family:-apple-system,sans-serif;max-width:480px;margin:28px auto;background:#0c1220;border:1px solid rgba(59,130,246,.15);border-radius:14px;padding:32px;text-align:center;">
          <div style="font-size:36px;">ðŸ“§</div>
          <h2 style="color:#e8ecf0;font-size:18px;margin:12px 0 4px;">Login OTP</h2>
          <p style="color:#64748b;font-size:13px;">Use the code below to log in to your account. This OTP expires in 5 minutes.</p>
          <div style="margin:24px 0;padding:16px;background:#0e1117;border-radius:10px;border:1px solid rgba(255,255,255,.08);">
            <span style="font-size:36px;font-weight:700;letter-spacing:10px;color:#60a5fa;font-family:monospace;">{otp}</span>
          </div>
          <p style="color:#475569;font-size:12px;">If you didn't request this, please ignore this email.</p>
          <p style="color:#475569;font-size:11px;margin-top:16px;">DevSpace Â· Secure Login</p>
        </div>
        """
        from services.mail_service import _send_async
        _send_async(current_app._get_current_object(),
                   f'Your OTP: {otp} â€” DevSpace',
                   body_html, [email])
        _log_event(user.id, 'otp_sent', request.remote_addr or '',
                  request.user_agent.string if request.user_agent else '',
                  'Login OTP sent', 'info')
        return jsonify({'ok': True})
    except Exception as e:
        print(f'[auth] Failed to send OTP: {e}')
        return jsonify({'ok': False, 'error': 'Failed to send OTP email. Check email configuration.'})


@auth.route('/verify-otp', methods=['POST'])
def verify_otp():
    email = request.form.get('email', '').strip()
    otp = request.form.get('otp', '').strip()

    if not email or not otp:
        return jsonify({'ok': False, 'error': 'Email and OTP are required'}), 400

    stored = _otp_store.get(email)
    if not stored:
        return jsonify({'ok': False, 'error': 'No OTP sent to this email. Request a new one.'}), 400

    if time.time() > stored['expires']:
        _otp_store.pop(email, None)
        return jsonify({'ok': False, 'error': 'OTP has expired. Request a new one.'}), 400

    if stored['otp'] != otp:
        _log_event(None, 'otp_failed', request.remote_addr or '',
                  request.user_agent.string if request.user_agent else '',
                  f'Invalid OTP for {email}', 'warning')
        return jsonify({'ok': False, 'error': 'Invalid OTP code.'}), 400

    _otp_store.pop(email, None)
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({'ok': False, 'error': 'User not found'}), 404

    login_user(user, remember=True)
    client_ip = request.remote_addr or ''
    ua = request.user_agent.string if request.user_agent else ''
    _record_session(user, client_ip, ua)
    _log_event(user.id, 'login', client_ip, ua, 'Success (OTP)', 'info')

    return jsonify({'ok': True, 'redirect': url_for('admin.dashboard') if user.role in ('super_admin', 'admin') else url_for('main.dashboard')})