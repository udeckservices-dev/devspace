from flask import Blueprint, render_template, request
from flask_login import login_required
from models import db, Deployment, CommandLog, ActivityLog

logs_bp = Blueprint('logs_bp', __name__, url_prefix='/logs')

@logs_bp.route('/')
@login_required
def index():
    log_type = request.args.get('type', 'all')
    search = request.args.get('search', '').strip()
    
    deployments = []
    commands = []
    activities = []
    
    if log_type in ('all', 'deploy'):
        q = Deployment.query.order_by(Deployment.created_at.desc())
        if search:
            q = q.filter(Deployment.logs.like(f"%{search}%") | Deployment.commit_message.like(f"%{search}%"))
        deployments = q.limit(50).all()
        
    if log_type in ('all', 'command'):
        q = CommandLog.query.order_by(CommandLog.created_at.desc())
        if search:
            q = q.filter(CommandLog.command.like(f"%{search}%") | CommandLog.output.like(f"%{search}%"))
        commands = q.limit(50).all()
        
    if log_type in ('all', 'audit'):
        q = ActivityLog.query.order_by(ActivityLog.created_at.desc())
        if search:
            q = q.filter(ActivityLog.action.like(f"%{search}%") | ActivityLog.details.like(f"%{search}%"))
        activities = q.limit(50).all()
        
    return render_template('admin/logs.html',
                           deployments=deployments,
                           commands=commands,
                           activities=activities,
                           log_type=log_type,
                           search=search)
