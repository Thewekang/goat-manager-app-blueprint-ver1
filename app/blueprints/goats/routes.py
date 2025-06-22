from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from ...models import Goat, GoatType, Sickness, SicknessPhoto, Removal, WeightLog, GoatFeedback, GoatFeedbackPhoto, VaccineType, VaccinationEvent, BreedingEvent
from ...extensions import db
from ...utils import require_permission, require_any_role, get_vaccine_due_info, get_target_weight
from werkzeug.utils import secure_filename
from datetime import datetime
import os

goats_bp = Blueprint("goats", __name__)

@goats_bp.route("/goats")
def list_goats():
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    selected_tags = request.args.getlist('tags')
    selected_location = request.args.get("location")
    locations = db.session.query(Goat.location).distinct().all()
    locations = [loc[0] for loc in locations if loc[0]]

    goats = Goat.query.filter_by(status="active").all()

    if selected_tags:
        goats = [g for g in goats if hasattr(g, "tags") and any(tag in g.tags for tag in selected_tags)]
    if selected_location:
        goats = [g for g in goats if g.location == selected_location]

    alerts = {}
    for goat in goats:
        target = get_target_weight(goat)
        if target and goat.weight and goat.weight < target:
            alerts[goat.tag] = f"Underweight! (target ≥ {target} kg)"

    return render_template(
        "goat_list.html",
        goats=goats,
        locations=locations,
        selected_location=selected_location,
        alerts=alerts,
        selected_tags=selected_tags
    )

@goats_bp.route("/goats/add", methods=["GET", "POST"])
def add_goat():
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    goat_types = GoatType.query.order_by(GoatType.name).all()

    if request.method == "POST":
        tag = request.form["tag"].strip()
        goat_type_id = int(request.form["goat_type_id"])
        sex = request.form["sex"]
        acquisition_method = request.form["acquisition_method"]
        source_name = request.form.get("source_name")
        purchase_price = request.form.get("purchase_price")
        dob = request.form["dob"] if request.form["dob"] else None
        age_estimate_months = request.form["age_estimate_months"]
        weight = request.form["weight"]
        location = request.form["location"]
        notes = request.form["notes"]

        date_acquired = request.form.get("date_acquired") or None
        if acquisition_method == "Born":
            if not dob:
                flash("Date of Birth is required for goats born on farm.", "danger")
                return redirect(url_for("goats.add_goat"))
            date_acquired = dob
        else:
            if not date_acquired:
                flash("Date Acquired is required for purchased/donated goats.", "danger")
                return redirect(url_for("goats.add_goat"))

        purchase_price = float(purchase_price) if purchase_price else None
        age_estimate_months = int(age_estimate_months) if age_estimate_months else None
        weight = float(weight) if weight else None

        if Goat.query.filter_by(tag=tag, status="active").first():
            flash(f"Tag {tag} is already in use!", "danger")
            return redirect(url_for("goats.add_goat"))

        goat = Goat(
            tag=tag,
            goat_type_id=goat_type_id,
            sex=sex,
            dob=dob,
            date_acquired=date_acquired,
            acquisition_method=acquisition_method,
            source_name=source_name,
            purchase_price=purchase_price,
            age_estimate_months=age_estimate_months,
            weight=weight,
            status="active",
            added_by=session.get("username"),
            location=location,
            notes=notes
        )
        db.session.add(goat)
        db.session.commit()
        flash(f"Goat {tag} added successfully.", "success")
        if acquisition_method != "Born":
            flash("Please record initial vaccination dates for this goat using 'Batch Vaccination' or on the goat profile page.", "warning")
        return redirect(url_for("goats.list_goats"))

    return render_template("add_goat.html", goat_types=goat_types, goat=None)

