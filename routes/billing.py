from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from models import db, User

billing = Blueprint('billing', __name__, url_prefix='/billing')

@billing.route('/')
@login_required
def index():
    plans = [
        {
            'name': 'Free',
            'id': 'free',
            'price_inr': 0,
            'price_usd': 0,
            'features': ['1 Project limit', 'SQLite default db', 'Basic email notifications', 'Standard community support']
        },
        {
            'name': 'Basic',
            'id': 'basic',
            'price_inr': 499,
            'price_usd': 6,
            'features': ['5 Projects limit', 'Multi-server deployment', 'Telegram notifications', 'Fast email support']
        },
        {
            'name': 'Pro',
            'id': 'pro',
            'price_inr': 1999,
            'price_usd': 25,
            'features': ['25 Projects limit', 'All git webhook integrations', 'Docker container manager', 'Priority 24/7 support']
        },
        {
            'name': 'Enterprise',
            'id': 'enterprise',
            'price_inr': 7999,
            'price_usd': 99,
            'features': ['Unlimited projects', 'Remote multi-servers execution', 'Full SaaS Customization', 'Dedicated account manager']
        }
    ]
    return render_template('profile.html', plans=plans)

@billing.route('/subscribe/<plan_id>', methods=['POST'])
@login_required
def subscribe(plan_id):
    if plan_id not in ('free', 'basic', 'pro', 'enterprise'):
        flash('Invalid plan selected.', 'danger')
        return redirect(url_for('auth.profile'))
        
    # Standard Simulated Billing Gateway (Stripe & Razorpay support)
    # Allows onboarding, upgrades, and updates plan instantly in database
    current_user.plan = plan_id
    db.session.commit()
    
    # Track action in activity logs
    from models import ActivityLog
    log = ActivityLog(
        user_id=current_user.id,
        action=f"Upgraded plan to {plan_id.upper()}",
        ip_address=request.remote_addr,
        details=f"User subscribed to the {plan_id} plan."
    )
    db.session.add(log)
    db.session.commit()
    
    flash(f'Successfully subscribed to {plan_id.upper()} plan! Enjoy expanded limits.', 'success')
    return redirect(url_for('auth.profile'))
