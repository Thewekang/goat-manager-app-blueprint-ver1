from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from ...models import VaccineType, VaccinationEvent, Goat, VaccineGuide, TargetWeight, Sickness
from ...extensions import db
from ...utils import require_role, require_any_role
from datetime import datetime

vaccine_bp = Blueprint("vaccine", __name__)

@vaccine_bp.route("/vaccine_types", methods=["GET", "POST"])
@require_role("superadmin")
def vaccine_types():
    guide = VaccineGuide.query.first()
    if not guide:
        guide = VaccineGuide(guide_text="Enter your vaccine/deworming program guide here...")
        db.session.add(guide)
        db.session.commit()

    if request.method == "POST":
        if "save_guide" in request.form:
            guide.guide_text = request.form.get("guide_text", "")
            db.session.commit()
            flash("Guide updated!", "success")
        elif "add_vaccine" in request.form:
            name = request.form["name"]
            if VaccineType.query.filter_by(name=name).first():
                flash("Vaccine name already exists!", "danger")
                return redirect(url_for("vaccine.vaccine_types"))
            description = request.form.get("description", "")
            min_age_days = int(request.form.get("min_age_days", 0))
            booster_schedule_days = request.form.get("booster_schedule_days", "")
            default_frequency_days = int(request.form.get("default_frequency_days", 180))
            vt = VaccineType(
                name=name,
                description=description,
                min_age_days=min_age_days,
                booster_schedule_days=booster_schedule_days,
                default_frequency_days=default_frequency_days
            )
            db.session.add(vt)
            db.session.commit()
            flash("Vaccine type added!", "success")
        return redirect(url_for("vaccine.vaccine_types"))

    types = VaccineType.query.order_by(VaccineType.name).all()
    return render_template("vaccine_types.html", types=types, guide=guide)

@vaccine_bp.route("/vaccine_types/edit/<int:vaccine_type_id>", methods=["POST"])
@require_any_role("admin", "superadmin")
def edit_vaccine_type(vaccine_type_id):
    vt = VaccineType.query.get_or_404(vaccine_type_id)
    data = request.get_json()
    from sqlalchemy import func

    if not data or "name" not in data:
        return jsonify({"success": False, "error": "Missing required data."}), 400

    duplicate = VaccineType.query.filter(
        func.lower(VaccineType.name) == data["name"].strip().lower(),
        VaccineType.id != vaccine_type_id
    ).first()
    if duplicate:
        return jsonify({"success": False, "error": "Name already in use."}), 400

    vt.name = data["name"].strip()
    vt.description = data.get("description", "").strip()
    vt.min_age_days = int(data.get("min_age_days", 0))
    vt.booster_schedule_days = data.get("booster_schedule_days", "")
    vt.default_frequency_days = int(data.get("default_frequency_days", 180))
    db.session.commit()
    return jsonify({"success": True})

@vaccine_bp.route("/vaccine_types/delete/<int:vaccine_type_id>", methods=["POST"])
@require_role("superadmin")
def delete_vaccine_type(vaccine_type_id):
    vt = VaccineType.query.get_or_404(vaccine_type_id)
    VaccinationEvent.query.filter_by(vaccine_type_id=vt.id, status="scheduled").delete()
    db.session.delete(vt)
    db.session.commit()
    flash("Vaccine type deleted. Historical vaccination records remain.", "info")
    return redirect(url_for("vaccine.vaccine_types"))

@vaccine_bp.route("/goats/<tag>/vaccine/<int:vaccine_type_id>", methods=["GET", "POST"])
def record_vaccine(tag, vaccine_type_id):
    goat = Goat.query.filter_by(tag=tag, status="active").first_or_404()
    vt = VaccineType.query.get_or_404(vaccine_type_id)
    today_str = datetime.now().strftime('%Y-%m-%d')

    if request.method == "POST":
        scheduled_date = request.form.get("scheduled_date", today_str)
        actual_date_given = request.form.get("actual_date_given") or None
        notes = request.form.get("notes", "")
        batch_number = request.form.get("batch_number", "")
        given_by = request.form.get("given_by") or session.get("username")
        status = "done" if actual_date_given else "scheduled"

        ve = VaccinationEvent.query.filter_by(
            goat_id=goat.id,
            vaccine_type_id=vt.id,
            scheduled_date=scheduled_date
        ).first()

        if ve:
            ve.actual_date_given = actual_date_given
            ve.status = status
            ve.notes = notes
            ve.given_by = given_by
            ve.batch_number = batch_number
        else:
            ve = VaccinationEvent(
                goat_id=goat.id,
                vaccine_type_id=vt.id,
                scheduled_date=scheduled_date,
                actual_date_given=actual_date_given,
                status=status,
                notes=notes,
                given_by=given_by,
                batch_number=batch_number
            )
            db.session.add(ve)
        db.session.commit()
        flash(f"{vt.name} vaccination scheduled for {goat.tag}.", "success")
        return redirect(url_for("goats.goat_detail", tag=goat.tag))

    return render_template(
        "record_vaccine.html",
        goat=goat,
        vt=vt,
        today=today_str
    )

