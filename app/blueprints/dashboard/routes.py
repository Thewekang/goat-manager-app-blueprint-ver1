from flask import Blueprint, render_template, redirect, url_for, session, flash, request
from ...models import FarmConfig, Goat, GoatType, Sickness, Removal, BreedingEvent, VaccineType, WeightLog, VaccinationEvent, SicknessPhoto
from ...extensions import db
from ...utils import get_ready_does, get_vaccine_due_info, get_target_weight, require_any_role
from sqlalchemy import func
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import os

dashboard_bp = Blueprint("dashboard", __name__)

# No changes needed, route for quickentry already exists and is correct
@dashboard_bp.route("/quickentry", methods=["GET", "POST"])
def quickentry():
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    # --- Filtering options (optional) ---
    selected_location = request.args.get("location")
    selected_type = request.args.get("goat_type")

    all_locations = db.session.query(Goat.location).distinct().all()
    all_types = GoatType.query.order_by(GoatType.name).all()

    goats_query = Goat.query.filter_by(status="active")
    if selected_location:
        goats_query = goats_query.filter_by(location=selected_location)
    if selected_type:
        goats_query = goats_query.filter_by(goat_type_id=selected_type)
    goats = goats_query.order_by(Goat.tag).all()
    vaccine_types = VaccineType.query.order_by(VaccineType.name).all()
    today_str = datetime.now().strftime('%Y-%m-%d')

    # --- Handle form submissions ---
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add_weight":
            for goat in goats:
                w = request.form.get(f"weight_{goat.id}")
                d = request.form.get(f"date_{goat.id}")
                if w and d:
                    log = WeightLog(
                        goat_id=goat.id,
                        date=d,
                        weight=float(w),
                        created_by=session.get("username"),
                        created_at=datetime.utcnow()
                    )
                    goat.weight = float(w)
                    db.session.add(log)
            db.session.commit()
            flash("Weights added!", "success")
            return redirect(url_for("dashboard.quickentry"))

        elif action == "batch_vaccine":
            vaccine_type_id = int(request.form["vaccine_type_id"])
            actual_date_given = request.form.get("actual_date_given", today_str)
            selected_goat_ids = request.form.getlist("goat_ids")
            notes = request.form.get("notes", "")
            given_by = session.get("username")
            for goat_id in selected_goat_ids:
                exists = VaccinationEvent.query.filter_by(
                    goat_id=goat_id,
                    vaccine_type_id=vaccine_type_id,
                    actual_date_given=actual_date_given
                ).first()
                if exists:
                    continue
                ve = VaccinationEvent(
                    goat_id=goat_id,
                    vaccine_type_id=vaccine_type_id,
                    scheduled_date=actual_date_given,
                    actual_date_given=actual_date_given,
                    status="done",
                    notes=notes,
                    given_by=given_by,
                    created_by=session.get("username"),
                    created_at=datetime.utcnow()
                )
                db.session.add(ve)
            db.session.commit()
            flash(f"Vaccination recorded for {len(selected_goat_ids)} goats.", "success")
            return redirect(url_for("dashboard.quickentry"))

        elif action == "mark_pregnancy":
            selected_goat_ids = request.form.getlist("pregnant_goat_ids")
            for goat in goats:
                goat.is_pregnant = str(goat.id) in selected_goat_ids
            db.session.commit()
            flash("Pregnancy status updated.", "success")
            return redirect(url_for("dashboard.quickentry"))

        elif action == "add_sickness":
            goat_id = int(request.form["goat_id"])
            sickness = request.form["sickness"]
            medicine = request.form["medicine"]
            date = request.form["date"]

            s = Sickness(
                goat_id=goat_id,
                sickness=sickness,
                medicine=medicine,
                date=date,
                created_by=session.get("username"),
                created_at=datetime.utcnow(),
                status='active'
            )
            db.session.add(s)
            db.session.commit()  # We need the Sickness.id!

            # --- Multi-photo upload ---
            if "photos" in request.files:
                photos = request.files.getlist("photos")
                for photo in photos:
                    if photo and photo.filename:
                        filename = secure_filename(f"sick_{goat_id}_{date}_{photo.filename}")
                        save_path = os.path.join("static", "uploads", filename)
                        photo.save(save_path)
                        sp = SicknessPhoto(sickness_id=s.id, image_path=save_path)
                        db.session.add(sp)
                db.session.commit()
            flash("Sickness recorded.", "success")
            return redirect(url_for("dashboard.quickentry"))

    return render_template(
        "quickentry.html",
        goats=goats,
        vaccine_types=vaccine_types,
        today=today_str,
        all_locations=[x[0] for x in all_locations if x[0]],
        all_types=all_types,
        selected_location=selected_location,
        selected_type=selected_type,
    )


@dashboard_bp.route("/")
def home():
    if session.get("username"):
        return redirect(url_for("dashboard.dashboard_home"))
    return redirect(url_for("auth.login"))

