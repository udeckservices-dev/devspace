"""
run.py â€” DevSpace entry point.

Usage:
  python run.py               # development
  gunicorn run:app            # production
"""

import os

# Load .env file if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _migrate_db():
    """Add missing columns to SQLite (safe, idempotent)."""
    from sqlalchemy import text, inspect as sa_inspect
    from models import db

    inspector = sa_inspect(db.engine)

    # â”€â”€ projects table â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    proj_cols = [c['name'] for c in inspector.get_columns('projects')]
    with db.engine.connect() as conn:
        if 'git_repo_path' not in proj_cols:
            conn.execute(text('ALTER TABLE projects ADD COLUMN git_repo_path VARCHAR(500)'))
            conn.commit()
            print("  Migration: added projects.git_repo_path")
        if 'port' not in proj_cols:
            conn.execute(text('ALTER TABLE projects ADD COLUMN port INTEGER'))
            conn.commit()
            print("  Migration: added projects.port")
        if 'service_name' not in proj_cols:
            conn.execute(text('ALTER TABLE projects ADD COLUMN service_name VARCHAR(100)'))
            conn.commit()
            print("  Migration: added projects.service_name")
        if 'startup_file' not in proj_cols:
            conn.execute(text('ALTER TABLE projects ADD COLUMN startup_file VARCHAR(100)'))
            conn.commit()
        if 'entry_point' not in proj_cols:
            conn.execute(text('ALTER TABLE projects ADD COLUMN entry_point VARCHAR(100)'))
            conn.commit()
        if 'python_version' not in proj_cols:
            conn.execute(text('ALTER TABLE projects ADD COLUMN python_version VARCHAR(20)'))
            conn.commit()
        if 'server_id' not in proj_cols:
            conn.execute(text('ALTER TABLE projects ADD COLUMN server_id INTEGER'))
            conn.commit()
        if 'project_type' not in proj_cols:
            conn.execute(text("ALTER TABLE projects ADD COLUMN project_type VARCHAR(50) DEFAULT 'git'"))
            conn.commit()
        if 'framework_type' not in proj_cols:
            conn.execute(text("ALTER TABLE projects ADD COLUMN framework_type VARCHAR(100) DEFAULT 'python'"))
            conn.commit()
        if 'build_command' not in proj_cols:
            conn.execute(text('ALTER TABLE projects ADD COLUMN build_command VARCHAR(500)'))
            conn.commit()
        if 'start_command' not in proj_cols:
            conn.execute(text('ALTER TABLE projects ADD COLUMN start_command VARCHAR(500)'))
            conn.commit()
        if 'env_vars' not in proj_cols:
            conn.execute(text('ALTER TABLE projects ADD COLUMN env_vars TEXT'))
            conn.commit()

    tables = inspector.get_table_names()

    # â”€â”€ servers table â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if 'servers' in tables:
        srv_cols = [c['name'] for c in inspector.get_columns('servers')]
        with db.engine.connect() as conn:
            if 'panel_type' not in srv_cols:
                conn.execute(text("ALTER TABLE servers ADD COLUMN panel_type VARCHAR(100) DEFAULT 'None'"))
                conn.commit()
                print("  Migration: added servers.panel_type")
            if 'web_server' not in srv_cols:
                conn.execute(text("ALTER TABLE servers ADD COLUMN web_server VARCHAR(100) DEFAULT 'Unknown'"))
                conn.commit()
                print("  Migration: added servers.web_server")

    # â”€â”€ users table â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    user_cols = [c['name'] for c in inspector.get_columns('users')]
    with db.engine.connect() as conn:
        if 'home_dir' not in user_cols:
            conn.execute(text('ALTER TABLE users ADD COLUMN home_dir VARCHAR(500)'))
            conn.commit()
            print("  Migration: added users.home_dir")
        if 'tfa_enabled' not in user_cols:
            conn.execute(text('ALTER TABLE users ADD COLUMN tfa_enabled BOOLEAN DEFAULT 0'))
            conn.commit()
        if 'tfa_secret' not in user_cols:
            conn.execute(text('ALTER TABLE users ADD COLUMN tfa_secret VARCHAR(100)'))
            conn.commit()

    # â”€â”€ monitor_metrics table â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if 'monitor_metrics' in tables:
        mm_cols = [c['name'] for c in inspector.get_columns('monitor_metrics')]
        with db.engine.connect() as conn:
            if 'load_1m' not in mm_cols:
                conn.execute(text('ALTER TABLE monitor_metrics ADD COLUMN load_1m FLOAT DEFAULT 0'))
                conn.commit()

    # â”€â”€ monitor_anomalies table â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if 'monitor_anomalies' in tables:
        ma_cols = [c['name'] for c in inspector.get_columns('monitor_anomalies')]
        with db.engine.connect() as conn:
            if 'value' not in ma_cols:
                conn.execute(text('ALTER TABLE monitor_anomalies ADD COLUMN value FLOAT'))
                conn.commit()
            if 'threshold' not in ma_cols:
                conn.execute(text('ALTER TABLE monitor_anomalies ADD COLUMN threshold FLOAT'))
                conn.commit()

    # â”€â”€ monitor_config table â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if 'monitor_config' in tables:
        mc_cols = [c['name'] for c in inspector.get_columns('monitor_config')]
        with db.engine.connect() as conn:
            for col, defn in [
                ('cpu_warn', 'FLOAT DEFAULT 75'),
                ('cpu_crit', 'FLOAT DEFAULT 90'),
                ('mem_warn', 'FLOAT DEFAULT 75'),
                ('mem_crit', 'FLOAT DEFAULT 90'),
                ('disk_warn', 'FLOAT DEFAULT 80'),
                ('disk_crit', 'FLOAT DEFAULT 92'),
                ('interval_sec', 'INTEGER DEFAULT 60'),
            ]:
                if col not in mc_cols:
                    conn.execute(text(f'ALTER TABLE monitor_config ADD COLUMN {col} {defn}'))
                    conn.commit()
                    print(f"  Migration: added monitor_config.{col}")

    # â”€â”€ security_events table â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if 'security_events' in tables:
        se_cols = [c['name'] for c in inspector.get_columns('security_events')]
        with db.engine.connect() as conn:
            for col, defn in [('severity', "VARCHAR(20) DEFAULT 'info'")]:
                if col not in se_cols:
                    conn.execute(text(f'ALTER TABLE security_events ADD COLUMN {col} {defn}'))
                    conn.commit()
                    print(f"  Migration: added security_events.{col}")

    # â”€â”€ user_sessions table â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if 'user_sessions' in tables:
        us_cols = [c['name'] for c in inspector.get_columns('user_sessions')]
        with db.engine.connect() as conn:
            if 'is_current' not in us_cols:
                conn.execute(text('ALTER TABLE user_sessions ADD COLUMN is_current BOOLEAN DEFAULT 0'))
                conn.commit()

    # â”€â”€ email_config table (auto-created by create_all, but add missing cols) â”€â”€
    tables = inspector.get_table_names()
    if 'email_config' in tables:
        email_cols = [c['name'] for c in inspector.get_columns('email_config')]
        with db.engine.connect() as conn:
            for col, defn in [
                ('notify_deploy_success', 'BOOLEAN DEFAULT 1'),
                ('notify_deploy_fail',    'BOOLEAN DEFAULT 1'),
                ('notify_app_start',      'BOOLEAN DEFAULT 1'),
                ('notify_app_stop',       'BOOLEAN DEFAULT 1'),
                ('notify_admin',          'BOOLEAN DEFAULT 1'),
                ('from_name',             "VARCHAR(100) DEFAULT 'Udeck Deploy Manager'"),
                ('telegram_bot_token',    'VARCHAR(255)'),
                ('telegram_chat_id',      'VARCHAR(100)'),
                ('whatsapp_api_key',      'VARCHAR(255)'),
                ('whatsapp_phone_number', 'VARCHAR(100)'),
                ('monitor_recipients',   'TEXT'),
            ]:
                if col not in email_cols:
                    conn.execute(text(f'ALTER TABLE email_config ADD COLUMN {col} {defn}'))
                    conn.commit()
                    print(f"  Migration: added email_config.{col}")


from app import app, db
from models import User


if __name__ == '__main__':
    with app.app_context():
        db.create_all()

        try:
            _migrate_db()
        except Exception as e:
            print(f"  Migration note: {e}")

        print("Database ready.")

    debug = os.environ.get('FLASK_ENV', 'development') != 'production'
    print(f"Starting DevSpace on http://0.0.0.0:{os.environ.get('PORT', 5000)}")
    app.run(host='0.0.0.0',
            port=int(os.environ.get('PORT', 5000)),
            debug=debug)
