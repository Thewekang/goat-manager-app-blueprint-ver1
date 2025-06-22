from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from app.models import db, FarmEvent, BreedingEvent, VaccinationEvent, VaccineType, Goat
from app.utils import require_any_role, expand_recurring_event, get_vaccine_due_info
from datetime import datetime, timedelta
import json

calendar_bp = Blueprint('calendar', __name__, url_prefix='/calendar')

# API routes for calendar events
@calendar_bp.route("/api/events")
def api_events():
    from_date = request.args.get('start')
    to_date = request.args.get('end')
    if from_date and to_date:
        from_date = datetime.strptime(from_date[:10], "%Y-%m-%d").date()
        to_date = datetime.strptime(to_date[:10], "%Y-%m-%d").date()
    else:
        from_date = datetime.now().date()
        to_date = from_date + timedelta(days=30)

    events = []

    # 1. User-created custom events
    farm_events = FarmEvent.query.filter(
        FarmEvent.event_date >= from_date.strftime('%Y-%m-%d'),
        FarmEvent.event_date <= to_date.strftime('%Y-%m-%d')
    ).all()
    for e in farm_events:
        events.append({
            "id": f"custom-{e.id}",
            "title": e.title,
            "start": e.event_date,
            "category": e.category,
            "notes": e.notes,
            "createdBy": e.created_by,
            "allDay": True
        })

    # 2. Breeding events
    breeding_events = BreedingEvent.query.filter(
        BreedingEvent.mating_start_date >= from_date.strftime('%Y-%m-%d'),
        BreedingEvent.mating_start_date <= to_date.strftime('%Y-%m-%d')
    ).all()
    for b in breeding_events:
        events.append({
            "id": f"mating-{b.id}",
            "title": f"Mating: {b.buck.tag if b.buck else '-'} x {b.doe.tag if b.doe else '-'}",
            "start": b.mating_start_date,
            "end": b.mating_end_date,
            "category": "Mating",
            "notes": b.notes,
            "allDay": True
        })

    # 3. Auto-generated vaccination schedule events for all goats
    goats = Goat.query.filter_by(status="active").all()
    for goat in goats:
        due_info = get_vaccine_due_info(goat)
        for v in due_info:
            # Only add if next_due is within range and not already marked as done
            if v["next_due"] and from_date <= v["next_due"] <= to_date:
                # Check if already marked as done for that due date (avoid duplicate)
                existing = VaccinationEvent.query.filter_by(
                    goat_id=goat.id,
                    vaccine_type_id=v["vaccine"].id,
                    scheduled_date=v["next_due"].strftime("%Y-%m-%d"),
                    status="done"
                ).first()
                if not existing:
                    events.append({
                        "id": f"auto-vax-{goat.id}-{v['vaccine'].id}-{v['next_due']}",
                        "title": f"{v['vaccine'].name} - {goat.tag}",
                        "start": v["next_due"].strftime("%Y-%m-%d"),
                        "category": "Vaccination",
                        "notes": f"Due for {goat.tag}: {v['vaccine'].name}",
                        "allDay": True,
                        "goat_tag": goat.tag,
                        "vaccine_type_id": v["vaccine"].id,
                        "status": v["status"]
                    })

    # 4. Scheduled vaccination events from VaccinationEvent table
    scheduled_events = VaccinationEvent.query.filter(
        VaccinationEvent.scheduled_date >= from_date.strftime('%Y-%m-%d'),
        VaccinationEvent.scheduled_date <= to_date.strftime('%Y-%m-%d'),
        VaccinationEvent.status != "done"
    ).all()
    for ve in scheduled_events:
        goat = Goat.query.get(ve.goat_id)
        vaccine = VaccineType.query.get(ve.vaccine_type_id)
        if goat and vaccine:
            events.append({
                "id": f"vax-{ve.id}",
                "title": f"{vaccine.name} - {goat.tag}",
                "start": ve.scheduled_date,
                "category": "Vaccination",
                "notes": f"Scheduled for {goat.tag}: {vaccine.name}",
                "allDay": True,
                "goat_tag": goat.tag,
                "vaccine_type_id": vaccine.id,
                "status": ve.status
            })

    return jsonify(events)

# Add event (AJAX)
@calendar_bp.route("/api/events/add", methods=["POST"])
def api_event_add():
    data = request.get_json()
    event = FarmEvent(
        title=data["title"],
        event_date=data["event_date"],
        category=data["category"],
        notes=data.get("notes", ""),
        created_by=session.get("username")
    )
    db.session.add(event)
    db.session.commit()
    return jsonify({"success": True, "event": {
        "id": event.id,
        "title": event.title,
        "start": event.event_date,
        "category": event.category,
        "notes": event.notes,
        "createdBy": event.created_by,
        "allDay": True
    }})

