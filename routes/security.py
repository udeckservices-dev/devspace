"""
security.py
-----------
Security management blueprint: 2FA setup, session management,
security dashboard, and sensitive-action confirmation.
"""

import hashlib
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from flask_login import login_required, current_user, logout_user

from models import db, User, SecurityEvent, UserSession
from services.security_service import (
    generate_totp_secret, get_totp_uri, verify_totp,
    generate_backup_codes, log_event, get_recent_events,
    bind_session, verify_session_binding,
    is_ip_blocked, check_action_rate,
    check_password_strength,
)

security = Blueprint('security', __name__, url_prefix='/security')


# ── Security Dashboard (admin) ─────────────────────────────────────────────

@security.route('/dashboard')
@login_required
def dashboard():
    if current_user.role not in ('super_admin', 'admin'):
        flash('Admin access required.', 'danger')
        return redirect(url_for('main.dashboard'))

    events = get_recent_events(db, limit=100)
    active_sessions = UserSession.query.filter_by(is_current=True).order_by(
        UserSession.last_active.desc()
    ).limit(20).all()

    critical_count = sum(1 for e in events if e.severity == 'critical')
    warning_count = sum(1 for e in events if e.severity == 'warning')

    return render_template('security/dashboard.html',
                          events=events,
                          active_sessions=active_sessions,
                          critical_count=critical_count,
                          warning_count=warning_count)


@security.route('/events')
@login_required
def events():
    if current_user.role not in ('super_admin', 'admin'):
        return jsonify({'error': 'Unauthorized'}), 403

    from services.security_service import get_recent_events
    hours = request.args.get('hours', 48, type=int)
    events_list = get_recent_events(db, limit=200, hours=hours)

    return jsonify({
        'events': [{
            'id': e.id,
            'user_id': e.user_id,
            'action': e.action,
            'severity': e.severity,
            'ip_address': e.ip_address,
            'details': e.details,
            'created_at': e.created_at.isoformat() if e.created_at else None,
        } for e in events_list]
    })


# ── 2FA Setup ──────────────────────────────────────────────────────────────

@security.route('/2fa/setup', methods=['GET', 'POST'])
@login_required
def twofa_setup():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'enable':
            code = request.form.get('code', '').strip()
            secret = session.get('_2fa_secret')
            if not secret:
                flash('Session expired. Please start again.', 'danger')
                return redirect(url_for('security.twofa_setup'))

            if not code or not verify_totp(secret, code):
                flash('Invalid verification code. Try again.', 'danger')
                return render_template('security/2fa_setup.html', step='verify')

            current_user.tfa_secret = secret
            current_user.tfa_enabled = True
            db.session.commit()

            log_event(db, current_user.id, '2fa_enabled',
                     ip_address=request.remote_addr,
                     user_agent=request.user_agent.string,
                     severity='info')

            session.pop('_2fa_secret', None)
            flash('Two-factor authentication has been enabled!', 'success')
            return redirect(url_for('security.dashboard'))

        elif action == 'disable':
            if not current_user.tfa_enabled:
                flash('2FA is not enabled.', 'info')
                return redirect(url_for('security.dashboard'))

            code = request.form.get('code', '').strip()
            if not code or not verify_totp(current_user.tfa_secret, code):
                flash('Invalid verification code.', 'danger')
                return render_template('security/2fa_setup.html', step='disable')

            current_user.tfa_secret = None
            current_user.tfa_enabled = False
            db.session.commit()

            log_event(db, current_user.id, '2fa_disabled',
                     ip_address=request.remote_addr,
                     user_agent=request.user_agent.string,
                     severity='warning')

            flash('Two-factor authentication has been disabled.', 'info')
            return redirect(url_for('security.dashboard'))

    # GET: show setup page
    if current_user.tfa_enabled:
        return render_template('security/2fa_setup.html', step='manage')

    secret = generate_totp_secret()
    session['_2fa_secret'] = secret
    uri = get_totp_uri(secret, current_user.email)

    return render_template('security/2fa_setup.html',
                          step='setup',
                          secret=secret,
                          uri=uri,
                          email=current_user.email)


@security.route('/2fa/generate-codes')
@login_required
def generate_codes_route():
    if not current_user.tfa_enabled:
        return jsonify({'error': '2FA not enabled'}), 400

    codes = generate_backup_codes()
    current_user.tfa_backup_codes = ','.join(codes)
    db.session.commit()

    return jsonify({'codes': codes})


# ── Session Management ─────────────────────────────────────────────────────

@security.route('/sessions')
@login_required
def list_sessions():
    sessions = UserSession.query.filter_by(user_id=current_user.id).order_by(
        UserSession.last_active.desc()
    ).all()

    current_sid = session.get('_sid', '')
    return render_template('security/sessions.html',
                          sessions=sessions,
                          current_sid=current_sid)


@security.route('/sessions/revoke/<int:session_id>', methods=['POST'])
@login_required
def revoke_session(session_id):
    sess = UserSession.query.get_or_404(session_id)
    if sess.user_id != current_user.id and current_user.role not in ('super_admin', 'admin'):
        return jsonify({'error': 'Unauthorized'}), 403

    sid_to_check = session.get('_sid', '')
    if sess.session_id == sid_to_check:
        return jsonify({'error': 'Cannot revoke current session'}), 400

    db.session.delete(sess)
    db.session.commit()

    log_event(db, current_user.id, 'session_revoked',
             ip_address=request.remote_addr,
             details=f'Session {sess.session_id[:8]}... revoked',
             severity='warning')

    return jsonify({'ok': True})


@security.route('/sessions/revoke-all', methods=['POST'])
@login_required
def revoke_all_sessions():
    current_sid = session.get('_sid', '')
    others = UserSession.query.filter(
        UserSession.user_id == current_user.id,
        UserSession.session_id != current_sid
    ).all()

    for s in others:
        db.session.delete(s)

    db.session.commit()

    log_event(db, current_user.id, 'session_revoked',
             ip_address=request.remote_addr,
             details=f'Revoked {len(others)} other session(s)',
             severity='warning')

    return jsonify({'ok': True, 'count': len(others)})