@dashboard_bp.route("/dashboard")
def dashboard_home():
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    # Handle export requests
    export_format = request.args.get('export')
    if export_format:
        return handle_dashboard_export(export_format)

    # Handle date range filtering
    days = request.args.get('days', '30')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    if start_date and end_date:
        date_filter_start = datetime.strptime(start_date, '%Y-%m-%d')
        date_filter_end = datetime.strptime(end_date, '%Y-%m-%d')
    else:
        date_filter_end = datetime.now()
        date_filter_start = date_filter_end - timedelta(days=int(days))

    # Get all active goats
    goats = Goat.query.filter_by(status="active").all()
    
    # Calculate statistics
    total_goats = len(goats)
    last_month = datetime.now() - timedelta(days=30)
    total_last_month = Goat.query.filter(
        Goat.status == "active",
        Goat.date_acquired <= last_month.strftime('%Y-%m-%d')
    ).count()
    total_change = round(((total_goats - total_last_month) / total_last_month * 100), 1) if total_last_month > 0 else 0

    # Health statistics
    sick_goats = [g for g in goats if hasattr(g, "tags") and "sick" in g.tags]
    underweight_goats = [g for g in goats if get_target_weight(g) and g.weight and g.weight < get_target_weight(g)]
    ready_to_mate = [g for g in goats if hasattr(g, "tags") and "ready to mate" in g.tags]
    pregnant = [g for g in goats if hasattr(g, "tags") and "pregnant" in g.tags]

    # Get upcoming vaccinations
    upcoming_vaccines = []
    for goat in goats:
        due_info = get_vaccine_due_info(goat)
        for info in due_info:
            if info["next_due"]:
                upcoming_vaccines.append({
                    "goat": goat,
                    "vaccine": info["vaccine"],
                    "due_date": info["next_due"]
                })
    
    # Sort by due date and get next 30 days
    upcoming_vaccines.sort(key=lambda x: x["due_date"])
    due_vaccines = len([v for v in upcoming_vaccines if (v["due_date"] - datetime.now().date()).days <= 30])

    # Get recent activities (filtered by date range)
    recent_activities = []
    
    # Add recent weight logs
    weight_logs = WeightLog.query.filter(
        WeightLog.created_at >= date_filter_start,
        WeightLog.created_at <= date_filter_end
    ).order_by(WeightLog.created_at.desc()).limit(5).all()
    
    for log in weight_logs:
        recent_activities.append({
            "title": f"Weight Update: {log.goat.tag}",
            "description": f"New weight: {log.weight}kg",
            "time": log.created_at.strftime("%b %d")
        })

    # Add recent sickness records
    sickness_logs = Sickness.query.filter(
        Sickness.created_at >= date_filter_start,
        Sickness.created_at <= date_filter_end
    ).order_by(Sickness.created_at.desc()).limit(5).all()
    
    for log in sickness_logs:
        recent_activities.append({
            "title": f"Health Issue: {log.goat.tag}",
            "description": f"Condition: {log.sickness}",
            "time": log.created_at.strftime("%b %d")
        })

    # Sort activities by time and keep only most recent 5
    recent_activities = recent_activities[:5]

    # Get upcoming events
    upcoming_events = []
    
    # Add upcoming vaccinations
    for vaccine in upcoming_vaccines[:3]:
        upcoming_events.append({
            "month": vaccine["due_date"].strftime("%b"),
            "day": vaccine["due_date"].strftime("%d"),
            "title": f"Vaccination Due: {vaccine['goat'].tag}",
            "description": f"{vaccine['vaccine'].name}"
        })

    # Add upcoming breeding events
    breeding_events = BreedingEvent.query.filter(
        BreedingEvent.status == "scheduled"
    ).order_by(BreedingEvent.mating_start_date).limit(3).all()
    
    for event in breeding_events:
        upcoming_events.append({
            "month": datetime.strptime(event.mating_start_date, "%Y-%m-%d").strftime("%b"),
            "day": datetime.strptime(event.mating_start_date, "%Y-%m-%d").strftime("%d"),
            "title": "Breeding Event",
            "description": f"Buck: {event.buck.tag}, Doe: {event.doe.tag}"
        })

    # Prepare statistics
    stats = {
        "total_goats": total_goats,
        "total_change": total_change,
        "sick_count": len(sick_goats),
        "underweight_count": len(underweight_goats),
        "ready_to_mate_count": len(ready_to_mate),
        "pregnant_count": len(pregnant),
        "due_vaccines": due_vaccines,
        "sick_goats": sick_goats
    }

    return render_template(
        "dashboard_new.html",
        stats=stats,
        goats=goats,
        recent_activities=recent_activities,
        upcoming_events=upcoming_events
    )