@goats_bp.route("/goats/edit/<int:goat_id>", methods=["GET", "POST"])
def edit_goat(goat_id):
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))
    goat = Goat.query.get_or_404(goat_id)
    goat_types = GoatType.query.order_by(GoatType.name).all()

    if request.method == "POST":
        goat.tag = request.form["tag"].strip()
        goat.goat_type_id = int(request.form["goat_type_id"])
        goat.sex = request.form["sex"]
        goat.dob = request.form["dob"] if request.form["dob"] else None
        goat.date_acquired = request.form["date_acquired"]
        goat.acquisition_method = request.form["acquisition_method"]
        goat.source_name = request.form.get("source_name")
        goat.purchase_price = float(request.form.get("purchase_price") or 0)
        goat.age_estimate_months = int(request.form.get("age_estimate_months") or 0)
        goat.weight = float(request.form.get("weight") or 0)
        goat.location = request.form["location"]
        goat.notes = request.form["notes"]
        goat.is_pregnant = 'is_pregnant' in request.form
        db.session.commit()
        flash("Goat details updated!", "success")
        return redirect(url_for("goats.goat_detail", tag=goat.tag))

    return render_template("edit_goat.html", goat_types=goat_types, goat=goat)

@goats_bp.route("/goats/<tag>")
def goat_detail(tag):
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    goat = Goat.query.filter_by(tag=tag).first_or_404()
    vaccine_due_info = get_vaccine_due_info(goat)

    if goat.dob:
        age_days = (datetime.now().date() - datetime.strptime(goat.dob, '%Y-%m-%d').date()).days
    elif goat.age_estimate_months:
        age_days = goat.age_estimate_months * 30
    else:
        age_days = 0

    has_any_vaccine = bool(getattr(goat, "vaccination_events", None))

    weight_page = request.args.get('weight_page', 1, type=int)
    weight_logs = WeightLog.query.filter_by(goat_id=goat.id)\
        .order_by(WeightLog.date.desc())\
        .paginate(page=weight_page, per_page=10, error_out=False)

    vaccine_page = request.args.get('vaccine_page', 1, type=int)
    vaccine_events = VaccinationEvent.query.filter_by(goat_id=goat.id)\
        .order_by(VaccinationEvent.scheduled_date.desc())\
        .paginate(page=vaccine_page, per_page=10, error_out=False)

    breeding_page = request.args.get('breeding_page', 1, type=int)
    breeding_events = BreedingEvent.query.filter(
        (BreedingEvent.buck_id == goat.id) | (BreedingEvent.doe_id == goat.id)
    ).order_by(BreedingEvent.mating_start_date.desc())\
     .paginate(page=breeding_page, per_page=10, error_out=False)

    sickness_page = request.args.get('sickness_page', 1, type=int)
    sickness_history = Sickness.query.filter_by(goat_id=goat.id)\
        .order_by(Sickness.created_at.desc())\
        .paginate(page=sickness_page, per_page=10, error_out=False)

    return render_template(
        "goat_detail.html",
        goat=goat,
        vaccine_due_info=vaccine_due_info,
        age_days=age_days,
        has_any_vaccine=has_any_vaccine,
        weight_logs=weight_logs,
        vaccine_events=vaccine_events,
        breeding_events=breeding_events,
        sickness_history=sickness_history,
        now=datetime.utcnow()
    )

@goats_bp.route("/goats/<tag>/add_weight", methods=["POST"])
def add_weight_log(tag):
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))
    goat = Goat.query.filter_by(tag=tag).first_or_404()
    date = request.form["date"]
    weight = float(request.form["weight"])
    log = WeightLog(
        goat_id=goat.id,
        date=date,
        weight=weight,
        created_by=session.get("username"),
        created_at=datetime.utcnow(),
    )
    db.session.add(log)
    goat.weight = weight
    db.session.commit()
    flash("Weight log added!", "success")
    return redirect(url_for("goats.goat_detail", tag=goat.tag))

@goats_bp.route("/goats/<tag>/sickness", methods=["GET", "POST"])
@require_permission('sickness')
def record_sickness(tag):
    goat = Goat.query.filter_by(tag=tag, status="active").first()
    if not goat:
        flash("Goat not found or already removed.", "danger")
        return redirect(url_for("goats.list_goats"))
    if request.method == "POST":
        sickness = request.form["sickness"]
        medicine = request.form["medicine"]
        date = request.form["date"]
        s = Sickness(
            goat_id=goat.id,
            sickness=sickness,
            medicine=medicine,
            created_by=session.get("username"),
            created_at=datetime.utcnow(),
        )
        db.session.add(s)
        db.session.commit()
        flash(f"Sickness recorded for goat {tag}.", "success")
        return redirect(url_for("goats.list_goats"))
    today = datetime.now().strftime('%Y-%m-%d')
    return render_template("sickness_form.html", goat=goat, today=today)

