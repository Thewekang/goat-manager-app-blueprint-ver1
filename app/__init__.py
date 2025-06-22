from flask import Flask, session
from config import Config
from .extensions import db, migrate, mail
from .models import User
from datetime import datetime

def create_app():
    app = Flask(__name__, 
                template_folder='../templates',  # Point to templates directory at root level
                static_folder='../static')       # Point to static directory at root level
    app.config.from_object(Config)

    db.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)

    # Register blueprints
    from .blueprints.auth import auth_bp
    from .blueprints.dashboard import dashboard_bp
    from .blueprints.goats import goats_bp
    from .blueprints.breeding import breeding_bp
    from .blueprints.vaccine import vaccine_bp
    from .blueprints.reports import reports_bp
    from .blueprints.users import users_bp
    from .blueprints.sickness import sickness_bp
    from .blueprints.calendar import calendar_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(goats_bp)
    app.register_blueprint(breeding_bp)
    app.register_blueprint(vaccine_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(sickness_bp)
    app.register_blueprint(calendar_bp)

    # --- Context processors ---
    @app.context_processor
    def inject_now():
        return {'now': datetime.now}

    @app.context_processor
    def inject_target_weight():
        from .utils import get_target_weight
        return dict(get_target_weight=get_target_weight)

    @app.context_processor
    def inject_current_user():
        user = None
        if 'username' in session:
            user = User.query.filter_by(username=session['username']).first()
        return {'current_user': user}

    @app.template_filter('todate')
    def todate_filter(s, fmt="%Y-%m-%d"):
        return datetime.strptime(s, fmt).date()

    # Add user status check middleware
    @app.before_request
    def check_user_status():
        from flask import request, redirect, url_for, flash
        exempt_routes = ['login', 'logout', 'static', 'request_password_reset', 'force_change_password']
        if request.endpoint and any(request.endpoint.startswith(r) for r in exempt_routes):
            return

        username = session.get("username")
        if not username:
            return  # Let @require_permission or routes handle redirect

        user = User.query.filter_by(username=username).first()
        if not user or user.status != "active":
            session.clear()
            flash("Your account is inactive. Contact admin.", "danger")
            return redirect(url_for("auth.login"))

    return app
