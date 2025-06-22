from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from ...models import Goat, BreedingEvent
from ...extensions import db
from datetime import datetime, timedelta

breeding_bp = Blueprint("breeding", __name__)

@breeding_bp.route("/breeding")
def list_breeding():
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))
    events = BreedingEvent.query.order_by(BreedingEvent.mating_start_date.desc()).all()
    return render_template("breeding_list.html", events=events)

@breeding_bp.route("/breeding/add", methods=["GET", "POST"])
def add_breeding():
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))
    bucks = Goat.query.filter_by(status="active", sex="Male").all()
    does = Goat.query.filter_by(status="active", sex="Female").all()
    today = datetime.now().strftime('%Y-%m-%d')
    default_end_date = (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d')

    if request.method == "POST":
        buck_id = request.form["buck_id"]
        doe_id = request.form["doe_id"]
        mating_start_date = request.form["mating_start_date"]
        mating_end_date = request.form["mating_end_date"]
        notes = request.form["notes"]

        event = BreedingEvent(
            buck_id=buck_id,
            doe_id=doe_id,
            mating_start_date=mating_start_date,
            mating_end_date=mating_end_date,
            notes=notes,
            status="planned",
            created_by=session.get("username"),
            created_at=datetime.utcnow(),
        )
        db.session.add(event)
        db.session.commit()
        flash("Breeding event added!", "success")
        return redirect(url_for("breeding.list_breeding"))

    return render_template(
        "add_breeding.html",
        bucks=bucks,
        does=does,
        today=today,
        default_end_date=default_end_date
    )

@breeding_bp.route("/breeding/edit/<int:event_id>", methods=["GET", "POST"])
def edit_breeding(event_id):
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))
    event = BreedingEvent.query.get_or_404(event_id)
    bucks = Goat.query.filter_by(status="active", sex="Male").all()
    does = Goat.query.filter_by(status="active", sex="Female").all()
    if request.method == "POST":
        event.buck_id = int(request.form["buck_id"])
        event.doe_id = int(request.form["doe_id"])
        event.mating_start_date = request.form["mating_start_date"]
        event.mating_end_date = request.form["mating_end_date"]
        event.notes = request.form["notes"]
        db.session.commit()
        flash("Breeding event updated!", "success")
        return redirect(url_for("breeding.list_breeding"))
    return render_template(
        "add_breeding.html",
        bucks=bucks,
        does=does,
        today=event.mating_start_date,
        default_end_date=event.mating_end_date,
        event=event
    )

@breeding_bp.route("/breeding/delete/<int:event_id>", methods=["POST"])
def delete_breeding(event_id):
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))
    event = BreedingEvent.query.get_or_404(event_id)
    db.session.delete(event)
    db.session.commit()
    flash("Breeding event deleted.", "info")
    return redirect(url_for("breeding.list_breeding"))

@breeding_bp.route("/does/ready")
def does_ready():
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))
    from ...utils import get_ready_does
    ready_does = get_ready_does()
    return render_template("does_ready.html", ready_does=ready_does)