@goats_bp.route("/goats/<tag>/remove", methods=["GET", "POST"])
@require_permission('remove')
def remove_goat(tag):
    goat = Goat.query.filter_by(tag=tag, status="active").first()
    if not goat:
        flash("Goat not found or already removed.", "danger")
        return redirect(url_for("goats.list_goats"))
    if request.method == "POST":
        reason = request.form["reason"]
        note = request.form["note"]
        date = request.form["date"]
        goat.status = "removed"
        r = Removal(
            goat_id=goat.id,
            reason=reason,
            note=note,
            date=date,
            created_by=session.get("username"),
            created_at=datetime.utcnow(),
        )
        db.session.add(r)
        db.session.commit()
        flash(f"Goat {tag} marked as removed ({reason}).", "info")
        return redirect(url_for("goats.list_goats"))
    today = datetime.now().strftime('%Y-%m-%d')
    return render_template("remove_goat.html", goat=goat, today=today)

@goats_bp.route("/goats/<tag>/recover", methods=["POST"])
def mark_goat_recovered(tag):
    goat = Goat.query.filter_by(tag=tag).first_or_404()
    Sickness.query.filter_by(goat_id=goat.id, status='active').update({'status': 'recovered'})
    db.session.commit()
    flash(f"Goat {tag} marked as recovered.", "success")
    return redirect(url_for("goats.goat_detail", tag=tag))

@goats_bp.route("/goats/ajax_edit/<int:goat_id>", methods=["GET"])
def ajax_edit_goat(goat_id):
    goat = Goat.query.get_or_404(goat_id)
    goat_types = GoatType.query.order_by(GoatType.name).all()
    return render_template("goat_edit_fields.html", goat=goat, goat_types=goat_types)

@goats_bp.route("/goats/ajax_edit/<int:goat_id>", methods=["POST"])
def ajax_save_goat(goat_id):
    goat = Goat.query.get_or_404(goat_id)
    data = request.form
    goat.tag = data["tag"].strip()
    goat.goat_type_id = int(data["goat_type_id"])
    goat.sex = data["sex"]
    goat.dob = data["dob"] or None
    goat.date_acquired = data["date_acquired"] or None
    goat.acquisition_method = data["acquisition_method"]
    goat.source_name = data.get("source_name")
    goat.purchase_price = float(data.get("purchase_price") or 0)
    goat.age_estimate_months = int(data.get("age_estimate_months") or 0)
    goat.weight = float(data.get("weight") or 0)
    goat.location = data.get("location")
    goat.notes = data.get("notes")
    goat.is_pregnant = 'is_pregnant' in data
    db.session.commit()
    return jsonify({"success": True, "message": "Goat updated successfully."})

@goats_bp.route("/goats/<tag>/feedback", methods=["POST"])
def add_goat_feedback(tag):
    if not session.get("username"):
        flash("Login required.", "warning")
        return redirect(url_for("auth.login"))

    content = request.form["content"].strip()
    if not content:
        flash("Feedback cannot be empty.", "warning")
        return redirect(url_for("goats.goat_detail", tag=tag))

    goat = Goat.query.filter_by(tag=tag).first_or_404()
    fb = GoatFeedback(
        goat_id=goat.id,
        content=content,
        submitted_by=session["username"]
    )
    db.session.add(fb)
    db.session.commit()

    if "photos" in request.files:
        photos = request.files.getlist("photos")
        for photo in photos:
            if photo and photo.filename:
                filename = secure_filename(f"fb_{goat.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{photo.filename}")
                save_path = os.path.join("static/uploads", filename)
                photo.save(save_path)
                fb_photo = GoatFeedbackPhoto(feedback_id=fb.id, image_path=save_path)
                db.session.add(fb_photo)
        db.session.commit()

    flash("Feedback submitted.", "success")
    return redirect(url_for("goats.goat_detail", tag=tag))

