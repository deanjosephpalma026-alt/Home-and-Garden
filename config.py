import os
from dotenv import load_dotenv

load_dotenv()


def _normalize_supabase_db_host(host):
    if not host:
        return None
    host = host.strip()
    if host.startswith('http://') or host.startswith('https://'):
        host = host.split('://', 1)[1].rstrip('/')
    if host.endswith('.supabase.co') and not host.startswith('db.'):
        host = f'db.{host}'
    return host


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'default-secret-key')
    
    # PostgreSQL Configuration
    DATABASE_URL = os.environ.get('DATABASE_URL')
    SUPABASE_DB_HOST = _normalize_supabase_db_host(os.environ.get('SUPABASE_DB_HOST'))
    SUPABASE_DB_NAME = os.environ.get('SUPABASE_DB_NAME')
    SUPABASE_DB_USER = os.environ.get('SUPABASE_DB_USER')
    SUPABASE_DB_PASSWORD = os.environ.get('SUPABASE_DB_PASSWORD')
    SUPABASE_DB_PORT = os.environ.get('SUPABASE_DB_PORT', '5432')
    
    # Supabase Auth
    SUPABASE_URL = os.environ.get('SUPABASE_URL')
    SUPABASE_ANON_KEY = os.environ.get('SUPABASE_ANON_KEY')
    SUPABASE_SERVICE_ROLE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY')
    
    # Flask App Config
    FLASK_HOST = os.environ.get('FLASK_HOST', '0.0.0.0')
    FLASK_PORT = int(os.environ.get('FLASK_PORT', '5000'))
    FLASK_DEBUG = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
    
    # Mail Config
    MAIL_SERVER = 'smtp.gmail.com'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_FROM = os.environ.get('MAIL_FROM', MAIL_USERNAME)
    
    # Dev Mode
    DEV_MODE = os.environ.get('DEV_MODE', 'False').lower() == 'true'
    
    # Uploads
    UPLOAD_FOLDER = os.path.join('static', 'uploads')
