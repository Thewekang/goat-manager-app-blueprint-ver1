from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from ...models import User, PasswordResetRequest
from ...extensions import db
from ...utils import require_any_role
from datetime import datetime
import secrets

users_bp = Blueprint("users", __name__)

@users_bp.route("/users", methods=["GET", "POST"])
@require_any_role("admin", "superadmin")
def user_list():
    users = User.query.all()
    all_perms = [("sickness", "Can record sickness"), ("remove", "Can remove goats")]
    reset_requests = PasswordResetRequest.query.filter_by(resolved=False).order_by(PasswordResetRequest.timestamp.desc()).all()

    if request.method == "POST":
        for user in users:
            if user.role == "worker":
                perms = request.form.getlist(f"perms_{user.id}")
                user.permissions = ",".join(perms)
        db.session.commit()
        flash("Permissions updated!", "success")
        return redirect(url_for("users.user_list"))

    return render_template("user_list.html", users=users, all_perms=all_perms, reset_requests=reset_requests)

@users_bp.route("/users/reset/<int:user_id>", methods=["POST"])
@require_any_role("admin", "superadmin")
def reset_user_password(user_id):
    current_user = User.query.filter_by(username=session.get("username")).first()
    target_user = User.query.get_or_404(user_id)

    if current_user.role == "superadmin" or (current_user.role == "admin" and target_user.role == "worker"):
        temp_pw = secrets.token_urlsafe(8)[:10]
        target_user.set_temp_password(temp_pw)
        db.session.commit()
        return jsonify({"success": True, "temp_password": temp_pw})
    return jsonify({"success": False, "error": "Not authorized."}), 403

@users_bp.route("/users/toggle/<int:user_id>", methods=["POST"])
@require_any_role("admin", "superadmin")
def toggle_user_status(user_id):
    current_user = User.query.filter_by(username=session.get("username")).first()
    target_user = User.query.get_or_404(user_id)

    if current_user.role == "superadmin" or (current_user.role == "admin" and target_user.role == "worker"):
        target_user.status = "inactive" if target_user.status == "active" else "active"
        db.session.commit()
        flash("User status changed.", "info")
    else:
        flash("Not authorized to change status.", "danger")

    return redirect(url_for("users.user_list"))

@users_bp.route("/users/add", methods=["GET", "POST"])
@users_bp.route("/users/edit/<int:user_id>", methods=["GET", "POST"])
@require_any_role("admin", "superadmin")
def manage_user(user_id=None):
    current = User.query.filter_by(username=session.get("username")).first()
    is_edit = user_id is not None
    user = User.query.get(user_id) if is_edit else None

    if current.role == "admin":
        if is_edit and user.role != "worker":
            flash("Admins can only manage workers.", "danger")
            return redirect(url_for("users.user_list"))

    if request.method == "POST":
        username = request.form["username"]
        full_name = request.form["full_name"]
        email = request.form["email"]
        phone = request.form["phone"]
        role = "worker" if current.role != "superadmin" else request.form.get("role", "worker")
        status = "active" if "status" in request.form else "inactive"

        if is_edit:
            user.full_name = full_name
            user.email = email
            user.phone = phone
            user.status = status
            db.session.commit()
            flash("User updated.", "success")
        else:
            if User.query.filter_by(username=username).first():
                flash("Username already exists!", "danger")
                return redirect(url_for("users.manage_user"))
            raw_pw = request.form["password"] or secrets.token_urlsafe(8)[:10]
            new_user = User(
                username=username,
                full_name=full_name,
                email=email,
                phone=phone,
                role=role,
                status=status,
                created_by=current.username
            )
            new_user.set_temp_password(raw_pw)
            db.session.add(new_user)
            db.session.commit()
            flash(f"User created. Temp password: {raw_pw}", "info")
        return redirect(url_for("users.user_list"))

    return render_template("add_user.html", user=user)

@users_bp.route("/profile", methods=["GET", "POST"])
def user_profile():
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    user = User.query.filter_by(username=session["username"]).first()

    if request.method == "POST":
        user.full_name = request.form["full_name"]
        user.email = request.form["email"]
        user.phone = request.form["phone"]
        db.session.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("users.user_profile"))

    return render_template("user_profile.html", current_user=user)

@users_bp.route("/change_password", methods=["POST"])
def change_password():
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    user = User.query.filter_by(username=session["username"]).first()
    current_pw = request.form["current_password"]
    new_pw = request.form["new_password"]

    if not user.check_password(current_pw):
        flash("Incorrect current password.", "danger")
        return redirect(url_for("users.user_profile"))

    user.set_password(new_pw)
    db.session.commit()
    flash("Password changed successfully.", "success")
    return redirect(url_for("users.user_profile"))

@users_bp.route("/admin/reset/<int:user_id>/<int:request_id>", methods=["POST"])
@require_any_role("admin", "superadmin")
def admin_reset_password(user_id, request_id):
    """Admin reset password for user with pending request"""
    current_user = User.query.filter_by(username=session.get("username")).first()
    target_user = User.query.get_or_404(user_id)
    reset_request = PasswordResetRequest.query.get_or_404(request_id)
    
    # Verify the request belongs to the user
    if reset_request.user_id != user_id:
        flash("Invalid reset request.", "danger")
        return redirect(url_for("users.user_list"))
    
    # Check authorization
    if current_user.role == "admin" and target_user.role != "worker":
        flash("Admins can only reset worker passwords.", "danger")
        return redirect(url_for("users.user_list"))
    
    # Generate new temporary password
    temp_pw = secrets.token_urlsafe(8)[:10]
    target_user.set_temp_password(temp_pw)
    
    # Mark request as resolved
    reset_request.resolved = True
    reset_request.resolved_by = current_user.username
    reset_request.resolved_at = datetime.utcnow()
    
    db.session.commit()
    
    flash(f"Password reset for {target_user.username}. New temporary password: {temp_pw}", "success")
    return redirect(url_for("users.user_list"))