def handle_dashboard_export(format_type):
    """Handle dashboard data export"""
    from flask import make_response
    import csv
    import io
    
    if format_type == 'excel':
        # Create CSV data for Excel
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write headers
        writer.writerow(['Metric', 'Value', 'Description'])
        
        # Get current stats
        goats = Goat.query.filter_by(status="active").all()
        total_goats = len(goats)
        sick_goats = [g for g in goats if hasattr(g, "tags") and "sick" in g.tags]
        underweight_goats = [g for g in goats if get_target_weight(g) and g.weight and g.weight < get_target_weight(g)]
        
        # Write data
        writer.writerow(['Total Active Goats', total_goats, 'Current active goat count'])
        writer.writerow(['Sick Goats', len(sick_goats), 'Goats currently marked as sick'])
        writer.writerow(['Underweight Goats', len(underweight_goats), 'Goats below target weight'])
        
        # Create response
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = f'attachment; filename=dashboard_export_{datetime.now().strftime("%Y%m%d")}.csv'
        return response
        
    elif format_type == 'pdf':
        # For PDF, redirect to a report page or show message
        flash("PDF export functionality will be implemented soon.", "info")
        return redirect(url_for('dashboard.dashboard_home'))
    
    return redirect(url_for('dashboard.dashboard_home'))

@dashboard_bp.route("/setup")
def setup():
    """Farm setup page for admin users"""
    if not session.get("username") or session.get("role") not in ['admin', 'superadmin']:
        flash("Access denied.", "danger")
        return redirect(url_for("dashboard.home"))
    
    config = FarmConfig.query.first()
    return render_template("setup.html", config=config)

@dashboard_bp.route("/target_weight_admin", methods=["GET", "POST"])
def target_weight_admin():
    """Target weight administration page"""
    if not session.get("username") or session.get("role") not in ['admin', 'superadmin']:
        flash("Access denied.", "danger")
        return redirect(url_for("dashboard.home"))
    
    from ...models import TargetWeight

    if request.method == "POST":
        if "add" in request.form:
            # Add new target weight
            target = TargetWeight(
                goat_type_id=request.form["goat_type_id"],
                sex=request.form["sex"] or None,
                age_months=int(request.form["age_months"]),
                min_weight=float(request.form["min_weight"])
            )
            db.session.add(target)
            db.session.commit()
            flash("Target weight added successfully.", "success")
        
        elif "edit_id" in request.form:
            # Edit existing target weight
            target = TargetWeight.query.get_or_404(request.form["edit_id"])
            target.goat_type_id = request.form["goat_type_id"]
            target.sex = request.form["sex"] or None
            target.age_months = int(request.form["age_months"])
            target.min_weight = float(request.form["min_weight"])
            db.session.commit()
            flash("Target weight updated successfully.", "success")
        
        elif "delete_id" in request.form:
            # Delete target weight
            target = TargetWeight.query.get_or_404(request.form["delete_id"])
            db.session.delete(target)
            db.session.commit()
            flash("Target weight deleted successfully.", "success")
        
        return redirect(url_for("dashboard.target_weight_admin"))
    
    goat_types = GoatType.query.order_by(GoatType.name).all()
    targets = TargetWeight.query.join(GoatType).order_by(GoatType.name, TargetWeight.age_months).all()
    return render_template("target_weights.html", goat_types=goat_types, targets=targets)

@dashboard_bp.route("/admin_feedback")
def admin_feedback():
    """Admin feedback page"""
    if not session.get("username") or session.get("role") not in ['admin', 'superadmin']:
        flash("Access denied.", "danger")
        return redirect(url_for("dashboard.home"))
    
    # This would typically show feedback from workers
    # For now, just render a placeholder template
    return render_template("admin_feedback.html")

@dashboard_bp.route("/setup/reset", methods=["POST"])
@require_any_role("admin", "superadmin")
def reset_db():
    """Reset the database to initial state"""
    if session.get("role") != "superadmin":
        flash("Only superadmin can reset database.", "danger")
        return redirect(url_for("dashboard.setup"))

    try:
        # Drop all tables
        db.drop_all()
        # Recreate tables
        db.create_all()
        flash("Database reset successful.", "success")
    except Exception as e:
        flash(f"Error resetting database: {str(e)}", "danger")

    return redirect(url_for("dashboard.setup"))


@dashboard_bp.route("/feedback/photo/delete/<int:photo_id>", methods=["POST"])
def delete_feedback_photo(photo_id):
    """Delete a feedback photo"""
    from ...models import GoatFeedbackPhoto
    
    if not session.get("username"):
        flash("Login required.", "warning")
        return redirect(url_for("auth.login"))
    
    photo = GoatFeedbackPhoto.query.get_or_404(photo_id)
    feedback = photo.feedback
    
    # Check if user owns the feedback or is admin
    if feedback.submitted_by != session["username"] and session.get("role") not in ["admin", "superadmin"]:
        flash("You can only delete your own photos.", "danger")
        return redirect(url_for("goats.goat_detail", tag=feedback.goat.tag))
    
    # Delete file from filesystem
    try:
        if os.path.exists(photo.image_path):
            os.remove(photo.image_path)
    except Exception:
        pass
    
    # Delete from database
    db.session.delete(photo)
    db.session.commit()
    
    flash("Photo deleted successfully.", "success")
    return redirect(url_for("goats.goat_detail", tag=feedback.goat.tag))
