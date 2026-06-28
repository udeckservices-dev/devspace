from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from models import Server
from services.docker_service import list_containers, manage_container, get_container_logs, list_images, list_volumes

docker_bp = Blueprint('docker_bp', __name__, url_prefix='/docker')

@docker_bp.route('/')
@login_required
def index():
    servers = Server.query.all()
    selected_server_id = request.args.get('server_id')
    
    server = None
    containers = []
    images = []
    volumes = []
    
    if selected_server_id:
        server = Server.query.get(selected_server_id)
        if server:
            containers = list_containers(server)
            images = list_images(server)
            volumes = list_volumes(server)
            
    return render_template('admin/docker.html', 
                           servers=servers, 
                           server=server, 
                           containers=containers,
                           images=images,
                           volumes=volumes)

@docker_bp.route('/action/<int:server_id>/<container_id>/<action>', methods=['POST'])
@login_required
def container_action(server_id, container_id, action):
    server = Server.query.get_or_404(server_id)
    res = manage_container(server, container_id, action)
    return jsonify(res)

@docker_bp.route('/logs/<int:server_id>/<container_id>')
@login_required
def container_logs(server_id, container_id):
    server = Server.query.get_or_404(server_id)
    logs = get_container_logs(server, container_id)
    return jsonify({'logs': logs})
