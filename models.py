from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    # Role expanded to support super_admin, admin, employee, team
    role = db.Column(db.Enum('super_admin', 'admin', 'employee', 'team', 'user'), default='employee')
    plan = db.Column(db.Enum('free', 'basic', 'pro', 'enterprise'), default='free')
    home_dir = db.Column(db.String(500), nullable=True)   # auto-created on user add
    
    # Security Features
    tfa_enabled = db.Column(db.Boolean, default=False)
    tfa_secret = db.Column(db.String(100), nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    projects = db.relationship('Project', backref='user', lazy=True, cascade='all, delete-orphan')
    activity_logs = db.relationship('ActivityLog', backref='user', lazy=True, cascade='all, delete-orphan')
    
    PLAN_LIMITS = {
        'free': 1,
        'basic': 5,
        'pro': 25,
        'enterprise': 999
    }
    
    def set_password(self, password):
        self.password = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password, password)
    
    def can_create_project(self):
        if self.role in ('super_admin', 'admin') or self.plan == 'enterprise':
            return True
        limit = self.PLAN_LIMITS.get(self.plan, 0)
        return len(self.projects) < limit
    
    def get_project_limit(self):
        return self.PLAN_LIMITS.get(self.plan, 0)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'role': self.role,
            'plan': self.plan,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class Server(db.Model):
    __tablename__ = 'servers'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    ip = db.Column(db.String(100), nullable=False)
    ssh_port = db.Column(db.Integer, default=22)
    username = db.Column(db.String(100), default='root')
    password_enc = db.Column(db.Text, nullable=True)
    ssh_key_enc = db.Column(db.Text, nullable=True)
    os_type = db.Column(db.String(100), default='Ubuntu')
    provider = db.Column(db.String(100), default='Generic')
    tags = db.Column(db.String(255), default='')
    status = db.Column(db.String(50), default='Unknown') # Active, Inactive, Unknown
    
    # Auto-scanned environment properties
    panel_type = db.Column(db.String(100), default='None') # CyberPanel, cPanel, None
    web_server = db.Column(db.String(100), default='Unknown') # OpenLiteSpeed, Apache, Nginx, Unknown
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    projects = db.relationship('Project', backref='server', lazy=True)
    command_logs = db.relationship('CommandLog', backref='server', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'ip': self.ip,
            'ssh_port': self.ssh_port,
            'username': self.username,
            'os_type': self.os_type,
            'provider': self.provider,
            'tags': self.tags,
            'status': self.status,
            'panel_type': self.panel_type,
            'web_server': self.web_server,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class Project(db.Model):
    __tablename__ = 'projects'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    server_id = db.Column(db.Integer, db.ForeignKey('servers.id'), nullable=True)
    
    name = db.Column(db.String(255), nullable=False)
    project_type = db.Column(db.Enum('git', 'zip', 'docker'), default='git')
    framework_type = db.Column(db.String(100), default='python') # fastapi, react, node, etc.
    
    repo_url = db.Column(db.String(500), nullable=True)   
    git_repo_path = db.Column(db.String(500), nullable=True)  
    branch = db.Column(db.String(100), default='main')
    language = db.Column(db.Enum('python', 'php', 'node', 'docker', 'static'), default='python')
    deploy_path = db.Column(db.String(500), nullable=False)
    
    port = db.Column(db.Integer, nullable=True)
    service_name = db.Column(db.String(100), nullable=True)
    startup_file = db.Column(db.String(100), nullable=True)   
    entry_point  = db.Column(db.String(100), nullable=True)   
    python_version = db.Column(db.String(20), nullable=True)  
    
    # Custom Deploy Settings
    build_command = db.Column(db.String(500), nullable=True)
    start_command = db.Column(db.String(500), nullable=True)
    env_vars = db.Column(db.Text, nullable=True) # JSON format string
    
    last_deployed = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    deployments = db.relationship('Deployment', backref='project', lazy=True, cascade='all, delete-orphan')
    nginx_vhosts = db.relationship('NginxVhost', backref='project', lazy=True, cascade='all, delete-orphan')

    def get_ssh_clone_url(self, vps_host, ssh_user='git'):
        if self.git_repo_path:
            return f"{ssh_user}@{vps_host}:{self.git_repo_path}"
        return None

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'server_id': self.server_id,
            'name': self.name,
            'project_type': self.project_type,
            'framework_type': self.framework_type,
            'repo_url': self.repo_url,
            'git_repo_path': self.git_repo_path,
            'branch': self.branch,
            'language': self.language,
            'deploy_path': self.deploy_path,
            'port': self.port,
            'build_command': self.build_command,
            'start_command': self.start_command,
            'last_deployed': self.last_deployed.isoformat() if self.last_deployed else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class EmailConfig(db.Model):
    __tablename__ = 'email_config'

    id            = db.Column(db.Integer, primary_key=True)
    enabled       = db.Column(db.Boolean, default=False)
    smtp_host     = db.Column(db.String(255), nullable=True)
    smtp_port     = db.Column(db.Integer,     default=587)
    smtp_user     = db.Column(db.String(255), nullable=True)
    smtp_password = db.Column(db.String(255), nullable=True)
    use_tls       = db.Column(db.Boolean,     default=True)
    use_ssl       = db.Column(db.Boolean,     default=False)
    from_name     = db.Column(db.String(100), default='Udeck Deploy Manager')
    from_email    = db.Column(db.String(255), nullable=True)
    
    # SaaS Notifications
    notify_deploy_success = db.Column(db.Boolean, default=True)
    notify_deploy_fail    = db.Column(db.Boolean, default=True)
    notify_app_start      = db.Column(db.Boolean, default=True)
    notify_app_stop       = db.Column(db.Boolean, default=True)
    notify_admin          = db.Column(db.Boolean, default=True)
    
    telegram_bot_token = db.Column(db.String(255), nullable=True)
    telegram_chat_id = db.Column(db.String(100), nullable=True)
    whatsapp_api_key = db.Column(db.String(255), nullable=True)
    whatsapp_phone_number = db.Column(db.String(100), nullable=True)

    # Monitor alert recipients (comma-separated emails)
    monitor_recipients = db.Column(db.Text, nullable=True)
    
    updated_at    = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Deployment(db.Model):
    __tablename__ = 'deployments'
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    status = db.Column(db.Enum('pending', 'running', 'success', 'failed'), default='pending')
    logs = db.Column(db.Text, nullable=True)
    commit_message = db.Column(db.String(500), nullable=True)
    commit_date = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime, nullable=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'project_id': self.project_id,
            'status': self.status,
            'logs': self.logs,
            'commit_message': self.commit_message,
            'commit_date': self.commit_date.isoformat() if self.commit_date else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'finished_at': self.finished_at.isoformat() if self.finished_at else None
        }