# Edit event (AJAX)
@calendar_bp.route("/api/events/edit/<int:event_id>", methods=["POST"])
def api_event_edit(event_id):
    event = FarmEvent.query.get_or_404(event_id)
    data = request.get_json()
    event.title = data["title"]
    event.event_date = data["event_date"]
    event.category = data["category"]
    event.notes = data.get("notes", "")
    db.session.commit()
    return jsonify({"success": True})

# Delete event (AJAX)
@calendar_bp.route("/api/events/delete/<int:event_id>", methods=["POST"])
def api_event_delete(event_id):
    event = FarmEvent.query.get(event_id)
    if not event:
        return jsonify({"success": False, "error": "Not found"}), 404
    db.session.delete(event)
    db.session.commit()
    return jsonify({"success": True})

@calendar_bp.route("/")
def calendar():
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    from datetime import datetime, timedelta
    today = datetime.now().date()
    max_day = today + timedelta(days=30)

    # 1. Get all custom/admin events in the next 30 days
    farm_events = FarmEvent.query.filter(
        FarmEvent.event_date >= today.strftime('%Y-%m-%d'),
        FarmEvent.event_date <= max_day.strftime('%Y-%m-%d')
    ).order_by(FarmEvent.event_date.asc()).all()

    events = []
    # A. Add FarmEvent (custom/admin events)
    for e in farm_events:
        events.append({
            "id": e.id,  # Needed for edit/delete links
            "title": e.title,
            "start": e.event_date,
            "type": e.category,
            "notes": e.notes
        })
    # B. Add Breedings/Matings (in next 30 days)
    breeding_events = BreedingEvent.query.filter(
        BreedingEvent.mating_start_date >= today.strftime('%Y-%m-%d'),
        BreedingEvent.mating_start_date <= max_day.strftime('%Y-%m-%d')
    ).all()
    for b in breeding_events:
        events.append({
            "title": f"Mating: {b.buck.tag} x {b.doe.tag}",
            "start": b.mating_start_date,
            "end": b.mating_end_date,
            "type": "mating",
            "notes": b.notes
        })

    return render_template(
        "calendar.html",
        events_json=json.dumps(events),  # for JS
        events=events  # for table in Jinja
    )

@calendar_bp.route("/add", methods=["GET", "POST"])
def add_event():
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        title = request.form["title"]
        event_date = request.form["event_date"]
        category = request.form["category"]
        notes = request.form["notes"]
        recurrence = request.form.get("recurrence") or None

        event = FarmEvent(
            title=title,
            event_date=event_date,
            category=category,
            notes=notes,
            created_by=session.get("username"),
            recurrence=recurrence
        )
        db.session.add(event)
        db.session.commit()
        flash("Event added!", "success")
        return redirect(url_for("calendar.calendar"))
    return render_template("add_event.html")

@calendar_bp.route("/edit/<int:event_id>", methods=["GET", "POST"])
@require_any_role("admin", "superadmin")
def edit_event(event_id):
    from app.models import User
    event = FarmEvent.query.get_or_404(event_id)
    current_user = User.query.filter_by(username=session.get("username")).first()

    # Extra safety: Only allow admin/superadmin OR original creator
    if current_user.role not in ["admin", "superadmin"] and event.created_by != current_user.username:
        flash("Access denied!", "danger")
        return redirect(url_for("calendar.calendar"))

    if request.method == "POST":
        event.title = request.form["title"]
        event.event_date = request.form["event_date"]
        event.category = request.form["category"]
        event.notes = request.form["notes"]
        event.recurrence = request.form.get("recurrence") or None
        db.session.commit()
        flash("Event updated!", "success")
        return redirect(url_for("calendar.calendar"))

    return render_template("edit_event.html", event=event)

@calendar_bp.route("/delete/<int:event_id>", methods=["POST"])
@require_any_role("admin", "superadmin")
def delete_event(event_id):
    from app.models import User
    event = FarmEvent.query.get_or_404(event_id)
    current_user = User.query.filter_by(username=session.get("username")).first()

    # Allow only admin/superadmin OR event creator to delete
    if current_user.role not in ["admin", "superadmin"] and event.created_by != current_user.username:
        flash("Access denied!", "danger")
        return redirect(url_for("calendar.calendar"))

    db.session.delete(event)
    db.session.commit()
    flash("Event deleted.", "info")
    return redirect(url_for("calendar.calendar"))
