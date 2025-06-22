from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from ...models import User, PasswordResetRequest
from ...extensions import db
from datetime import datetime

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            if user.status != "active":
                flash("Account is inactive.", "danger")
                return redirect(url_for("auth.login"))

            session["username"] = user.username
            session["role"] = user.role
            user.last_login = datetime.now()
            db.session.commit()

            if user.must_change_password:
                flash("Please change your password before continuing.", "warning")
                return redirect(url_for("auth.force_change_password"))

            flash("Login successful!", "success")
            return redirect(url_for("dashboard.dashboard_home"))
        else:
            flash("Invalid username or password", "danger")
    return render_template("login.html")

@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))

@auth_bp.route("/force_change_password", methods=["GET", "POST"])
def force_change_password():
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    user = User.query.filter_by(username=session["username"]).first()

    if not user.must_change_password:
        return redirect(url_for("dashboard.dashboard_home"))

    if request.method == "POST":
        new_pw = request.form["new_password"]
        confirm_pw = request.form["confirm_password"]

        if new_pw != confirm_pw:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("auth.force_change_password"))

        user.set_password(new_pw)
        db.session.commit()
        flash("Password updated. You can now use the app.", "success")
        return redirect(url_for("dashboard.dashboard_home"))

    return render_template("force_change_password.html")

@auth_bp.route("/request_password_reset", methods=["POST"])
def request_password_reset():
    username = request.form.get("username", "").strip()

    if not username:
        flash("Please enter your username before requesting a reset.", "warning")
        return redirect(url_for("auth.login"))

    user = User.query.filter_by(username=username).first()
    if not user:
        flash(f"User '{username}' not found.", "danger")
        return redirect(url_for("auth.login"))

    existing = PasswordResetRequest.query.filter_by(user_id=user.id, resolved=False).first()
    if existing:
        flash("You have already requested a reset. Please wait for admin to act.", "info")
    else:
        req = PasswordResetRequest(user_id=user.id)
        db.session.add(req)
        db.session.commit()
        flash("✅ Password reset request submitted. Please contact your admin.", "success")

    return redirect(url_for("auth.login"))