class ActivityLog(db.Model):
    __tablename__ = 'activity_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=True)
    action = db.Column(db.String(255), nullable=False)
    ip_address = db.Column(db.String(100), nullable=True)
    details = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class CommandLog(db.Model):
    __tablename__ = 'command_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    server_id = db.Column(db.Integer, db.ForeignKey('servers.id', ondelete='CASCADE'), nullable=True)
    command = db.Column(db.String(1000), nullable=False)
    output = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), default='pending') # success, failed, running
    run_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class NginxVhost(db.Model):
    __tablename__ = 'nginx_vhosts'
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id', ondelete='CASCADE'), nullable=True)
    domain_name = db.Column(db.String(255), nullable=False, unique=True)
    ssl_enabled = db.Column(db.Boolean, default=False)
    ssl_cert_path = db.Column(db.String(500), nullable=True)
    ssl_key_path = db.Column(db.String(500), nullable=True)
    config_content = db.Column(db.Text, nullable=True)
    redirect_rules = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class CronJob(db.Model):
    __tablename__ = 'cron_jobs'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    schedule = db.Column(db.String(100), nullable=False)
    command = db.Column(db.String(1000), nullable=False)
    last_run = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(50), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class MonitorMetric(db.Model):
    __tablename__ = 'monitor_metrics'

    id          = db.Column(db.Integer, primary_key=True)
    server_id   = db.Column(db.Integer, db.ForeignKey('servers.id', ondelete='CASCADE'), nullable=False)
    cpu_pct     = db.Column(db.Float, default=0)
    memory_pct  = db.Column(db.Float, default=0)
    disk_pct    = db.Column(db.Float, default=0)
    load_1m     = db.Column(db.Float, default=0)
    proc_count  = db.Column(db.Integer, default=0)
    is_healthy  = db.Column(db.Boolean, default=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    server = db.relationship('Server', backref='monitor_metrics', lazy=True)

    __table_args__ = (
        db.Index('idx_metric_server_time', 'server_id', 'created_at'),
    )


class MonitorAnomaly(db.Model):
    __tablename__ = 'monitor_anomalies'

    id          = db.Column(db.Integer, primary_key=True)
    server_id   = db.Column(db.Integer, db.ForeignKey('servers.id', ondelete='CASCADE'), nullable=False)
    metric_type = db.Column(db.String(50), nullable=False)  # cpu, memory, disk, process, down
    severity    = db.Column(db.String(20), default='warning')  # info, warning, critical
    title       = db.Column(db.String(255), nullable=False)
    message     = db.Column(db.Text, nullable=True)
    value       = db.Column(db.Float, nullable=True)
    threshold   = db.Column(db.Float, nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    server = db.relationship('Server', backref='monitor_anomalies', lazy=True)

    __table_args__ = (
        db.Index('idx_anomaly_server_time', 'server_id', 'created_at'),
    )


class MonitorConfig(db.Model):
    __tablename__ = 'monitor_config'

    id             = db.Column(db.Integer, primary_key=True)
    interval_sec   = db.Column(db.Integer, default=60)
    cpu_warn       = db.Column(db.Float, default=75)
    cpu_crit       = db.Column(db.Float, default=90)
    mem_warn       = db.Column(db.Float, default=75)
    mem_crit       = db.Column(db.Float, default=90)
    disk_warn      = db.Column(db.Float, default=80)
    disk_crit      = db.Column(db.Float, default=92)
    enabled        = db.Column(db.Boolean, default=True)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at     = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SecurityEvent(db.Model):
    __tablename__ = 'security_events'

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    action     = db.Column(db.String(100), nullable=False, index=True)
    severity   = db.Column(db.String(20), default='info')  # info, warning, critical
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    details    = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship('User', backref='security_events', lazy=True)


class UserSession(db.Model):
    __tablename__ = 'user_sessions'

    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    session_id  = db.Column(db.String(64), nullable=False, unique=True)
    ip_address  = db.Column(db.String(45), nullable=True)
    user_agent  = db.Column(db.String(255), nullable=True)
    last_active = db.Column(db.DateTime, default=datetime.utcnow)
    is_current  = db.Column(db.Boolean, default=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='sessions', lazy=True)

    __table_args__ = (
        db.Index('idx_session_user', 'user_id', 'last_active'),
    )


class CodeScan(db.Model):
    __tablename__ = 'code_scans'

    id          = db.Column(db.Integer, primary_key=True)
    project_id  = db.Column(db.Integer, db.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    status      = db.Column(db.String(20), default='pending')  # pending, running, completed, failed
    language    = db.Column(db.String(20))
    total_issues = db.Column(db.Integer, default=0)
    high_count   = db.Column(db.Integer, default=0)
    medium_count = db.Column(db.Integer, default=0)
    low_count    = db.Column(db.Integer, default=0)
    score       = db.Column(db.Float, nullable=True)
    summary_json = db.Column(db.Text, nullable=True)
    started_at  = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime, nullable=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    project = db.relationship('Project', backref='code_scans', lazy=True)
    user    = db.relationship('User', backref='code_scans', lazy=True)

    __table_args__ = (
        db.Index('idx_scans_project', 'project_id'),
        db.Index('idx_scans_status', 'status'),
    )


class CodeVulnerability(db.Model):
    __tablename__ = 'code_vulnerabilities'

    id          = db.Column(db.Integer, primary_key=True)
    scan_id     = db.Column(db.Integer, db.ForeignKey('code_scans.id', ondelete='CASCADE'), nullable=False)
    vuln_type   = db.Column(db.String(50))   # security, quality, dependency
    scanner     = db.Column(db.String(30))   # bandit, pylint, npm_audit, basic
    severity    = db.Column(db.String(10))   # HIGH, MEDIUM, LOW
    confidence  = db.Column(db.String(10))
    title       = db.Column(db.String(200))
    message     = db.Column(db.Text)
    file_path   = db.Column(db.String(500))
    line_number = db.Column(db.Integer, default=0)
    code_snippet = db.Column(db.Text, nullable=True)
    cve         = db.Column(db.String(100), nullable=True)
    fix         = db.Column(db.Text, nullable=True)
    is_false_positive = db.Column(db.Boolean, default=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    scan = db.relationship('CodeScan', backref='vulnerabilities', lazy=True)

    __table_args__ = (
        db.Index('idx_vuln_scan', 'scan_id'),
        db.Index('idx_vuln_severity', 'severity'),
    )