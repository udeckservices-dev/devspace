from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required
from models import db, Project, Server, NginxVhost
from services.nginx_service import configure_nginx_vhost, install_letsencrypt_ssl

nginx_bp = Blueprint('nginx_bp', __name__, url_prefix='/nginx')

@nginx_bp.route('/')
@login_required
def index():
    projects = Project.query.all()
    vhosts = NginxVhost.query.order_by(NginxVhost.created_at.desc()).all()
    servers = Server.query.all()
    return render_template('admin/nginx.html', projects=projects, vhosts=vhosts, servers=servers)

@nginx_bp.route('/add', methods=['POST'])
@login_required
def add_vhost():
    project_id = request.form.get('project_id')
    domain_name = request.form.get('domain_name', '').strip()
    target_port = request.form.get('target_port')
    server_id = request.form.get('server_id')
    
    if not all([domain_name, target_port, server_id]):
        flash('All fields are required.', 'danger')
        return redirect(url_for('nginx_bp.index'))
        
    server = Server.query.get_or_404(server_id)
    project = Project.query.get(project_id) if project_id else None
    
    # Configure reverse proxy
    res = configure_nginx_vhost(server, domain_name, target_port)
    
    if res['success']:
        # Save to database
        vhost = NginxVhost(
            project_id=project.id if project else None,
            domain_name=domain_name,
            config_content=res['config'],
            ssl_enabled=False
        )
        db.session.add(vhost)
        db.session.commit()
        flash('Nginx vhost configured successfully!', 'success')
    else:
        flash(f"Nginx configuration failed: {res['message']}", 'danger')
        
    return redirect(url_for('nginx_bp.index'))

@nginx_bp.route('/ssl/<int:vhost_id>', methods=['POST'])
@login_required
def request_ssl(vhost_id):
    vhost = NginxVhost.query.get_or_404(vhost_id)
    project = vhost.project
    
    if not project or not project.server_id:
        # Fallback to local server or look up server from projects
        server = Server.query.first() # select primary server
    else:
        server = Server.query.get(project.server_id)
        
    if not server:
        return jsonify({'success': False, 'message': 'No server assigned to this domain\'s project.'})
        
    res = install_letsencrypt_ssl(server, vhost.domain_name)
    if res['success']:
        vhost.ssl_enabled = True
        db.session.commit()
        return jsonify({'success': True, 'message': 'SSL Certificate configured and redirects activated!'})
    else:
        return jsonify({'success': False, 'message': f"SSL request failed: {res['message']}"})

@nginx_bp.route('/delete/<int:vhost_id>', methods=['POST'])
@login_required
def delete_vhost(vhost_id):
    vhost = NginxVhost.query.get_or_404(vhost_id)
    db.session.delete(vhost)
    db.session.commit()
    flash('Domain vhost config record deleted from dashboard.', 'success')
    return redirect(url_for('nginx_bp.index'))
