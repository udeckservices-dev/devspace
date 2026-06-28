import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(days=1)
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    @classmethod
    def init_db(cls):
        use_sqlite = os.environ.get('USE_SQLITE', 'true').lower() == 'true'
        if use_sqlite:
            base_dir = os.path.abspath(os.path.dirname(__file__))
            cls.SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(base_dir, 'devspace.db')}"
        else:
            db_host = os.environ.get('DB_HOST', 'localhost')
            db_port = os.environ.get('DB_PORT', '3306')
            db_name = os.environ.get('DB_NAME', 'devspace')
            db_user = os.environ.get('DB_USER', 'root')
            db_password = os.environ.get('DB_PASSWORD', '')
            cls.SQLALCHEMY_DATABASE_URI = f"mysql+pymysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"


# Set DB URI at import time
_use_sqlite = os.environ.get('USE_SQLITE', 'true').lower() == 'true'
if _use_sqlite:
    _base_dir = os.path.abspath(os.path.dirname(__file__))
    Config.SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(_base_dir, 'devspace.db')}"
else:
    _db_host = os.environ.get('DB_HOST', 'localhost')
    _db_port = os.environ.get('DB_PORT', '3306')
    _db_name = os.environ.get('DB_NAME', 'devspace')
    _db_user = os.environ.get('DB_USER', 'root')
    _db_password = os.environ.get('DB_PASSWORD', '')
    Config.SQLALCHEMY_DATABASE_URI = f"mysql+pymysql://{_db_user}:{_db_password}@{_db_host}:{_db_port}/{_db_name}"


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