@goats_bp.route("/goats/<tag>/feedback/<int:fb_id>/delete", methods=["POST"])
@require_any_role("worker","admin", "superadmin")
def delete_goat_feedback(tag, fb_id):
    goat = Goat.query.filter_by(tag=tag).first_or_404()
    feedback = GoatFeedback.query.get_or_404(fb_id)

    if feedback.submitted_by != session["username"]:
        flash("You are not authorized to delete this feedback.", "danger")
        return redirect(url_for("goats.goat_detail", tag=tag))

    time_diff = (datetime.utcnow() - feedback.timestamp).total_seconds()
    if time_diff > 3600:
        flash("You can only delete your feedback within 1 hour.", "warning")
        return redirect(url_for("goats.goat_detail", tag=tag))

    for photo in feedback.photos:
        try:
            os.remove(photo.image_path)
        except Exception:
            pass
        db.session.delete(photo)

    db.session.delete(feedback)
    db.session.commit()

    flash("Feedback deleted successfully.", "success")
    return redirect(url_for("goats.goat_detail", tag=tag))

@goats_bp.route("/goats/<tag>/feedback/<int:fb_id>/edit", methods=["POST"])
@require_any_role("worker","admin", "superadmin")
def edit_goat_feedback(tag, fb_id):
    if not session.get("username"):
        flash("Login required.", "warning")
        return redirect(url_for("auth.login"))

    feedback = GoatFeedback.query.get_or_404(fb_id)

    if feedback.submitted_by != session["username"]:
        flash("You can only edit your own feedback.", "danger")
        return redirect(url_for("goats.goat_detail", tag=tag))

    if (datetime.utcnow() - feedback.timestamp).total_seconds() > 3600:
        flash("Feedback edit window expired (1 hour limit).", "warning")
        return redirect(url_for("goats.goat_detail", tag=tag))

    new_content = request.form.get("edit_content", "").strip()
    if not new_content:
        flash("Feedback cannot be empty.", "warning")
        return redirect(url_for("goats.goat_detail", tag=tag))

    feedback.content = new_content
    feedback.updated_at = datetime.utcnow()
    db.session.commit()

    flash("Feedback updated.", "success")
    return redirect(url_for("goats.goat_detail", tag=tag))

@goats_bp.route("/goats/<tag>/vaccine/<int:vaccine_type_id>/reschedule", methods=["POST"])
def reschedule_vaccine(tag, vaccine_type_id):
    """
    Reschedule ONLY the next due vaccination for this goat/vaccine.
    Deletes the scheduled, not-done event for the old due date,
    then creates a new scheduled event at the requested new date.
    """
    if not session.get("username"):
        return jsonify({"success": False, "error": "Login required."}), 403

    new_date = request.form.get("new_date")
    if not new_date:
        return jsonify({"success": False, "error": "No date provided"}), 400

    goat = Goat.query.filter_by(tag=tag, status="active").first_or_404()
    vt = VaccineType.query.get_or_404(vaccine_type_id)

    # Get only the next due info for this goat/vaccine
    due_info = [v for v in get_vaccine_due_info(goat) if v["vaccine"].id == vaccine_type_id]
    if not due_info:
        return jsonify({"success": False, "error": "No due vaccination found."}), 404

    next_due = due_info[0]["next_due"].strftime("%Y-%m-%d")
    # Delete any scheduled (not-done) event for this due date
    existing = VaccinationEvent.query.filter_by(
        goat_id=goat.id,
        vaccine_type_id=vt.id,
        scheduled_date=next_due,
        status="scheduled"
    ).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()

    # Prevent duplicate on new date
    already_done = VaccinationEvent.query.filter_by(
        goat_id=goat.id,
        vaccine_type_id=vt.id,
        scheduled_date=new_date,
        status="done"
    ).first()
    if already_done:
        return jsonify({"success": False, "error": "Already marked as done on this date!"}), 400

    # Create new scheduled event
    ve = VaccinationEvent(
        goat_id=goat.id,
        vaccine_type_id=vt.id,
        scheduled_date=new_date,
        status="scheduled",
        notes=f"Rescheduled by {session['username']} on {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        created_by=session.get("username"),
        created_at=datetime.utcnow(),
    )
    db.session.add(ve)
    db.session.commit()
    return jsonify({"success": True, "message": "Vaccination rescheduled.", "new_date": new_date})
