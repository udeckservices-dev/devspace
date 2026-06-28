import re
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
from markupsafe import escape
from models import db, User, Project, Deployment, EmailConfig

admin = Blueprint('admin', __name__, url_prefix='/admin')

@admin.route('/')
@login_required
def dashboard():
    if current_user.role != 'admin':
        flash('Admin access required.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    total_users = User.query.count()
    total_projects = Project.query.count()
    total_deployments = Deployment.query.count()
    
    recent_deployments = Deployment.query.order_by(Deployment.created_at.desc()).limit(10).all()
    all_projects = Project.query.order_by(Project.created_at.desc()).limit(10).all()
    
    users = User.query.all()
    plan_stats = {'free': 0, 'basic': 0, 'pro': 0}
    for user in users:
        plan_stats[user.plan] += 1
    
    return render_template('admin/dashboard.html',
                         total_users=total_users,
                         total_projects=total_projects,
                         total_deployments=total_deployments,
                         recent_deployments=recent_deployments,
                         all_projects=all_projects,
                         plan_stats=plan_stats)

@admin.route('/users')
@login_required
def users():
    if current_user.role != 'admin':
        flash('Admin access required.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)

@admin.route('/users/add', methods=['GET', 'POST'])
@login_required
def add_user():
    if current_user.role != 'admin':
        flash('Admin access required.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'user')
        plan = request.form.get('plan', 'free')
        
        if not all([name, email, password]):
            flash('All fields are required.', 'danger')
            return render_template('admin/add_user.html')
        
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            flash('Invalid email format.', 'danger')
            return render_template('admin/add_user.html')
        
        if User.query.filter_by(email=email).first():
            flash('Email already exists.', 'danger')
            return render_template('admin/add_user.html')
        
        from services.git_service import create_user_home_dir, get_user_home_dir
        user = User(name=name, email=email, role=role, plan=plan)
        user.set_password(password)

        # Auto-assign home directory path
        user.home_dir = get_user_home_dir(name)

        db.session.add(user)
        db.session.commit()

        # Create the folder on disk
        result = create_user_home_dir(name)
        if result['success']:
            flash(f'User created. Home folder: {escape(result["path"])}', 'success')
        else:
            flash(f'User created but home folder setup failed: {escape(str(result["error"]))}', 'warning')

        return redirect(url_for('admin.users'))
    
    return render_template('admin/add_user.html')

@admin.route('/users/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    if current_user.role != 'admin':
        flash('Admin access required.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    user = User.query.get_or_404(user_id)
    
    if request.method == 'POST':
        user.name = request.form.get('name', '').strip()
        user.email = request.form.get('email', '').strip()
        user.role = request.form.get('role', 'user')
        user.plan = request.form.get('plan', 'free')
        
        new_password = request.form.get('new_password', '')
        if new_password:
            if len(new_password) < 8 or not re.search(r'[A-Za-z]', new_password) or not re.search(r'\d', new_password):
                flash('Password must be at least 8 characters with a letter and a number.', 'danger')
                return render_template('admin/edit_user.html', user=user)
            user.set_password(new_password)
        
        if not all([user.name, user.email]):
            flash('Name and email are required.', 'danger')
            return render_template('admin/edit_user.html', user=user)
        
        existing = User.query.filter(User.email == user.email, User.id != user_id).first()
        if existing:
            flash('Email already in use.', 'danger')
            return render_template('admin/edit_user.html', user=user)
        
        db.session.commit()
        flash('User updated successfully.', 'success')
        return redirect(url_for('admin.users'))
    
    return render_template('admin/edit_user.html', user=user)

@admin.route('/users/delete/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if current_user.role != 'admin':
        flash('Admin access required.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    if user_id == current_user.id:
        flash('Cannot delete your own account.', 'danger')
        return redirect(url_for('admin.users'))
    
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    
    flash('User deleted successfully.', 'success')
    return redirect(url_for('admin.users'))

@admin.route('/projects')
@login_required
def all_projects():
    if current_user.role != 'admin':
        flash('Admin access required.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    projects = Project.query.order_by(Project.created_at.desc()).all()
    return render_template('admin/projects.html', projects=projects)

@admin.route('/deployments')
@login_required
def all_deployments():
    if current_user.role != 'admin':
        flash('Admin access required.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    deployments = Deployment.query.order_by(Deployment.created_at.desc()).limit(50).all()
    return render_template('admin/deployments.html', deployments=deployments)

@admin.route('/deployments/<int:deployment_id>')
@login_required
def deployment_detail(deployment_id):
    if current_user.role != 'admin':
        flash('Admin access required.', 'danger')
        return redirect(url_for('main.dashboard'))

    deployment = Deployment.query.get_or_404(deployment_id)
    return render_template('admin/deployment_detail.html', deployment=deployment)


# Ã¢â€â‚¬Ã¢â€â‚¬ Email configuration Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

@admin.route('/email-config', methods=['GET', 'POST'])
@login_required
def email_config():
    if current_user.role != 'admin':
        flash('Admin access required.', 'danger')
        return redirect(url_for('main.dashboard'))

    cfg = EmailConfig.query.first()
    if not cfg:
        cfg = EmailConfig()
        db.session.add(cfg)
        db.session.commit()

    if request.method == 'POST':
        cfg.enabled      = request.form.get('enabled') == 'on'
        cfg.smtp_host    = request.form.get('smtp_host', '').strip() or None
        cfg.smtp_port    = int(request.form.get('smtp_port', 587) or 587)
        cfg.smtp_user    = request.form.get('smtp_user', '').strip() or None
        smtp_pass        = request.form.get('smtp_password', '')
        if smtp_pass:                          # only update if a new value provided
            cfg.smtp_password = smtp_pass
        cfg.use_tls      = request.form.get('use_tls') == 'on'
        cfg.use_ssl      = request.form.get('use_ssl') == 'on'
        cfg.from_name    = request.form.get('from_name', 'DevSpace').strip() or 'DevSpace'
        cfg.from_email   = request.form.get('from_email', '').strip() or None
        cfg.notify_deploy_success = request.form.get('notify_deploy_success') == 'on'
        cfg.monitor_recipients = request.form.get('monitor_recipients', '').strip() or None

        db.session.commit()
        flash('Email config saved.', 'success')
        return redirect(url_for('admin.email_config'))

    return render_template('admin/email_config.html', cfg=cfg)


@admin.route('/')
@login_required
def dashboard():
    if current_user.role != 'admin':
        flash('Admin access required.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    total_users = User.query.count()
    total_projects = Project.query.count()
    total_deployments = Deployment.query.count()
    
    recent_deployments = Deployment.query.order_by(Deployment.created_at.desc()).limit(10).all()
    all_projects = Project.query.order_by(Project.created_at.desc()).limit(10).all()
    
    users = User.query.all()
    plan_stats = {'free': 0, 'basic': 0, 'pro': 0}
    for user in users:
        plan_stats[user.plan] += 1
    
    return render_template('admin/dashboard.html',
                         total_users=total_users,
                         total_projects=total_projects,
                         total_deployments=total_deployments,
                         recent_deployments=recent_deployments,
                         all_projects=all_projects,
                         plan_stats=plan_stats)

@admin.route('/users')
@login_required
def users():
    if current_user.role != 'admin':
        flash('Admin access required.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)

@admin.route('/users/add', methods=['GET', 'POST'])
@login_required
def add_user():
    if current_user.role != 'admin':
        flash('Admin access required.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'user')
        plan = request.form.get('plan', 'free')
        
        if not all([name, email, password]):
            flash('All fields are required.', 'danger')
            return render_template('admin/add_user.html')
        
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            flash('Invalid email format.', 'danger')
            return render_template('admin/add_user.html')
        
        if User.query.filter_by(email=email).first():
            flash('Email already exists.', 'danger')
            return render_template('admin/add_user.html')
        
        from services.git_service import create_user_home_dir, get_user_home_dir
        user = User(name=name, email=email, role=role, plan=plan)
        user.set_password(password)

        # Auto-assign home directory path
        user.home_dir = get_user_home_dir(name)

        db.session.add(user)
        db.session.commit()

        # Create the folder on disk
        result = create_user_home_dir(name)
        if result['success']:
            flash(f'User created. Home folder: {escape(result["path"])}', 'success')
        else:
            flash(f'User created but home folder setup failed: {escape(str(result["error"]))}', 'warning')

        return redirect(url_for('admin.users'))
    
    return render_template('admin/add_user.html')

@admin.route('/users/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    if current_user.role != 'admin':
        flash('Admin access required.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    user = User.query.get_or_404(user_id)
    
    if request.method == 'POST':
        user.name = request.form.get('name', '').strip()
        user.email = request.form.get('email', '').strip()
        user.role = request.form.get('role', 'user')
        user.plan = request.form.get('plan', 'free')
        
        new_password = request.form.get('new_password', '')
        if new_password:
            if len(new_password) < 8 or not re.search(r'[A-Za-z]', new_password) or not re.search(r'\d', new_password):
                flash('Password must be at least 8 characters with a letter and a number.', 'danger')
                return render_template('admin/edit_user.html', user=user)
            user.set_password(new_password)
        
        if not all([user.name, user.email]):
            flash('Name and email are required.', 'danger')
            return render_template('admin/edit_user.html', user=user)
        
        existing = User.query.filter(User.email == user.email, User.id != user_id).first()
        if existing:
            flash('Email already in use.', 'danger')
            return render_template('admin/edit_user.html', user=user)
        
        db.session.commit()
        flash('User updated successfully.', 'success')
        return redirect(url_for('admin.users'))
    
    return render_template('admin/edit_user.html', user=user)

@admin.route('/users/delete/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if current_user.role != 'admin':
        flash('Admin access required.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    if user_id == current_user.id:
        flash('Cannot delete your own account.', 'danger')
        return redirect(url_for('admin.users'))
    
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    
    flash('User deleted successfully.', 'success')
    return redirect(url_for('admin.users'))

@admin.route('/projects')
@login_required
def all_projects():
    if current_user.role != 'admin':
        flash('Admin access required.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    projects = Project.query.order_by(Project.created_at.desc()).all()
    return render_template('admin/projects.html', projects=projects)

@admin.route('/deployments')
@login_required
def all_deployments():
    if current_user.role != 'admin':
        flash('Admin access required.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    deployments = Deployment.query.order_by(Deployment.created_at.desc()).limit(50).all()
    return render_template('admin/deployments.html', deployments=deployments)

@admin.route('/deployments/<int:deployment_id>')
@login_required
def deployment_detail(deployment_id):
    if current_user.role != 'admin':
        flash('Admin access required.', 'danger')
        return redirect(url_for('main.dashboard'))

    deployment = Deployment.query.get_or_404(deployment_id)
    return render_template('admin/deployment_detail.html', deployment=deployment)


# Ã¢â€â‚¬Ã¢â€â‚¬ Email configuration Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

@admin.route('/email-config', methods=['GET', 'POST'])
@login_required
def email_config():
    if current_user.role != 'admin':
        flash('Admin access required.', 'danger')
        return redirect(url_for('main.dashboard'))

    cfg = EmailConfig.query.first()
    if not cfg:
        cfg = EmailConfig()
        db.session.add(cfg)
        db.session.commit()

    if request.method == 'POST':
        cfg.enabled      = request.form.get('enabled') == 'on'
        cfg.smtp_host    = request.form.get('smtp_host', '').strip() or None
        cfg.smtp_port    = int(request.form.get('smtp_port', 587) or 587)
        cfg.smtp_user    = request.form.get('smtp_user', '').strip() or None
        smtp_pass        = request.form.get('smtp_password', '')
        if smtp_pass:                          # only update if a new value provided
            cfg.smtp_password = smtp_pass
        cfg.use_tls      = request.form.get('use_tls') == 'on'
        cfg.use_ssl      = request.form.get('use_ssl') == 'on'
        cfg.from_name    = request.form.get('from_name', 'DevSpace').strip() or 'DevSpace'
        cfg.from_email   = request.form.get('from_email', '').strip() or None
        cfg.notify_deploy_success = request.form.get('notify_deploy_success') == 'on'
        cfg.notify_deploy_fail    = request.form.get('notify_deploy_fail') == 'on'
        cfg.notify_app_start      = request.form.get('notify_app_start') == 'on'
        cfg.notify_app_stop       = request.form.get('notify_app_stop') == 'on'
        cfg.notify_admin          = request.form.get('notify_admin') == 'on'
        cfg.monitor_recipients    = request.form.get('monitor_recipients', '').strip() or None

        db.session.commit()
        flash('Email settings saved.', 'success')
        return redirect(url_for('admin.email_config'))

    return render_template('admin/email_config.html', cfg=cfg)


@admin.route('/email-config/test', methods=['POST'])
@login_required
def test_email():
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'error': 'Admin only'}), 403

    to_email = request.json.get('email', '').strip() if request.is_json else ''
    if not to_email:
        to_email = current_user.email

    from services.mail_service import send_test_email
    result = send_test_email(current_app._get_current_object(), to_email)
    return jsonify(result)


# Ã¢â€â‚¬Ã¢â€â‚¬ Python apps monitor Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

@admin.route('/python-monitor')
@login_required
def python_monitor():
    """Render the Python Monitor page with server list."""
    if current_user.role not in ('super_admin', 'admin', 'employee'):
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    from models import Server
    servers = Server.query.order_by(Server.name).all()
    return render_template('admin/python_monitor.html', servers=servers)


@admin.route('/python-apps')
@login_required
def python_apps_api():
    """SSH into server(s) and return running Python applications with status."""
    if current_user.role not in ('super_admin', 'admin', 'employee'):
        return jsonify({'ok': False, 'error': 'Access denied'}), 403

    import paramiko
    from io import StringIO
    from models import Server
    from services.crypto_service import decrypt_data

    server_id = request.args.get('server_id')
    if server_id:
        servers = Server.query.filter(Server.id == server_id).all()
    else:
        servers = Server.query.all()

    results = []

    for svr in servers:
        server_data = {
            'id': svr.id,
            'name': svr.name,
            'ip': svr.ip,
            'port': svr.ssh_port,
            'username': svr.username,
            'status_in_db': svr.status,
            'error': None,
            'processes': [],
            'services': [],
        }

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
                server_data['error'] = 'No credentials'
                results.append(server_data)
                continue

            # Get Python processes
            stdin, stdout, stderr = ssh.exec_command(
                r"""ps aux | grep -E 'python|gunicorn|uvicorn|daphne|celery|manage.py|flask|fastapi' | grep -v grep | grep -v 'python3 -c' | grep -v firewalld | grep -v fail2ban | awk '{
                    pid=$2; cpu=$3; mem=$4; user=$1; cmd=""
                    for(i=11;i<=NF;i++) cmd=cmd " " $i

                    # Identify app name
                    app="unknown"
                    if (cmd ~ /gunicorn/) {
                        if (cmd ~ /DevSpace/) app="DevSpace-lite"
                        else if (cmd ~ /smm_pan/) app="smm-panel"
                        else app="gunicorn-app"
                    }
                    else if (cmd ~ /manage\.py.*runserver/) app="django-runserver"
                    else if (cmd ~ /daphne/) app="daphne-asgi"
                    else if (cmd ~ /celery.*worker/) app="celery-worker"
                    else if (cmd ~ /celery.*beat/) app="celery-beat"
                    else if (cmd ~ /uvicorn/) app="fastapi-uvicorn"
                    else if (cmd ~ /app\.py/) app="flask-app"
                    else app="python-process"

                    gsub(/^ */, "", cmd)
                    printf "{\"app\":\"%s\",\"pid\":\"%s\",\"cpu\":\"%s\",\"mem\":\"%s\",\"user\":\"%s\",\"cmd\":\"%s\"}\n", app, pid, cpu, mem, user, cmd
                }'""",
                timeout=15
            )
            for line in stdout.read().decode('utf-8', errors='replace').splitlines():
                line = line.strip()
                if line.startswith('{'):
                    try:
                        import json as _json
                        server_data['processes'].append(_json.loads(line))
                    except:
                        pass

            # Get port-to-PID mapping
            port_map = {}
            stdin_port, stdout_port, stderr_port = ssh.exec_command(
                r"""ss -tlnp 2>/dev/null | awk -F'[[:space:]]+' 'NR>1 {
                    split($4, a, ":")
                    port = a[length(a)]
                    if ($6 ~ /users:.*pid=/) {
                        match($6, /pid=([0-9]+)/, arr)
                        pid = arr[1]
                        if (pid && port) print pid, port
                    }
                }' || netstat -tlnp 2>/dev/null | awk 'NR>2 {
                    split($4, a, ":")
                    port = a[length(a)]
                    if ($7 ~ /\//) {
                        split($7, b, "/")
                        pid = b[1]
                        if (pid ~ /^[0-9]+$/ && port) print pid, port
                    }
                }' || echo 'PORTSCAN_FAILED'""",
                timeout=10
            )
            for line in stdout_port.read().decode('utf-8', errors='replace').splitlines():
                line = line.strip()
                parts = line.split()
                if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                    pid = parts[0]
                    port = parts[1]
                    if pid not in port_map:
                        port_map[pid] = []
                    port_map[pid].append(port)

            # Also try to detect ports from common gunicorn/django/uvicorn bind args
            for proc in server_data['processes']:
                pid = proc['pid']
                if pid in port_map:
                    proc['ports'] = port_map[pid]
                else:
                    # Try to extract port from command line
                    cmd = proc.get('cmd', '')
                    ports = []
                    import re as _re
                    # gunicorn --bind 0.0.0.0:8000
                    for m in _re.finditer(r'(?:bind|port|:)(?:\s+|=)?(?:0\.0\.0\.0|127\.0\.0\.1|localhost)?:?(\d{4,5})', cmd):
                        ports.append(m.group(1))
                    # manage.py runserver 0.0.0.0:8000
                    for m in _re.finditer(r'runserver\s+0\.0\.0\.0:(\d{4,5})', cmd):
                        if m.group(1) not in ports:
                            ports.append(m.group(1))
                    # python3 app.py Ã¢â‚¬â€ try to read config (we'll note it as detected)
                    proc['ports'] = list(set(ports)) if ports else []

            # Get systemd services
            stdin2, stdout2, stderr2 = ssh.exec_command(
                r"""systemctl list-units --type=service --all --no-pager 2>/dev/null | awk '/loaded/ {print $1, $3, $4}' | grep -iE 'python|gunicorn|flask|django|app|deploy|DevSpace|celery|daphne|uvicorn|fastapi|smm|webmail|backend|hrms' || echo 'NONE'""",
                timeout=10
            )
            for line in stdout2.read().decode('utf-8', errors='replace').splitlines():
                line = line.strip()
                if line == 'NONE' or not line:
                    continue
                parts = line.split(None, 2)
                if len(parts) >= 3:
                    running = 'running' in parts[2]
                    server_data['services'].append({
                        'name': parts[0],
                        'status': 'running' if running else 'stopped',
                    })

            ssh.close()
        except paramiko.AuthenticationException:
            server_data['error'] = 'Authentication failed'
        except Exception as e:
            server_data['error'] = str(e)

        results.append(server_data)

    return jsonify({'ok': True, 'servers': results, 'server_id': server_id})


@admin.route('/python-monitor/status')
@login_required
def python_monitor_status():
    from services.monitor_service import get_monitor_status
    return jsonify(get_monitor_status())


@admin.route('/python-monitor/run-check', methods=['POST'])
@login_required
def python_monitor_run_check():
    """
    Run a monitoring check: SSH into all servers, compare with previous state,
    and send email alerts for any newly stopped apps.
    """
    if current_user.role not in ('super_admin', 'admin'):
        return jsonify({'ok': False, 'error': 'Admin only'}), 403

    from services.monitor_service import check_and_alert
    result = check_and_alert(app=current_app._get_current_object())
    return jsonify(result)


@admin.route('/python-monitor/test-alert', methods=['POST'])
@login_required
def python_monitor_test_alert():
    """Send a test alert email to configured recipients to verify email setup."""
    if current_user.role not in ('super_admin', 'admin'):
        return jsonify({'ok': False, 'error': 'Admin only'}), 403

    from services.mail_service import notify_app_down
    from models import EmailConfig

    cfg = EmailConfig.query.first()
    if not cfg or not cfg.enabled or not cfg.smtp_host:
        return jsonify({'ok': False, 'error': 'Email not configured. Go to Settings first.'})

    try:
        notify_app_down(
            app=current_app._get_current_object(),
            server_name='TEST-SERVER (167.86.72.196)',
            app_name='sample-app',
            app_type='service'
        )
        recipients = cfg.monitor_recipients or 'admin (fallback)'
        return jsonify({'ok': True, 'message': f'Test alert sent to: {recipients}'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


# Ã¢â€â‚¬Ã¢â€â‚¬ AI Monitor Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

@admin.route('/ai-monitor')
@login_required
def ai_monitor():
    if current_user.role not in ('super_admin', 'admin'):
        flash('Admin access required.', 'danger')
        return redirect(url_for('main.dashboard'))
    from models import Server, MonitorMetric, MonitorAnomaly, MonitorConfig
    servers = Server.query.all()
    config = MonitorConfig.query.first()
    return render_template('admin/ai_monitor.html', servers=servers, config=config)


@admin.route('/ai-monitor/data')
@login_required
def ai_monitor_data():
    if current_user.role not in ('super_admin', 'admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    from models import Server, MonitorMetric, MonitorAnomaly
    from datetime import datetime, timedelta

    server_id = request.args.get('server_id', type=int)
    hours = request.args.get('hours', 6, type=int)
    since = datetime.utcnow() - timedelta(hours=hours)

    query = MonitorMetric.query.filter(MonitorMetric.created_at >= since)
    if server_id:
        query = query.filter_by(server_id=server_id)
    query = query.order_by(MonitorMetric.created_at.asc())
    metrics = query.all()

    chart_data = {
        'labels': [m.created_at.strftime('%H:%M') for m in metrics],
        'cpu': [m.cpu_pct for m in metrics],
        'memory': [m.memory_pct for m in metrics],
        'disk': [m.disk_pct for m in metrics],
    }

    anom_query = MonitorAnomaly.query.filter(
        MonitorAnomaly.created_at >= since, MonitorAnomaly.resolved_at.is_(None)
    )
    if server_id:
        anom_query = anom_query.filter_by(server_id=server_id)
    anomalies = anom_query.order_by(MonitorAnomaly.created_at.desc()).limit(50).all()

    return jsonify({
        'chart': chart_data,
        'anomalies': [{
            'id': a.id,
            'metric_type': a.metric_type,
            'severity': a.severity,
            'title': a.title,
            'message': a.message,
            'server_id': a.server_id,
            'created_at': a.created_at.isoformat() if a.created_at else None,
        } for a in anomalies],
        'server_id': server_id,
    })


@admin.route('/ai-monitor/status')
@login_required
def ai_monitor_status():
    from models import Server, MonitorMetric, MonitorAnomaly
    from datetime import datetime, timedelta

    servers = Server.query.all()
    statuses = []
    for svr in servers:
        last = (MonitorMetric.query.filter_by(server_id=svr.id)
                .order_by(MonitorMetric.created_at.desc()).first())
        recent_anomalies = (MonitorAnomaly.query
                           .filter_by(server_id=svr.id, resolved_at=None)
                           .filter(MonitorAnomaly.created_at >= datetime.utcnow() - timedelta(hours=24))
                           .count())
        healthy = last.is_healthy if last else False
        statuses.append({
            'id': svr.id,
            'name': svr.name,
            'ip': svr.ip,
            'healthy': healthy,
            'cpu': last.cpu_pct if last else None,
            'memory': last.memory_pct if last else None,
            'disk': last.disk_pct if last else None,
            'load': last.load_1m if last else None,
            'procs': last.proc_count if last else None,
            'last_seen': last.created_at.isoformat() if last else None,
            'anomalies': recent_anomalies,
        })
    return jsonify({'servers': statuses})


@admin.route('/ai-monitor/run-check', methods=['POST'])
@login_required
def ai_monitor_run_check():
    if current_user.role not in ('super_admin', 'admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    from services.monitor_engine import run_once
    try:
        results = run_once(current_app._get_current_object())
        return jsonify({'ok': True, 'results': results})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@admin.route('/ai-monitor/resolve/<int:anomaly_id>', methods=['POST'])
@login_required
def ai_monitor_resolve(anomaly_id):
    if current_user.role not in ('super_admin', 'admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    from datetime import datetime
    from models import MonitorAnomaly
    anomaly = MonitorAnomaly.query.get_or_404(anomaly_id)
    anomaly.resolved_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'ok': True})


@admin.route('/email-config/test', methods=['POST'])
@login_required
def test_email():
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'error': 'Admin only'}), 403

    to_email = request.json.get('email', '').strip() if request.is_json else ''
    if not to_email:
        to_email = current_user.email

    from services.mail_service import send_test_email
    result = send_test_email(current_app._get_current_object(), to_email)
    return jsonify(result)


# Ã¢â€â‚¬Ã¢â€â‚¬ Python apps monitor Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

@admin.route('/python-monitor')
@login_required
def python_monitor():
    """Render the Python Monitor page with server list."""
    if current_user.role not in ('super_admin', 'admin', 'employee'):
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    from models import Server
    servers = Server.query.order_by(Server.name).all()
    return render_template('admin/python_monitor.html', servers=servers)


@admin.route('/python-apps')
@login_required
def python_apps_api():
    """SSH into server(s) and return running Python applications with status."""
    if current_user.role not in ('super_admin', 'admin', 'employee'):
        return jsonify({'ok': False, 'error': 'Access denied'}), 403

    import paramiko
    from io import StringIO
    from models import Server
    from services.crypto_service import decrypt_data

    server_id = request.args.get('server_id')
    if server_id:
        servers = Server.query.filter(Server.id == server_id).all()
    else:
        servers = Server.query.all()

    results = []

    for svr in servers:
        server_data = {
            'id': svr.id,
            'name': svr.name,
            'ip': svr.ip,
            'port': svr.ssh_port,
            'username': svr.username,
            'status_in_db': svr.status,
            'error': None,
            'processes': [],
            'services': [],
        }

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
                server_data['error'] = 'No credentials'
                results.append(server_data)
                continue

            # Get Python processes
            stdin, stdout, stderr = ssh.exec_command(
                r"""ps aux | grep -E 'python|gunicorn|uvicorn|daphne|celery|manage.py|flask|fastapi' | grep -v grep | grep -v 'python3 -c' | grep -v firewalld | grep -v fail2ban | awk '{
                    pid=$2; cpu=$3; mem=$4; user=$1; cmd=""
                    for(i=11;i<=NF;i++) cmd=cmd " " $i

                    # Identify app name
                    app="unknown"
                    if (cmd ~ /gunicorn/) {
                        if (cmd ~ /DevSpace/) app="DevSpace-lite"
                        else if (cmd ~ /smm_pan/) app="smm-panel"
                        else app="gunicorn-app"
                    }
                    else if (cmd ~ /manage\.py.*runserver/) app="django-runserver"
                    else if (cmd ~ /daphne/) app="daphne-asgi"
                    else if (cmd ~ /celery.*worker/) app="celery-worker"
                    else if (cmd ~ /celery.*beat/) app="celery-beat"
                    else if (cmd ~ /uvicorn/) app="fastapi-uvicorn"
                    else if (cmd ~ /app\.py/) app="flask-app"
                    else app="python-process"

                    gsub(/^ */, "", cmd)
                    printf "{\"app\":\"%s\",\"pid\":\"%s\",\"cpu\":\"%s\",\"mem\":\"%s\",\"user\":\"%s\",\"cmd\":\"%s\"}\n", app, pid, cpu, mem, user, cmd
                }'""",
                timeout=15
            )
            for line in stdout.read().decode('utf-8', errors='replace').splitlines():
                line = line.strip()
                if line.startswith('{'):
                    try:
                        import json as _json
                        server_data['processes'].append(_json.loads(line))
                    except:
                        pass

            # Get port-to-PID mapping
            port_map = {}
            stdin_port, stdout_port, stderr_port = ssh.exec_command(
                r"""ss -tlnp 2>/dev/null | awk -F'[[:space:]]+' 'NR>1 {
                    split($4, a, ":")
                    port = a[length(a)]
                    if ($6 ~ /users:.*pid=/) {
                        match($6, /pid=([0-9]+)/, arr)
                        pid = arr[1]
                        if (pid && port) print pid, port
                    }
                }' || netstat -tlnp 2>/dev/null | awk 'NR>2 {
                    split($4, a, ":")
                    port = a[length(a)]
                    if ($7 ~ /\//) {
                        split($7, b, "/")
                        pid = b[1]
                        if (pid ~ /^[0-9]+$/ && port) print pid, port
                    }
                }' || echo 'PORTSCAN_FAILED'""",
                timeout=10
            )
            for line in stdout_port.read().decode('utf-8', errors='replace').splitlines():
                line = line.strip()
                parts = line.split()
                if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                    pid = parts[0]
                    port = parts[1]
                    if pid not in port_map:
                        port_map[pid] = []
                    port_map[pid].append(port)

            # Also try to detect ports from common gunicorn/django/uvicorn bind args
            for proc in server_data['processes']:
                pid = proc['pid']
                if pid in port_map:
                    proc['ports'] = port_map[pid]
                else:
                    # Try to extract port from command line
                    cmd = proc.get('cmd', '')
                    ports = []
                    import re as _re
                    # gunicorn --bind 0.0.0.0:8000
                    for m in _re.finditer(r'(?:bind|port|:)(?:\s+|=)?(?:0\.0\.0\.0|127\.0\.0\.1|localhost)?:?(\d{4,5})', cmd):
                        ports.append(m.group(1))
                    # manage.py runserver 0.0.0.0:8000
                    for m in _re.finditer(r'runserver\s+0\.0\.0\.0:(\d{4,5})', cmd):
                        if m.group(1) not in ports:
                            ports.append(m.group(1))
                    # python3 app.py Ã¢â‚¬â€ try to read config (we'll note it as detected)
                    proc['ports'] = list(set(ports)) if ports else []

            # Get systemd services
            stdin2, stdout2, stderr2 = ssh.exec_command(
                r"""systemctl list-units --type=service --all --no-pager 2>/dev/null | awk '/loaded/ {print $1, $3, $4}' | grep -iE 'python|gunicorn|flask|django|app|deploy|DevSpace|celery|daphne|uvicorn|fastapi|smm|webmail|backend|hrms' || echo 'NONE'""",
                timeout=10
            )
            for line in stdout2.read().decode('utf-8', errors='replace').splitlines():
                line = line.strip()
                if line == 'NONE' or not line:
                    continue
                parts = line.split(None, 2)
                if len(parts) >= 3:
                    running = 'running' in parts[2]
                    server_data['services'].append({
                        'name': parts[0],
                        'status': 'running' if running else 'stopped',
                    })

            ssh.close()
        except paramiko.AuthenticationException:
            server_data['error'] = 'Authentication failed'
        except Exception as e:
            server_data['error'] = str(e)

        results.append(server_data)

    return jsonify({'ok': True, 'servers': results, 'server_id': server_id})


@admin.route('/python-monitor/status')
@login_required
def python_monitor_status():
    from services.monitor_service import get_monitor_status
    return jsonify(get_monitor_status())


@admin.route('/python-monitor/run-check', methods=['POST'])
@login_required
def python_monitor_run_check():
    """
    Run a monitoring check: SSH into all servers, compare with previous state,
    and send email alerts for any newly stopped apps.
    """
    if current_user.role not in ('super_admin', 'admin'):
        return jsonify({'ok': False, 'error': 'Admin only'}), 403

    from services.monitor_service import check_and_alert
    result = check_and_alert(app=current_app._get_current_object())
    return jsonify(result)


@admin.route('/python-monitor/test-alert', methods=['POST'])
@login_required
def python_monitor_test_alert():
    """Send a test alert email to configured recipients to verify email setup."""
    if current_user.role not in ('super_admin', 'admin'):
        return jsonify({'ok': False, 'error': 'Admin only'}), 403

    from services.mail_service import notify_app_down
    from models import EmailConfig

    cfg = EmailConfig.query.first()
    if not cfg or not cfg.enabled or not cfg.smtp_host:
        return jsonify({'ok': False, 'error': 'Email not configured. Go to Settings first.'})

    try:
        notify_app_down(
            app=current_app._get_current_object(),
            server_name='TEST-SERVER (167.86.72.196)',
            app_name='sample-app',
            app_type='service'
        )
        recipients = cfg.monitor_recipients or 'admin (fallback)'
        return jsonify({'ok': True, 'message': f'Test alert sent to: {recipients}'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


# Ã¢â€â‚¬Ã¢â€â‚¬ AI Monitor Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

@admin.route('/ai-monitor')
@login_required
def ai_monitor():
    if current_user.role not in ('super_admin', 'admin'):
        flash('Admin access required.', 'danger')
        return redirect(url_for('main.dashboard'))
    from models import Server, MonitorMetric, MonitorAnomaly, MonitorConfig
    servers = Server.query.all()
    config = MonitorConfig.query.first()
    return render_template('admin/ai_monitor.html', servers=servers, config=config)


@admin.route('/ai-monitor/data')
@login_required
def ai_monitor_data():
    if current_user.role not in ('super_admin', 'admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    from models import Server, MonitorMetric, MonitorAnomaly
    from datetime import datetime, timedelta

    server_id = request.args.get('server_id', type=int)
    hours = request.args.get('hours', 6, type=int)
    since = datetime.utcnow() - timedelta(hours=hours)

    query = MonitorMetric.query.filter(MonitorMetric.created_at >= since)
    if server_id:
        query = query.filter_by(server_id=server_id)
    query = query.order_by(MonitorMetric.created_at.asc())
    metrics = query.all()

    chart_data = {
        'labels': [m.created_at.strftime('%H:%M') for m in metrics],
        'cpu': [m.cpu_pct for m in metrics],
        'memory': [m.memory_pct for m in metrics],
        'disk': [m.disk_pct for m in metrics],
    }

    anom_query = MonitorAnomaly.query.filter(
        MonitorAnomaly.created_at >= since, MonitorAnomaly.resolved_at.is_(None)
    )
    if server_id:
        anom_query = anom_query.filter_by(server_id=server_id)
    anomalies = anom_query.order_by(MonitorAnomaly.created_at.desc()).limit(50).all()

    return jsonify({
        'chart': chart_data,
        'anomalies': [{
            'id': a.id,
            'metric_type': a.metric_type,
            'severity': a.severity,
            'title': a.title,
            'message': a.message,
            'server_id': a.server_id,
            'created_at': a.created_at.isoformat() if a.created_at else None,
        } for a in anomalies],
        'server_id': server_id,
    })


@admin.route('/ai-monitor/status')
@login_required
def ai_monitor_status():
    from models import Server, MonitorMetric, MonitorAnomaly
    from datetime import datetime, timedelta

    servers = Server.query.all()
    statuses = []
    for svr in servers:
        last = (MonitorMetric.query.filter_by(server_id=svr.id)
                .order_by(MonitorMetric.created_at.desc()).first())
        recent_anomalies = (MonitorAnomaly.query
                           .filter_by(server_id=svr.id, resolved_at=None)
                           .filter(MonitorAnomaly.created_at >= datetime.utcnow() - timedelta(hours=24))
                           .count())
        healthy = last.is_healthy if last else False
        statuses.append({
            'id': svr.id,
            'name': svr.name,
            'ip': svr.ip,
            'healthy': healthy,
            'cpu': last.cpu_pct if last else None,
            'memory': last.memory_pct if last else None,
            'disk': last.disk_pct if last else None,
            'load': last.load_1m if last else None,
            'procs': last.proc_count if last else None,
            'last_seen': last.created_at.isoformat() if last else None,
            'anomalies': recent_anomalies,
        })
    return jsonify({'servers': statuses})


@admin.route('/ai-monitor/run-check', methods=['POST'])
@login_required
def ai_monitor_run_check():
    if current_user.role not in ('super_admin', 'admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    from services.monitor_engine import run_once
    try:
        results = run_once(current_app._get_current_object())
        return jsonify({'ok': True, 'results': results})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@admin.route('/ai-monitor/resolve/<int:anomaly_id>', methods=['POST'])
@login_required
def ai_monitor_resolve(anomaly_id):
    if current_user.role not in ('super_admin', 'admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    from datetime import datetime
    from models import MonitorAnomaly
    anomaly = MonitorAnomaly.query.get_or_404(anomaly_id)
    anomaly.resolved_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'ok': True})