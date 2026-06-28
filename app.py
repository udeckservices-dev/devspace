import os
from flask import Flask, render_template
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_mail import Mail
from config import config
from models import db

login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'info'

csrf    = CSRFProtect()
mail    = Mail()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri="memory://",   # use Redis URI in production: "redis://localhost:6379"
)

def create_app(config_name='default'):
    app = Flask(__name__)
    app.config.from_object(config[config_name])

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    mail.init_app(app)
    limiter.init_app(app)
    
    from models import User
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
    
    from routes.auth import auth
    from routes.main import main
    from routes.admin import admin
    from routes.billing import billing
    from routes.servers import servers_bp
    from routes.file_manager import file_manager
    from routes.terminal import terminal_bp
    from routes.docker import docker_bp
    from routes.nginx import nginx_bp
    from routes.automation import automation_bp
    from routes.logs import logs_bp
    from routes.security import security
    
    app.register_blueprint(auth)
    app.register_blueprint(main)
    app.register_blueprint(admin)
    app.register_blueprint(billing)
    app.register_blueprint(servers_bp)
    app.register_blueprint(file_manager)
    app.register_blueprint(terminal_bp)
    app.register_blueprint(docker_bp)
    app.register_blueprint(nginx_bp)
    app.register_blueprint(automation_bp)
    app.register_blueprint(logs_bp)
    app.register_blueprint(security)

    # ── Rate limits ───────────────────────────────────────────────────────────
    # Auth: strict limits to prevent brute-force
    limiter.limit("10 per minute")(app.view_functions['auth.login'])
    limiter.limit("5 per minute")(app.view_functions['auth.register'])
    # API endpoints: prevent abuse/scanning
    limiter.limit("30 per minute")(app.view_functions['main.scan_path'])
    limiter.limit("60 per minute")(app.view_functions['main.run_pip_install'])
    limiter.limit("60 per minute")(app.view_functions['main.run_npm_install'])
    limiter.limit("20 per minute")(app.view_functions['main.app_control'])
    
    # CSS cache-busting — sends file mtime as version to every template
    import os as _os
    _css_path = _os.path.join(app.static_folder, 'css', 'style.css')

    @app.context_processor
    def inject_css_version():
        try:
            v = int(_os.path.getmtime(_css_path))
        except Exception:
            v = 1
        return {'css_version': v}

    # Exempt internal webhook from CSRF — it uses X-Deploy-Secret instead
    from routes.main import internal_deploy_webhook
    csrf.exempt(internal_deploy_webhook)

    # (no global session filter — handled per-route)

    # ── Security headers on every response ───────────────────────────────────
    @app.after_request
    def set_security_headers(response):
        # Prevent clickjacking
        response.headers['X-Frame-Options'] = 'DENY'
        # Prevent MIME sniffing
        response.headers['X-Content-Type-Options'] = 'nosniff'
        # Basic XSS protection for older browsers
        response.headers['X-XSS-Protection'] = '1; mode=block'
        # Referrer policy — don't leak URL to third parties
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        # Content Security Policy
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        )
        # Permissions policy — disable unnecessary browser features
        response.headers['Permissions-Policy'] = (
            'geolocation=(), microphone=(), camera=()'
        )
        # HSTS — only set over HTTPS (nginx/reverse-proxy sets it in prod)
        if _os.environ.get('FLASK_ENV') == 'production':
            response.headers['Strict-Transport-Security'] = (
                'max-age=31536000; includeSubDomains'
            )
        return response

    @app.route('/health')
    def health():
        return {'status': 'ok'}

    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(429)
    def too_many_requests(e):
        from flask import request as req, jsonify
        if req.path.startswith('/api/') or req.headers.get('Accept') == 'application/json':
            return jsonify({'error': 'Too many requests. Please slow down.'}), 429
        from flask import flash as _flash, redirect as _redirect, url_for as _url
        _flash('Too many attempts. Please wait a moment and try again.', 'warning')
        return _redirect(_url('auth.login')), 429

    @app.errorhandler(500)
    def server_error(e):
        return render_template('errors/500.html'), 500

    return app

app = create_app(os.environ.get('FLASK_ENV', 'production'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)