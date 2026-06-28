from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from models import db, Server, CommandLog, ActivityLog
from services.crypto_service import encrypt_data, decrypt_data
from services.ssh_service import test_ssh_connection, execute_ssh_command, scan_server_environment

servers_bp = Blueprint('servers', __name__, url_prefix='/servers')

@servers_bp.route('/')
@login_required
def index():
    if current_user.role not in ('super_admin', 'admin', 'employee'):
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('main.dashboard'))
        
    servers = Server.query.order_by(Server.created_at.desc()).all()
    return render_template('admin/servers.html', servers=servers)

@servers_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if current_user.role not in ('super_admin', 'admin'):
        flash('Access restricted to administrators.', 'danger')
        return redirect(url_for('servers.index'))
        
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        ip = request.form.get('ip', '').strip()
        port = int(request.form.get('port', 22))
        username = request.form.get('username', 'root').strip()
        password = request.form.get('password', '').strip()
        ssh_key = request.form.get('ssh_key', '').strip()
        os_type = request.form.get('os_type', 'Ubuntu').strip()
        provider = request.form.get('provider', 'Generic').strip()
        tags = request.form.get('tags', '').strip()
        
        if not all([name, ip, username]):
            flash('Name, IP, and Username are required.', 'danger')
            return render_template('admin/add_server.html')
            
        password_enc = encrypt_data(password) if password else None
        ssh_key_enc = encrypt_data(ssh_key) if ssh_key else None
        
        server = Server(
            name=name,
            ip=ip,
            ssh_port=port,
            username=username,
            password_enc=password_enc,
            ssh_key_enc=ssh_key_enc,
            os_type=os_type,
            provider=provider,
            tags=tags,
            status='Unknown'
        )
        db.session.add(server)
        db.session.commit()
        
        # Log activity
        log = ActivityLog(
            user_id=current_user.id,
            action=f"Added VPS server '{name}'",
            ip_address=request.remote_addr,
            details=f"Server IP: {ip}, Username: {username}"
        )
        db.session.add(log)
        db.session.commit()
        
        flash('Server added successfully.', 'success')
        return redirect(url_for('servers.index'))
        
    return render_template('admin/add_server.html')

@servers_bp.route('/test/<int:server_id>', methods=['POST'])
@login_required
def test_connection(server_id):
    server = Server.query.get_or_404(server_id)
    res = test_ssh_connection(
        ip=server.ip,
        port=server.ssh_port,
        username=server.username,
        password_enc=server.password_enc,
        ssh_key_enc=server.ssh_key_enc
    )
    if res['success']:
        server.status = 'Active'
        # Run server environment auto-scanning
        try:
            scan_res = scan_server_environment(server)
            server.panel_type = scan_res['panel_type']
            server.web_server = scan_res['web_server']
            res['message'] += f" Detected: {scan_res['panel_type']} with {scan_res['web_server']} web server."
        except Exception as e:
            res['message'] += f" (Scan failed: {str(e)})"
    else:
        server.status = 'Inactive'
    db.session.commit()
    return jsonify(res)

@servers_bp.route('/edit/<int:server_id>', methods=['GET', 'POST'])
@login_required
def edit(server_id):
    if current_user.role not in ('super_admin', 'admin'):
        flash('Access restricted to administrators.', 'danger')
        return redirect(url_for('servers.index'))
        
    server = Server.query.get_or_404(server_id)
    
    if request.method == 'POST':
        server.name = request.form.get('name', '').strip()
        server.ip = request.form.get('ip', '').strip()
        server.ssh_port = int(request.form.get('port', 22))
        server.username = request.form.get('username', 'root').strip()
        server.os_type = request.form.get('os_type', 'Ubuntu').strip()
        server.provider = request.form.get('provider', 'Generic').strip()
        server.tags = request.form.get('tags', '').strip()
        
        password = request.form.get('password', '').strip()
        ssh_key = request.form.get('ssh_key', '').strip()
        
        if password:
            server.password_enc = encrypt_data(password)
        if ssh_key:
            server.ssh_key_enc = encrypt_data(ssh_key)
            
        db.session.commit()
        flash('Server details updated successfully.', 'success')
        return redirect(url_for('servers.index'))
        
    # Decrypt credentials for viewing/editing if needed
    password_dec = decrypt_data(server.password_enc) if server.password_enc else ""
    ssh_key_dec = decrypt_data(server.ssh_key_enc) if server.ssh_key_enc else ""
    
    return render_template('admin/edit_server.html', server=server, password_dec=password_dec, ssh_key_dec=ssh_key_dec)

@servers_bp.route('/delete/<int:server_id>', methods=['POST'])
@login_required
def delete(server_id):
    if current_user.role not in ('super_admin', 'admin'):
        flash('Access restricted to administrators.', 'danger')
        return redirect(url_for('servers.index'))
        
    server = Server.query.get_or_404(server_id)
    db.session.delete(server)
    db.session.commit()
    flash('Server deleted successfully.', 'success')
    return redirect(url_for('servers.index'))

@servers_bp.route('/terminal', methods=['GET', 'POST'])
@login_required
def terminal():
    servers = Server.query.all()
    history = CommandLog.query.order_by(CommandLog.created_at.desc()).limit(50).all()
    return render_template('admin/terminal_bulk.html', servers=servers, history=history)

@servers_bp.route('/terminal/run', methods=['POST'])
@login_required
def run_terminal_command():
    target = request.json.get('target', 'single') # single, multiple, all
    server_ids = request.json.get('server_ids', [])
    command = request.json.get('command', '').strip()
    
    if not command:
        return jsonify({'ok': False, 'message': 'No command provided'})
        
    if target == 'all':
        servers = Server.query.all()
    elif target == 'multiple':
        servers = Server.query.filter(Server.id.in_(server_ids)).all()
    else:
        server_id = request.json.get('server_id')
        servers = [Server.query.get(server_id)] if server_id else []
        
    if not servers:
        return jsonify({'ok': False, 'message': 'No valid server selected'})
        
    results = []
    for s in servers:
        if not s:
            continue
        res = execute_ssh_command(
            ip=s.ip,
            port=s.ssh_port,
            username=s.username,
            command=command,
            password_enc=s.password_enc,
            ssh_key_enc=s.ssh_key_enc
        )
        
        # Store in command log
        clog = CommandLog(
            server_id=s.id,
            command=command,
            output=res['stdout'] if res['success'] else res['stderr'],
            status='success' if res['success'] else 'failed',
            run_by_user_id=current_user.id
        )
        db.session.add(clog)
        db.session.commit()
        
        results.append({
            'server_name': s.name,
            'server_ip': s.ip,
            'success': res['success'],
            'stdout': res['stdout'],
            'stderr': res['stderr']
        })
        
    return jsonify({'ok': True, 'results': results})
