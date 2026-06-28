from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from models import Server, CommandLog, db
from services.ssh_service import execute_ssh_command

terminal_bp = Blueprint('terminal_routes', __name__, url_prefix='/terminal')

@terminal_bp.route('/')
@login_required
def index():
    servers = Server.query.all()
    return render_template('admin/terminal_ssh.html', servers=servers)

@terminal_bp.route('/execute', methods=['POST'])
@login_required
def run_command():
    server_id = request.json.get('server_id')
    command = request.json.get('command', '').strip()
    
    if not command:
        return jsonify({'ok': False, 'error': 'Command is empty'})
        
    server = Server.query.get_or_404(server_id)
    
    # Run the SSH command
    res = execute_ssh_command(
        ip=server.ip,
        port=server.ssh_port,
        username=server.username,
        command=command,
        password_enc=server.password_enc,
        ssh_key_enc=server.ssh_key_enc
    )
    
    # Audit log command execution in Database
    clog = CommandLog(
        server_id=server.id,
        command=command,
        output=res['stdout'] if res['success'] else res['stderr'],
        status='success' if res['success'] else 'failed',
        run_by_user_id=current_user.id
    )
    db.session.add(clog)
    db.session.commit()
    
    return jsonify({
        'ok': res['success'],
        'stdout': res['stdout'],
        'stderr': res['stderr']
    })