@vaccine_bp.route("/sicklog")
def sick_log():
    # Filters
    goat_tag = request.args.get("goat_tag")
    keyword = request.args.get("keyword")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")

    logs_query = Sickness.query.order_by(Sickness.created_at.desc())

    if goat_tag:
        goat = Goat.query.filter_by(tag=goat_tag).first()
        if goat:
            logs_query = logs_query.filter_by(goat_id=goat.id)
    if keyword:
        logs_query = logs_query.filter(
            Sickness.sickness.ilike(f"%{keyword}%") |
            Sickness.medicine.ilike(f"%{keyword}%")
        )
    if date_from:
        logs_query = logs_query.filter(Sickness.date >= date_from)
    if date_to:
        logs_query = logs_query.filter(Sickness.date <= date_to)

    logs = logs_query.all()
    goats = Goat.query.filter_by(status="active").order_by(Goat.tag).all()
    return render_template("sick_log.html", logs=logs, goats=goats, goat_tag=goat_tag or '', keyword=keyword or '', date_from=date_from or '', date_to=date_to or '')

@vaccine_bp.route("/sicklog/edit/<int:log_id>", methods=["GET", "POST"])
def edit_sick_log(log_id):
    log = Sickness.query.get_or_404(log_id)
    goats = Goat.query.filter_by(status="active").order_by(Goat.tag).all()
    if request.method == "POST":
        log.goat_id = int(request.form["goat_id"])
        log.sickness = request.form["sickness"]
        log.medicine = request.form["medicine"]
        log.date = request.form["date"]
        db.session.commit()
        flash("Sickness log updated.", "success")
        return redirect(url_for("vaccine.sick_log"))
    return render_template("edit_sick_log.html", log=log, goats=goats)

@vaccine_bp.route("/sicklog/delete/<int:log_id>", methods=["POST"])
def delete_sick_log(log_id):
    log = Sickness.query.get_or_404(log_id)
    db.session.delete(log)
    db.session.commit()
    flash("Sickness log deleted.", "info")
    return redirect(url_for("vaccine.sick_log"))

@vaccine_bp.route("/sicklog/batch_delete", methods=["POST"])
def batch_delete_sick_log():
    ids = request.form.getlist("selected_logs")
    count = 0
    for log_id in ids:
        log = Sickness.query.get(log_id)
        if log:
            db.session.delete(log)
            count += 1
    db.session.commit()
    flash(f"Deleted {count} selected sickness logs.", "info")
    return redirect(url_for("vaccine.sick_log"))

@vaccine_bp.route("/vaccines/batch", methods=["GET", "POST"])
def batch_vaccine_entry():
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    all_vaccine_types = VaccineType.query.order_by(VaccineType.name).all()
    all_goats = Goat.query.filter_by(status="active").order_by(Goat.tag).all()
    today_str = datetime.now().strftime('%Y-%m-%d')

    if request.method == "POST":
        vaccine_type_id = int(request.form["vaccine_type_id"])
        actual_date_given = request.form.get("actual_date_given", today_str)
        goat_ids = request.form.getlist("goat_ids")
        notes = request.form.get("notes", "")
        batch_number = request.form.get("batch_number", "")
        given_by = request.form.get("given_by") or session.get("username")
        for goat_id in goat_ids:
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
                batch_number=batch_number
            )
            db.session.add(ve)
        db.session.commit()
        flash(f"Vaccination recorded for {len(goat_ids)} goats.", "success")
        return redirect(url_for("vaccine.batch_vaccine_entry"))

    return render_template(
        "batch_vaccine_entry.html",
        vaccine_types=all_vaccine_types,
        goats=all_goats,
        today=today_str
    )
