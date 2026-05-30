from flask import Flask
from flask_cors import CORS
import os
import logging

from config import Config
from database import get_db_connection, pg_table_exists, add_column_if_missing
from utils import ensure_default_admin_account

# Import Blueprints
from routes.auth import auth_bp
from routes.main import main_bp
from routes.order import order_bp
from routes.seller import seller_bp
from routes.user import user_bp
from routes.rider import rider_bp
from routes.api import api_bp
from routes.mobile_api import mobile_api_bp
from routes.admin import admin_bp

try:
    from flask_wtf.csrf import CSRFProtect, generate_csrf
except ModuleNotFoundError:
    CSRFProtect = None
    generate_csrf = None

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config.setdefault('WTF_CSRF_ENABLED', True)
    app.config.setdefault('WTF_CSRF_SECRET_KEY', app.config.get('SECRET_KEY'))

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    # Initialize CORS
    CORS(
        app,
        resources={
            r"/api/*": {"origins": "*"},
            r"/api/mobile/*": {"origins": "*"},
            r"/api/auth/*": {"origins": "*"},
            r"/static/*": {"origins": "*"},
        },
        allow_headers=["Content-Type", "Authorization"],
        methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    )
    
    # Initialize CSRF Protection
    if CSRFProtect is not None:
        csrf = CSRFProtect(app)
        if generate_csrf is not None:
            app.jinja_env.globals['csrf_token'] = generate_csrf
        csrf.exempt(api_bp)
        csrf.exempt(mobile_api_bp)
        # Exempt auth blueprint API endpoints (e.g. /api/auth/bridge-login)
        # so mobile clients can POST JSON without needing a CSRF token.
        csrf.exempt(auth_bp)
    else:
        app.jinja_env.globals['csrf_token'] = lambda: ''
        logger.warning('flask_wtf is not installed; CSRF protection is disabled.')
    
    # Create upload directories
    upload_dirs = [
        os.path.join(app.static_folder, 'uploads', 'profile'),
        os.path.join(app.static_folder, 'uploads', 'products'),
        os.path.join(app.static_folder, 'uploads', 'valid_ids'),
        os.path.join(app.static_folder, 'uploads', 'refunds'),
        os.path.join(app.static_folder, 'uploads', 'delivery_proof')
    ]
    for directory in upload_dirs:
        os.makedirs(directory, exist_ok=True)
    
    # Register Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(order_bp)
    app.register_blueprint(seller_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(rider_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(mobile_api_bp, url_prefix='/api/mobile')
    
    # Add cache control headers for authenticated pages
    @app.after_request
    def set_cache_headers(response):
        # Check if user is authenticated
        from flask import session as flask_session
        if flask_session.get('id') or flask_session.get('user_id'):
            # For authenticated users, prevent caching
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response
    
    # Database Initializations
    with app.app_context():
        try:
            ensure_default_admin_account()
            logger.info("Database initialization completed.")
        except Exception as e:
            logger.error(f"Error during database initialization: {e}")
            
    return app

app = create_app()

if __name__ == '__main__':
    import threading
    from scripts.discovery import start_udp_discovery_server
    
    
    threading.Thread(
        target=start_udp_discovery_server, 
        args=(Config.FLASK_PORT, 5001), 
        daemon=True
    ).start()
    
    app.run(host=Config.FLASK_HOST, port=Config.FLASK_PORT, debug=Config.FLASK_DEBUG)
