import os
import json
import csv
import io
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for, session, flash,
    Response, make_response
)
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import func, and_, or_, desc
import pdfkit



app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///goatmanager.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = os.urandom(24)
db = SQLAlchemy(app)
migrate = Migrate(app, db)

UPLOAD_FOLDER = os.path.join("static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

from flask_mail import Mail, Message

app.config['MAIL_SERVER'] = 'smtp.gmail.com'         # Or your provider
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'your_email@gmail.com'
app.config['MAIL_PASSWORD'] = 'your_app_password'    # Use an App Password, not your real password

mail = Mail(app)


# --- Permission Decorator ---
def require_permission(permission):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not session.get("username"):
                flash("Please login first.", "warning")
                return redirect(url_for("login"))
            user = User.query.filter_by(username=session.get("username")).first()
            if not (user and user.has_permission(permission)):
                flash(f"You do not have permission for this action ({permission}).", "danger")
                return redirect(url_for("home"))
            return func(*args, **kwargs)
        return wrapper
    return decorator

# --- Role-Based Decorators ---

def require_role(role_required):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not session.get("username"):
                flash("Please login first.", "warning")
                return redirect(url_for("login"))
            user = User.query.filter_by(username=session["username"]).first()
            if not user or user.role != role_required:
                flash(f"Access denied: {role_required} only.", "danger")
                return redirect(url_for("home"))
            return func(*args, **kwargs)
        return wrapper
    return decorator


def require_any_role(*roles):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not session.get("username"):
                flash("Please login first.", "warning")
                return redirect(url_for("login"))
            user = User.query.filter_by(username=session["username"]).first()
            if not user or user.role not in roles:
                flash("Access denied: insufficient privileges.", "danger")
                return redirect(url_for("home"))
            return func(*args, **kwargs)
        return wrapper
    return decorator

# --- Utility Functions ---
def get_ready_does(min_days=21):
    does = Goat.query.filter_by(status="active", sex="Female").all()
    ready_does = []
    today = datetime.now().date()
    for doe in does:
        last_breeding = (
            BreedingEvent.query
            .filter_by(doe_id=doe.id)
            .order_by(BreedingEvent.mating_end_date.desc())
            .first()
        )
        if last_breeding:
            last_mate_end = datetime.strptime(last_breeding.mating_end_date, "%Y-%m-%d").date()
            days_since_last_mate = (today - last_mate_end).days
            if days_since_last_mate >= min_days:
                ready_does.append((doe, last_breeding, days_since_last_mate))
        else:
            ready_does.append((doe, None, None))
    return ready_does

def expand_recurring_event(event, from_date, to_date):
    """
    Returns a list of event dicts representing each instance of a recurring event within the date range.
    """
    events = []
    dt = datetime.strptime(event.event_date, "%Y-%m-%d").date()
    start = from_date
    end = to_date
    current = dt

    if not event.recurrence:
        # Not recurring
        if start <= current <= end:
            events.append({
                "id": event.id,
                "title": event.title,
                "start": event.event_date,
                "category": event.category,
                "notes": event.notes,
                "createdBy": event.created_by,
                "recurrence": event.recurrence,
                "allDay": True
            })
        return events

    # Recurring: expand as needed
    while current <= end:
        if current >= start:
            events.append({
                "id": f"rec-{event.id}-{current}",
                "title": event.title,
                "start": current.isoformat(),
                "category": event.category,
                "notes": event.notes,
                "createdBy": event.created_by,
                "recurrence": event.recurrence,
                "allDay": True
            })
        # Move to next occurrence
        if event.recurrence == "daily":
            current += timedelta(days=1)
        elif event.recurrence == "weekly":
            current += timedelta(weeks=1)
        elif event.recurrence == "monthly":
            # Jump to same day next month, simple version:
            month = current.month + 1
            year = current.year
            if month > 12:
                month = 1
                year += 1
            try:
                current = current.replace(year=year, month=month)
            except ValueError:
                # If next month has no such day, go to last day of month
                from calendar import monthrange
                last_day = monthrange(year, month)[1]
                current = current.replace(year=year, month=month, day=last_day)
        else:
            break  # Unknown recurrence, just exit
    return events

def get_vaccine_due_info(goat):
    """Returns a list of dicts: [{vaccine, last_given, next_due, status}] for this goat"""
    result = []
    today = datetime.now().date()
    for vt in VaccineType.query.all():
        dob = datetime.strptime(goat.dob, "%Y-%m-%d").date() if goat.dob else None
        if not dob or (today - dob).days < vt.min_age_days:
            continue  # Too young

        # 1. Find future scheduled vaccination event (not done)
        scheduled_event = (
            VaccinationEvent.query
            .filter_by(goat_id=goat.id, vaccine_type_id=vt.id, status="scheduled")
            .order_by(VaccinationEvent.scheduled_date.asc())
            .first()
        )
        if scheduled_event:
            next_due = datetime.strptime(scheduled_event.scheduled_date, "%Y-%m-%d").date()
            last_given = None
            # Also, look for last done
            last_done = (
                VaccinationEvent.query
                .filter_by(goat_id=goat.id, vaccine_type_id=vt.id, status="done")
                .order_by(VaccinationEvent.actual_date_given.desc())
                .first()
            )
            if last_done:
                last_given = datetime.strptime(last_done.actual_date_given, "%Y-%m-%d").date()
            status = "overdue" if today > next_due else "due"
            result.append(dict(
                vaccine=vt,
                last_given=last_given,
                next_due=next_due,
                status=status,
            ))
            continue  # Skip further calculation for this vaccine

        # 2. Else, calculate as before based on done events
        records = [v for v in goat.vaccination_events if v.vaccine_type_id == vt.id and v.actual_date_given]
        records = sorted(records, key=lambda v: v.actual_date_given)
        boosters = [int(x.strip()) for x in vt.booster_schedule_days.split(",") if x.strip()]

        if not records:
            next_due = dob + timedelta(days=vt.min_age_days)
            last_given = None
            status = "overdue" if today > next_due else "due"
        else:
            last_given_date = datetime.strptime(records[-1].actual_date_given, "%Y-%m-%d").date()
            dose_num = len(records)
            if dose_num <= len(boosters):
                next_due = records[0].actual_date_given
                for i in range(dose_num):
                    next_due = datetime.strptime(records[i].actual_date_given, "%Y-%m-%d").date()
                interval = boosters[dose_num-1] if dose_num-1 < len(boosters) else vt.default_frequency_days
                next_due = last_given_date + timedelta(days=interval)
            else:
                next_due = last_given_date + timedelta(days=vt.default_frequency_days)
            last_given = last_given_date
            status = "overdue" if today > next_due else "due"
        result.append(dict(
            vaccine=vt,
            last_given=last_given,
            next_due=next_due,
            status=status,
        ))
    return result


def get_target_weight(goat):
    if not goat.goat_type_id:
        return None
    from datetime import datetime
    # Assume you have a way to get age_months
    if goat.dob:
        dob = datetime.strptime(goat.dob, "%Y-%m-%d")
        age_months = (datetime.now() - dob).days // 30
    else:
        age_months = goat.age_estimate_months or 0

    q = (TargetWeight.query
         .filter_by(goat_type_id=goat.goat_type_id)
         .filter((TargetWeight.sex == goat.sex) | (TargetWeight.sex == None))
         .filter(TargetWeight.age_months <= age_months)
         .order_by(TargetWeight.age_months.desc())
         .first())
    if q:
        return q.min_weight
    return None

@app.before_request
def check_user_status():
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
        return redirect(url_for("login"))


# --- Models ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    full_name = db.Column(db.String(100))
    email = db.Column(db.String(100))
    phone = db.Column(db.String(30))
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # superadmin, admin, worker
    permissions = db.Column(db.String(500), default="")  # optional per-form permissions
    must_change_password = db.Column(db.Boolean, default=False)
    created_by = db.Column(db.String(50))
    status = db.Column(db.String(10), default="active")  # active/inactive
    last_login = db.Column(db.DateTime)

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)
        self.must_change_password = False

    def set_temp_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)
        self.must_change_password = True

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def has_permission(self, perm):
        if self.role == "superadmin":
            return True
        perms = self.permissions.split(",") if self.permissions else []
        return perm in perms

class PasswordResetRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    resolved = db.Column(db.Boolean, default=False)
    user = db.relationship("User", backref="reset_requests")


class Goat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tag = db.Column(db.String(50), unique=True, nullable=False)
    goat_type_id = db.Column(db.Integer, db.ForeignKey('goat_type.id'), nullable=False)
    goat_type = db.relationship('GoatType')
    sex = db.Column(db.String(10))
    is_pregnant = db.Column(db.Boolean, default=False)  # Manual control by user
    dob = db.Column(db.String(20), nullable=True)
    date_acquired = db.Column(db.String(20), nullable=False)
    acquisition_method = db.Column(db.String(20), nullable=False)
    source_name = db.Column(db.String(50), nullable=True)
    purchase_price = db.Column(db.Float, nullable=True)
    age_estimate_months = db.Column(db.Integer, nullable=True)
    weight = db.Column(db.Float)
    status = db.Column(db.String(20), default="active")
    added_by = db.Column(db.String(50))
    location = db.Column(db.String(50))
    notes = db.Column(db.String(200), nullable=True)
    @property
    def tags(self):
        tags = []
        today = datetime.now().date()

        # 1. Pregnant (manual mark)
        if self.is_pregnant:
            tags.append("pregnant")

        # 2. Underweight
        target = get_target_weight(self)
        if target and self.weight and self.weight < target:
            tags.append("underweight")

        # 3. Sick (any active sickness record)
        latest_sick = Sickness.query.filter_by(goat_id=self.id, status='active').order_by(Sickness.created_at.desc()).first()
        if latest_sick:
            tags.append("sick")

        # 4. Ready to Mate (doe, not pregnant, not sick, last mating ended >21 days ago or never mated)
        if self.sex == "Female" and not self.is_pregnant and not latest_sick:
            last_breeding = None
            if hasattr(self, 'breedings_as_doe'):
                last_breeding = sorted(self.breedings_as_doe, key=lambda e: e.mating_end_date or '', reverse=True)
                last_breeding = last_breeding[0] if last_breeding else None
            if last_breeding and last_breeding.mating_end_date:
                days_since = (today - datetime.strptime(last_breeding.mating_end_date, "%Y-%m-%d").date()).days
                if days_since >= 21:
                    tags.append("ready to mate")
            else:
                tags.append("ready to mate")

        # 5. Old (age over X months/years, e.g. 6 years = 72 months)
        age_days = 0
        if self.dob:
            age_days = (today - datetime.strptime(self.dob, '%Y-%m-%d').date()).days
        elif self.age_estimate_months:
            age_days = self.age_estimate_months * 30
        if age_days >= 6*365:
            tags.append("old")

        # 6. New Arrival (first 60 days after acquired)
        if self.date_acquired:
            days_since_acquired = (today - datetime.strptime(self.date_acquired, "%Y-%m-%d").date()).days
            if days_since_acquired < 60:
                tags.append("new arrival")

        # 7. New Born (first 60 days after born)
        if self.dob:
            days_since_born = (today - datetime.strptime(self.dob, "%Y-%m-%d").date()).days
            if days_since_born < 60:
                tags.append("new born")

        # 8. Matured (e.g. 1 year = 365 days)
        if age_days >= 365:
            tags.append("matured")

        return tags


class GoatType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)

class Sickness(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    goat_id = db.Column(db.Integer, db.ForeignKey('goat.id'))
    sickness = db.Column(db.String(100))
    status = db.Column(db.String(20), default='active')  # 'active' or 'recovered'
    medicine = db.Column(db.String(100))
    created_by = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    image_path = db.Column(db.String(200))  # <-- add this line
    goat = db.relationship('Goat', backref=db.backref('sicknesses', lazy=True))

class SicknessPhoto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sickness_id = db.Column(db.Integer, db.ForeignKey('sickness.id'))
    image_path = db.Column(db.String(200))
    sickness = db.relationship('Sickness', backref=db.backref('photos', lazy=True))

class Removal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    goat_id = db.Column(db.Integer, db.ForeignKey('goat.id'))
    date = db.Column(db.String(20))
    reason = db.Column(db.String(100))
    notes = db.Column(db.Text)
    certificate_path = db.Column(db.String(200))
    created_by = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    goat = db.relationship('Goat', backref=db.backref('removals', lazy=True))

class FarmConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    farm_name = db.Column(db.String(100))

class BreedingEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    buck_id = db.Column(db.Integer, db.ForeignKey('goat.id'))
    doe_id = db.Column(db.Integer, db.ForeignKey('goat.id'))
    mating_start_date = db.Column(db.String(20))
    mating_end_date = db.Column(db.String(20))
    notes = db.Column(db.String(200))
    status = db.Column(db.String(20), default="planned")
    created_by = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    buck = db.relationship('Goat', foreign_keys=[buck_id], backref='breedings_as_buck')
    doe = db.relationship('Goat', foreign_keys=[doe_id], backref='breedings_as_doe')

class FarmEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    event_date = db.Column(db.String(20), nullable=False)
    category = db.Column(db.String(50), nullable=False)  # "Mating", "Vaccination", "Custom", etc.
    notes = db.Column(db.String(200))
    created_by = db.Column(db.String(50))
    recurrence = db.Column(db.String(20), nullable=True)  # e.g. 'daily', 'weekly', 'monthly'

class VaccineType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True)  # e.g. "FMD", "Deworming"
    description = db.Column(db.String(200))
    min_age_days = db.Column(db.Integer, default=0)  # Minimum age to start (days)
    booster_schedule_days = db.Column(db.String(200))  # CSV, e.g. "28,180,365" (after how many days to schedule next doses)
    default_frequency_days = db.Column(db.Integer, default=180)  # Routine repeat after booster schedule done

class VaccinationEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    goat_id = db.Column(db.Integer, db.ForeignKey('goat.id'))
    vaccine_type_id = db.Column(db.Integer, db.ForeignKey('vaccine_type.id'))
    scheduled_date = db.Column(db.String(20))
    actual_date_given = db.Column(db.String(20))
    status = db.Column(db.String(20))  # "scheduled", "done", "overdue"
    notes = db.Column(db.Text)
    batch_number = db.Column(db.String(50))
    given_by = db.Column(db.String(50))
    created_by = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    goat = db.relationship('Goat', backref=db.backref('vaccination_events', lazy=True))
    vaccine_type = db.relationship('VaccineType', backref=db.backref('events', lazy=True))

    __table_args__ = (
        db.UniqueConstraint('goat_id', 'vaccine_type_id', 'scheduled_date', name='uix_1'),
    )


class VaccineGuide(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    guide_text = db.Column(db.Text)
    image_path = db.Column(db.String(200), default="img/vaccine_guide_placeholder.jpg")

class WeightLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    goat_id = db.Column(db.Integer, db.ForeignKey('goat.id'), nullable=False)
    date = db.Column(db.String(20), nullable=False)
    weight = db.Column(db.Float, nullable=False)
    created_by = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    goat = db.relationship('Goat', backref=db.backref('weight_logs', lazy=True))

class TargetWeight(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    goat_type_id = db.Column(db.Integer, db.ForeignKey('goat_type.id'), nullable=False)
    sex = db.Column(db.String(10), nullable=True)
    age_months = db.Column(db.Integer, nullable=False)
    min_weight = db.Column(db.Float, nullable=False)
    goat_type = db.relationship('GoatType')

class GoatFeedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    goat_id = db.Column(db.Integer, db.ForeignKey('goat.id'), nullable=False)
    content = db.Column(db.String(300), nullable=False)
    submitted_by = db.Column(db.String(50), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    image_path = db.Column(db.String(200)) 
    updated_at = db.Column(db.DateTime)



    goat = db.relationship('Goat', backref=db.backref('feedbacks', lazy=True))

class GoatFeedbackPhoto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    feedback_id = db.Column(db.Integer, db.ForeignKey('goat_feedback.id'))
    image_path = db.Column(db.String(200))
    feedback = db.relationship('GoatFeedback', backref=db.backref('photos', lazy=True))


from flask import jsonify

# List all events as JSON (for FullCalendar)
@app.route("/api/events")
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

    # 4. (Optional) Scheduled vaccination events from VaccinationEvent table (e.g., batch scheduled by user)
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


    # ✅ Put this at the end
    return jsonify(events)


# Add event (AJAX)
@app.route("/api/events/add", methods=["POST"])
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
@app.route("/api/events/edit/<int:event_id>", methods=["POST"])
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
@app.route("/api/events/delete/<int:event_id>", methods=["POST"])
def api_event_delete(event_id):
    event = FarmEvent.query.get(event_id)
    if not event:
        return jsonify({"success": False, "error": "Not found"}), 404
    db.session.delete(event)
    db.session.commit()
    return jsonify({"success": True})

# --- Context for current date (for sickness form) ---
@app.context_processor
def inject_now():
    return {'now': datetime.now}

@app.context_processor
def inject_target_weight():
    return dict(get_target_weight=get_target_weight)

@app.context_processor
def inject_current_user():
    from flask import session
    user = None
    if 'username' in session:
        user = User.query.filter_by(username=session['username']).first()
    return {'current_user': user}

@app.template_filter('todate')
def todate_filter(s, fmt="%Y-%m-%d"):
    from datetime import datetime
    return datetime.strptime(s, fmt).date()

# --- Routes ---

@app.route("/")
def home():
    if session.get("username"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            if user.status != "active":
                flash("Account is inactive.", "danger")
                return redirect(url_for("login"))

            session["username"] = user.username
            session["role"] = user.role
            user.last_login = datetime.now()
            db.session.commit()

            if user.must_change_password:
                flash("Please change your password before continuing.", "warning")
                return redirect(url_for("force_change_password"))

            flash("Login successful!", "success")
            # 🚩 Redirect to dashboard, not home
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid username or password", "danger")
    return render_template("login.html")



@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("home"))

@app.route("/force_change_password", methods=["GET", "POST"])
def force_change_password():
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("login"))

    user = User.query.filter_by(username=session["username"]).first()

    if not user.must_change_password:
        return redirect(url_for("home"))

    if request.method == "POST":
        new_pw = request.form["new_password"]
        confirm_pw = request.form["confirm_password"]

        if new_pw != confirm_pw:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("force_change_password"))

        user.set_password(new_pw)
        db.session.commit()
        flash("Password updated. You can now use the app.", "success")
        return redirect(url_for("home"))

    return render_template("force_change_password.html")


@app.route("/setup", methods=["GET", "POST"])
@require_role("superadmin")
def setup():
    config = FarmConfig.query.first()

    # Handle POST actions
    if request.method == "POST":
        # Update farm name if present
        if "farm_name" in request.form:
            config.farm_name = request.form["farm_name"]
            db.session.commit()
            flash("Farm name updated!", "success")

        # Add new goat type
        new_type = request.form.get("add_goat_type")
        if new_type:
            new_type = new_type.strip()
            if new_type and not GoatType.query.filter_by(name=new_type).first():
                db.session.add(GoatType(name=new_type))
                db.session.commit()
                flash("Goat type added!", "success")

        # Delete goat type
        if "delete_type" in request.form:
            t = GoatType.query.get(int(request.form["delete_type"]))
            if t:
                db.session.delete(t)
                db.session.commit()
                flash("Goat type deleted!", "info")
        return redirect(url_for("setup"))

    goat_types = GoatType.query.order_by(GoatType.name).all()
    return render_template("setup.html", config=config, goat_types=goat_types)


@app.route("/goats/ajax_edit/<int:goat_id>", methods=["GET"])
def ajax_edit_goat(goat_id):
    goat = Goat.query.get_or_404(goat_id)
    goat_types = GoatType.query.order_by(GoatType.name).all()
    return render_template("goat_edit_fields.html", goat=goat, goat_types=goat_types)

@app.route("/goats/ajax_edit/<int:goat_id>", methods=["POST"])
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

@app.route("/goats/add", methods=["GET", "POST"])
def add_goat():
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("login"))

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

        # Logic for acquisition date
        date_acquired = request.form.get("date_acquired") or None
        if acquisition_method == "Born":
            if not dob:
                flash("Date of Birth is required for goats born on farm.", "danger")
                return redirect(url_for("add_goat"))
            # Optionally, set date_acquired = dob for consistency
            date_acquired = dob
        else:
            if not date_acquired:
                flash("Date Acquired is required for purchased/donated goats.", "danger")
                return redirect(url_for("add_goat"))

        purchase_price = float(purchase_price) if purchase_price else None
        age_estimate_months = int(age_estimate_months) if age_estimate_months else None
        weight = float(weight) if weight else None

        if Goat.query.filter_by(tag=tag, status="active").first():
            flash(f"Tag {tag} is already in use!", "danger")
            return redirect(url_for("add_goat"))

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
        # Suggest user to record vaccination history for older goats
        if acquisition_method != "Born":
            flash("Please record initial vaccination dates for this goat using 'Batch Vaccination' or on the goat profile page.", "warning")
        return redirect(url_for("list_goats"))

    return render_template("add_goat.html", goat_types=goat_types, goat=None)



@app.route("/goats")
def list_goats():
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("login"))

    selected_tags = request.args.getlist('tags')
    selected_location = request.args.get("location")
    locations = db.session.query(Goat.location).distinct().all()
    locations = [loc[0] for loc in locations if loc[0]]

    # Start with active goats
    goats = Goat.query.filter_by(status="active").all()

    # Tag filter first
    if selected_tags:
        goats = [g for g in goats if any(tag in g.tags for tag in selected_tags)]
    # Location filter next
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


@app.route("/goats/edit/<int:goat_id>", methods=["GET", "POST"])
def edit_goat(goat_id):
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("login"))
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
        return redirect(url_for("goat_detail", tag=goat.tag))

    return render_template("edit_goat.html", goat_types=goat_types, goat=goat)
    # Or use "edit_goat.html" if you want a separate template

@app.route("/goats/<tag>")
def goat_detail(tag):
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("login"))

    goat = Goat.query.filter_by(tag=tag).first_or_404()
    vaccine_due_info = get_vaccine_due_info(goat)

    # Calculate age_days in Python
    if goat.dob:
        age_days = (datetime.now().date() - datetime.strptime(goat.dob, '%Y-%m-%d').date()).days
    elif goat.age_estimate_months:
        age_days = goat.age_estimate_months * 30
    else:
        age_days = 0

    has_any_vaccine = bool(goat.vaccination_events)

    # --- Pagination setup ---
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


@app.route("/goats/<tag>/vaccine/<int:vaccine_type_id>/reschedule", methods=["POST"])
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
        given_by=given_by,
        created_by=session.get("username"),
        created_at=datetime.utcnow(),
    )
    db.session.add(ve)
    db.session.commit()
    return jsonify({"success": True, "message": "Vaccination rescheduled.", "new_date": new_date})


@app.route("/goats/<tag>/add_weight", methods=["POST"])
def add_weight_log(tag):
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("login"))
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
    # Optionally, update goat’s main weight to latest
    goat.weight = weight
    db.session.commit()
    flash("Weight log added!", "success")
    return redirect(url_for("goat_detail", tag=goat.tag))


@app.route("/goats/<tag>/sickness", methods=["GET", "POST"])
@require_permission('sickness')
def record_sickness(tag):
    goat = Goat.query.filter_by(tag=tag, status="active").first()
    if not goat:
        flash("Goat not found or already removed.", "danger")
        return redirect(url_for("list_goats"))
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
        return redirect(url_for("list_goats"))
    today = datetime.now().strftime('%Y-%m-%d')
    return render_template("sickness_form.html", goat=goat, today=today)

@app.route("/goats/sicklog")
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


@app.route("/goats/<tag>/remove", methods=["GET", "POST"])
@require_permission('remove')
def remove_goat(tag):
    goat = Goat.query.filter_by(tag=tag, status="active").first()
    if not goat:
        flash("Goat not found or already removed.", "danger")
        return redirect(url_for("list_goats"))
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
        return redirect(url_for("list_goats"))
    today = datetime.now().strftime('%Y-%m-%d')
    return render_template("remove_goat.html", goat=goat, today=today)

@app.route("/goats/<tag>/recover", methods=["POST"])
def mark_goat_recovered(tag):
    goat = Goat.query.filter_by(tag=tag).first_or_404()
    # Mark all active Sickness as recovered
    Sickness.query.filter_by(goat_id=goat.id, status='active').update({'status': 'recovered'})
    db.session.commit()
    flash(f"Goat {tag} marked as recovered.", "success")
    return redirect(url_for("goat_detail", tag=tag))

@app.route("/sicklog/photo/delete/<int:photo_id>", methods=["POST"])
def delete_sickness_photo(photo_id):
    photo = SicknessPhoto.query.get_or_404(photo_id)
    # Remove file from disk (optional)
    if os.path.exists(photo.image_path):
        os.remove(photo.image_path)
    db.session.delete(photo)
    db.session.commit()
    flash("Photo deleted.", "info")
    next_url = request.form.get("next")
    return redirect(next_url or url_for("sick_log"))

@app.route("/goats/<tag>/feedback", methods=["POST"])
def add_goat_feedback(tag):
    if not session.get("username"):
        flash("Login required.", "warning")
        return redirect(url_for("login"))

    content = request.form["content"].strip()
    if not content:
        flash("Feedback cannot be empty.", "warning")
        return redirect(url_for("goat_detail", tag=tag))

    goat = Goat.query.filter_by(tag=tag).first_or_404()
    fb = GoatFeedback(
        goat_id=goat.id,
        content=content,
        submitted_by=session["username"]
    )
    db.session.add(fb)
    db.session.commit()

    # --- Optional Photo Upload ---
    if "photos" in request.files:
        photos = request.files.getlist("photos")
        for photo in photos:
            if photo and photo.filename:
                filename = secure_filename(f"fb_{goat.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{photo.filename}")
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                photo.save(save_path)
                fb_photo = GoatFeedbackPhoto(feedback_id=fb.id, image_path=save_path)
                db.session.add(fb_photo)
        db.session.commit()

    flash("Feedback submitted.", "success")
    return redirect(url_for("goat_detail", tag=tag))

@app.route("/goats/<tag>/feedback/<int:fb_id>/delete", methods=["POST"])
@require_any_role("worker","admin", "superadmin")
def delete_goat_feedback(tag, fb_id):
    goat = Goat.query.filter_by(tag=tag).first_or_404()
    feedback = GoatFeedback.query.get_or_404(fb_id)

    # Only allow the original submitter within 1 hour
    if feedback.submitted_by != session["username"]:
        flash("You are not authorized to delete this feedback.", "danger")
        return redirect(url_for("goat_detail", tag=tag))

    time_diff = (datetime.utcnow() - feedback.timestamp).total_seconds()
    if time_diff > 3600:
        flash("You can only delete your feedback within 1 hour.", "warning")
        return redirect(url_for("goat_detail", tag=tag))

    # Delete photos from disk and DB
    for photo in feedback.photos:
        try:
            os.remove(photo.image_path)
        except Exception:
            pass
        db.session.delete(photo)

    db.session.delete(feedback)
    db.session.commit()

    flash("Feedback deleted successfully.", "success")
    return redirect(url_for("goat_detail", tag=tag))

@app.route("/goats/<tag>/feedback/<int:fb_id>/edit", methods=["POST"])
@require_any_role("worker","admin", "superadmin")
def edit_goat_feedback(tag, fb_id):
    if not session.get("username"):
        flash("Login required.", "warning")
        return redirect(url_for("login"))

    feedback = GoatFeedback.query.get_or_404(fb_id)

    # Owner check
    if feedback.submitted_by != session["username"]:
        flash("You can only edit your own feedback.", "danger")
        return redirect(url_for("goat_detail", tag=tag))

    # Time check (within 1 hour)
    if (datetime.utcnow() - feedback.timestamp).total_seconds() > 3600:
        flash("Feedback edit window expired (1 hour limit).", "warning")
        return redirect(url_for("goat_detail", tag=tag))

    new_content = request.form.get("edit_content", "").strip()
    if not new_content:
        flash("Feedback cannot be empty.", "warning")
        return redirect(url_for("goat_detail", tag=tag))

    feedback.content = new_content
    feedback.updated_at = datetime.utcnow()
    db.session.commit()

    flash("Feedback updated.", "success")
    return redirect(url_for("goat_detail", tag=tag))


@app.route("/sicklog/edit/<int:log_id>", methods=["GET", "POST"])
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
        return redirect(url_for("sick_log"))
    return render_template("edit_sick_log.html", log=log, goats=goats)

@app.route("/sicklog/delete/<int:log_id>", methods=["POST"])
def delete_sick_log(log_id):
    log = Sickness.query.get_or_404(log_id)
    db.session.delete(log)
    db.session.commit()
    flash("Sickness log deleted.", "info")
    return redirect(url_for("sick_log"))

@app.route("/sicklog/batch_delete", methods=["POST"])
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
    return redirect(url_for("sick_log"))

@app.route("/sicklog/recover/<int:log_id>", methods=["POST"])
def mark_sickness_recovered(log_id):
    log = Sickness.query.get_or_404(log_id)
    log.status = 'recovered'
    db.session.commit()
    flash("Sickness log marked as recovered.", "success")
    return redirect(url_for("goat_detail", tag=log.goat.tag))


@app.route("/breeding/add", methods=["GET", "POST"])
def add_breeding():
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("login"))
    
    # Only active bucks and does by sex
    bucks = Goat.query.filter_by(status="active", sex="Male").all()
    does = Goat.query.filter_by(status="active", sex="Female").all()
    today = datetime.now().strftime('%Y-%m-%d')
    default_end_date = (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d')  # default 2 days

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
        return redirect(url_for("list_breeding"))

    return render_template(
        "add_breeding.html",
        bucks=bucks,
        does=does,
        today=today,
        default_end_date=default_end_date
    )


@app.route("/breeding")
def list_breeding():
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("login"))
    events = BreedingEvent.query.order_by(BreedingEvent.mating_start_date.desc()).all()
    return render_template("breeding_list.html", events=events)

@app.route("/breeding/edit/<int:event_id>", methods=["GET", "POST"])
def edit_breeding(event_id):
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("login"))
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
        return redirect(url_for("list_breeding"))
    return render_template("add_breeding.html", bucks=bucks, does=does, today=event.mating_start_date, default_end_date=event.mating_end_date, event=event)

@app.route("/breeding/delete/<int:event_id>", methods=["POST"])
def delete_breeding(event_id):
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("login"))
    event = BreedingEvent.query.get_or_404(event_id)
    db.session.delete(event)
    db.session.commit()
    flash("Breeding event deleted.", "info")
    return redirect(url_for("list_breeding"))


@app.route("/does/ready")
def does_ready():
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("login"))

    ready_does = get_ready_does()
    return render_template("does_ready.html", ready_does=ready_does)

@app.route("/dashboard")
def dashboard():
    config = FarmConfig.query.first()
    goat_types = GoatType.query.order_by(GoatType.name).all()  # <-- Use DB, not CSV

    total_goats = Goat.query.filter_by(status="active").count()
    removed_goats = Goat.query.filter_by(status="removed").count()
    avg_weight = db.session.query(func.avg(Goat.weight)).filter_by(status="active").scalar() or 0

    acquisition_counts = db.session.query(
        Goat.acquisition_method, func.count(Goat.id)
    ).group_by(Goat.acquisition_method).all()

    # Count goats per type using goat_type_id
    goats_by_type = [
        Goat.query.filter_by(goat_type_id=gt.id, status="active").count() for gt in goat_types
    ]

    sickness_types = db.session.query(Sickness.sickness, func.count(Sickness.id)).group_by(Sickness.sickness).all()
    sickness_labels = [s[0] for s in sickness_types]
    sickness_counts = [s[1] for s in sickness_types]

    now = datetime.now()
    one_week_ago = (now - timedelta(days=7)).strftime('%Y-%m-%d')
    weekly_new_goats = Goat.query.filter(Goat.status == "active", Goat.dob >= one_week_ago).count()

    removals_by_reason = db.session.query(Removal.reason, func.count(Removal.id)).group_by(Removal.reason).all()
    removal_labels = [r[0] for r in removals_by_reason]
    removal_counts = [r[1] for r in removals_by_reason]

    ready_does = get_ready_does()
    num_ready_does = len(ready_does)

    recent_breedings = BreedingEvent.query.order_by(BreedingEvent.mating_start_date.desc()).limit(5).all()

    today = datetime.now().date()
    upcoming_vax = []
    overdue_vax = []

    for goat in Goat.query.filter_by(status="active").all():
        due_info = get_vaccine_due_info(goat)
        for v in due_info:
            if v["status"] == "overdue":
                overdue_vax.append({
                    "goat": goat, 
                    "vaccine": v["vaccine"].name, 
                    "vaccine_id": v["vaccine"].id, 
                    "due": v["next_due"]
                })
            elif v["status"] == "due" and (v["next_due"] - today).days <= 7:
                upcoming_vax.append({
                    "goat": goat, 
                    "vaccine": v["vaccine"].name, 
                    "vaccine_id": v["vaccine"].id,
                    "due": v["next_due"]
                })

    goats = Goat.query.filter_by(status="active").all()
    sick_goats = [g for g in goats if 'sick' in g.tags]
    num_sick_goats = len(sick_goats)
    underweight = [g for g in goats if get_target_weight(g) and g.weight and g.weight < get_target_weight(g)]
    num_underweight = len(underweight)
    vaccine_type_ids = {vt.name: vt.id for vt in VaccineType.query.all()}

    return render_template("dashboard.html",
        total=total_goats,
        removed=removed_goats,
        avg_weight=round(avg_weight, 2),
        goats_by_type=goats_by_type,
        goat_types=[gt.name for gt in goat_types],  # Send names for chart labels
        sickness_labels=sickness_labels,
        sickness_counts=sickness_counts,
        weekly_new_goats=weekly_new_goats,
        removal_labels=removal_labels,
        removal_counts=removal_counts,
        num_ready_does=num_ready_does,
        recent_breedings=recent_breedings,
        overdue_vax=overdue_vax,
        upcoming_vax=upcoming_vax,
        num_underweight=num_underweight,
        underweight=underweight,
        vaccine_type_ids=vaccine_type_ids,
        sick_goats=sick_goats,
        num_sick_goats=num_sick_goats
    )

@app.route("/calendar")
def calendar():
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("login"))

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

    # C. (Optional) Add Vaccination or other event types if/when you create the model
    # for v in VaccinationEvent.query... (similarly)

    import json
    return render_template(
        "calendar.html",
        events_json=json.dumps(events),  # for JS
        events=events  # for table in Jinja
)

@app.route("/calendar/add", methods=["GET", "POST"])
def add_event():
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("login"))
    if request.method == "POST":
        title = request.form["title"]
        event_date = request.form["event_date"]
        category = request.form["category"]
        notes = request.form["notes"]
        recurrence = request.form.get("recurrence") or None   # <-- ADD THIS LINE

        event = FarmEvent(
            title=title,
            event_date=event_date,
            category=category,
            notes=notes,
            created_by=session.get("username"),
            recurrence=recurrence          # <-- AND THIS LINE
        )
        db.session.add(event)
        db.session.commit()
        flash("Event added!", "success")
        return redirect(url_for("calendar"))
    return render_template("add_event.html")

@app.route("/calendar/edit/<int:event_id>", methods=["GET", "POST"])
@require_any_role("admin", "superadmin")  # Allow admins by default
def edit_event(event_id):
    event = FarmEvent.query.get_or_404(event_id)
    current_user = User.query.filter_by(username=session.get("username")).first()

    # Extra safety: Only allow admin/superadmin OR original creator
    if current_user.role not in ["admin", "superadmin"] and event.created_by != current_user.username:
        flash("Access denied!", "danger")
        return redirect(url_for("calendar"))

    if request.method == "POST":
        event.title = request.form["title"]
        event.event_date = request.form["event_date"]
        event.category = request.form["category"]
        event.notes = request.form["notes"]
        event.recurrence = request.form.get("recurrence") or None
        db.session.commit()
        flash("Event updated!", "success")
        return redirect(url_for("calendar"))

    return render_template("edit_event.html", event=event)


@app.route("/calendar/delete/<int:event_id>", methods=["POST"])
@require_any_role("admin", "superadmin")
def delete_event(event_id):
    event = FarmEvent.query.get_or_404(event_id)
    current_user = User.query.filter_by(username=session.get("username")).first()

    # Allow only admin/superadmin OR event creator to delete
    if current_user.role not in ["admin", "superadmin"] and event.created_by != current_user.username:
        flash("Access denied!", "danger")
        return redirect(url_for("calendar"))

    db.session.delete(event)
    db.session.commit()
    flash("Event deleted.", "info")
    return redirect(url_for("calendar"))


@app.route("/quickentry", methods=["GET", "POST"])
def quickentry():
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("login"))

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
            return redirect(url_for("quickentry"))

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
            return redirect(url_for("quickentry"))

        elif action == "mark_pregnancy":
            selected_goat_ids = request.form.getlist("pregnant_goat_ids")
            all_ids = [str(g.id) for g in goats]
            for goat in goats:
                # Mark as pregnant if in selected list, else unmark
                goat.is_pregnant = str(goat.id) in selected_goat_ids
            db.session.commit()
            flash("Pregnancy status updated.", "success")
            return redirect(url_for("quickentry"))

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
                        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                        photo.save(save_path)
                        sp = SicknessPhoto(sickness_id=s.id, image_path=save_path)
                        db.session.add(sp)
                db.session.commit()
            flash("Sickness recorded.", "success")
            return redirect(url_for("quickentry"))

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

@app.route("/setup/reset", methods=["POST"])
def reset_db():
    if session.get("role") not in ["admin", "superadmin"]:
        flash("Admin only.", "danger")
        return redirect(url_for("setup"))
    action = request.form.get("action")
    admin_pwd = request.form.get("admin_pwd")
    user = User.query.filter_by(username=session.get("username")).first()
    if not user or not user.check_password(admin_pwd):
        flash("Password incorrect. Database reset aborted!", "danger")
        return redirect(url_for("setup"))
    if action == "reset_all":
        db.session.query(Sickness).delete()
        db.session.query(Removal).delete()
        db.session.query(Goat).delete()
        db.session.commit()
        flash("All data reset!", "warning")
    elif action == "reset_goats":
        db.session.query(Sickness).delete()
        db.session.query(Removal).delete()
        db.session.query(Goat).delete()
        db.session.commit()
        flash("All goats, sickness, and removal logs deleted!", "warning")
    elif action == "reset_sickness":
        db.session.query(Sickness).delete()
        db.session.commit()
        flash("All sickness logs deleted!", "warning")
    elif action == "reset_removals":
        db.session.query(Removal).delete()
        db.session.commit()
        flash("All removal logs deleted!", "warning")
    elif action == "delete_removed_goats":
        removed_goats = Goat.query.filter_by(status="removed").all()
        for goat in removed_goats:
            db.session.delete(goat)
        db.session.commit()
        flash("All goats with status 'removed' deleted!", "info")
    else:
        flash("Unknown reset action.", "danger")
    return redirect(url_for("setup"))

from flask import abort

@app.route("/admin/targets", methods=["GET", "POST"])
@require_any_role("admin", "superadmin")
def target_weight_admin():
    types = GoatType.query.order_by(GoatType.name).all()

    # ADD new
    if request.method == "POST" and "add" in request.form:
        goat_type_id = int(request.form["goat_type_id"])
        sex = request.form.get("sex") or None
        age_months = int(request.form["age_months"])
        min_weight = float(request.form["min_weight"])
        db.session.add(TargetWeight(
            goat_type_id=goat_type_id,
            sex=sex,
            age_months=age_months,
            min_weight=min_weight
        ))
        db.session.commit()
        flash("Target weight added!", "success")
        return redirect(url_for("target_weight_admin"))

    # EDIT existing
    if request.method == "POST" and "edit_id" in request.form:
        tw = TargetWeight.query.get_or_404(int(request.form["edit_id"]))
        tw.goat_type_id = int(request.form["goat_type_id"])
        tw.sex = request.form.get("sex") or None
        tw.age_months = int(request.form["age_months"])
        tw.min_weight = float(request.form["min_weight"])
        db.session.commit()
        flash("Target weight updated!", "success")
        return redirect(url_for("target_weight_admin"))

    # DELETE
    if request.method == "POST" and "delete_id" in request.form:
        tw = TargetWeight.query.get_or_404(int(request.form["delete_id"]))
        db.session.delete(tw)
        db.session.commit()
        flash("Target weight deleted.", "info")
        return redirect(url_for("target_weight_admin"))

    targets = TargetWeight.query.order_by(TargetWeight.goat_type_id, TargetWeight.sex, TargetWeight.age_months).all()
    return render_template("target_weights.html", targets=targets, goat_types=types)

@app.route("/admin/feedback")
@require_any_role("admin", "superadmin")
def admin_feedback():
    feedbacks = GoatFeedback.query.order_by(GoatFeedback.timestamp.desc()).limit(50).all()
    return render_template("admin_feedback.html", feedbacks=feedbacks)

@app.route("/feedback/photo/delete/<int:photo_id>", methods=["POST"])
def delete_feedback_photo(photo_id):
    photo = GoatFeedbackPhoto.query.get_or_404(photo_id)
    feedback = photo.feedback  # assumes you have a relationship GoatFeedbackPhoto.feedback

    user_role = session.get("role")
    is_owner = feedback.submitted_by == session["username"]
    is_admin = user_role in ["admin", "superadmin"]

    # Only the feedback submitter or admin/superadmin can delete
    if not (is_owner or is_admin):
        flash("You are not authorized to delete this photo.", "danger")
        next_url = request.form.get("next") or url_for("goat_detail", tag=feedback.goat.tag)
        return redirect(next_url)

    # Safe to delete the photo
    if photo.image_path and os.path.exists(photo.image_path):
        os.remove(photo.image_path)
    db.session.delete(photo)
    db.session.commit()
    flash("Feedback photo deleted.", "info")
    next_url = request.form.get("next") or url_for("goat_detail", tag=feedback.goat.tag)
    return redirect(next_url)



@app.route("/users", methods=["GET", "POST"])
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
        return redirect(url_for("user_list"))

    return render_template("user_list.html", users=users, all_perms=all_perms, reset_requests=reset_requests)


@app.route("/users/reset/<int:user_id>", methods=["POST"])
@require_any_role("admin", "superadmin")
def reset_user_password(user_id):
    current_user = User.query.filter_by(username=session.get("username")).first()
    target_user = User.query.get_or_404(user_id)

    # Only allow superadmin OR admin resetting a worker
    if current_user.role == "superadmin" or (current_user.role == "admin" and target_user.role == "worker"):
        import secrets
        temp_pw = secrets.token_urlsafe(8)[:10]
        target_user.set_temp_password(temp_pw)
        db.session.commit()
        return jsonify({"success": True, "temp_password": temp_pw})
    
    return jsonify({"success": False, "error": "Not authorized."}), 403


@app.route("/users/toggle/<int:user_id>", methods=["POST"])
@require_any_role("admin", "superadmin")
def toggle_user_status(user_id):
    current_user = User.query.filter_by(username=session.get("username")).first()
    target_user = User.query.get_or_404(user_id)

    # Only allow superadmin OR admin changing a worker's status
    if current_user.role == "superadmin" or (current_user.role == "admin" and target_user.role == "worker"):
        target_user.status = "inactive" if target_user.status == "active" else "active"
        db.session.commit()
        flash("User status changed.", "info")
    else:
        flash("Not authorized to change status.", "danger")

    return redirect(url_for("user_list"))


@app.route("/users/add", methods=["GET", "POST"])
@app.route("/users/edit/<int:user_id>", methods=["GET", "POST"])
@require_any_role("admin", "superadmin")
def manage_user(user_id=None):
    current = User.query.filter_by(username=session.get("username")).first()
    is_edit = user_id is not None
    user = User.query.get(user_id) if is_edit else None

    if current.role == "admin":
        if is_edit and user.role != "worker":
            flash("Admins can only manage workers.", "danger")
            return redirect(url_for("user_list"))

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
                return redirect(url_for("add_user"))
            import secrets
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
        return redirect(url_for("user_list"))

    return render_template("add_user.html", user=user)

@app.route("/profile", methods=["GET", "POST"])
def user_profile():
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("login"))

    user = User.query.filter_by(username=session["username"]).first()

    if request.method == "POST":
        user.full_name = request.form["full_name"]
        user.email = request.form["email"]
        user.phone = request.form["phone"]
        db.session.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("user_profile"))

    return render_template("user_profile.html", current_user=user)

@app.route("/change_password", methods=["POST"])
def change_password():
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("login"))

    user = User.query.filter_by(username=session["username"]).first()
    current_pw = request.form["current_password"]
    new_pw = request.form["new_password"]

    if not user.check_password(current_pw):
        flash("Incorrect current password.", "danger")
        return redirect(url_for("user_profile"))

    user.set_password(new_pw)
    db.session.commit()
    flash("Password changed successfully.", "success")
    return redirect(url_for("user_profile"))

@app.route("/request_password_reset", methods=["POST"])
def request_password_reset():
    username = request.form.get("username", "").strip()

    if not username:
        flash("Please enter your username before requesting a reset.", "warning")
        return redirect(url_for("login"))

    user = User.query.filter_by(username=username).first()
    if not user:
        flash(f"User '{username}' not found.", "danger")
        return redirect(url_for("login"))

    existing = PasswordResetRequest.query.filter_by(user_id=user.id, resolved=False).first()
    if existing:
        flash("You have already requested a reset. Please wait for admin to act.", "info")
    else:
        req = PasswordResetRequest(user_id=user.id)
        db.session.add(req)
        db.session.commit()
        flash("✅ Password reset request submitted. Please contact your admin.", "success")

    return redirect(url_for("login"))


@app.route("/admin/reset/<int:user_id>/<int:request_id>", methods=["POST"])
@require_any_role("admin", "superadmin")
def admin_reset_password(user_id, request_id):
    current = User.query.filter_by(username=session.get("username")).first()
    target = User.query.get_or_404(user_id)
    req = PasswordResetRequest.query.get_or_404(request_id)

    # Restrict admin to only reset workers
    if current.role == "admin" and target.role != "worker":
        flash("Admins can only reset passwords for workers.", "danger")
        return redirect(url_for("user_list"))

    import secrets
    temp_pw = secrets.token_urlsafe(8)[:10]
    target.set_temp_password(temp_pw)
    req.resolved = True
    db.session.commit()
    flash(f"Password for {target.username} reset. Temp password: {temp_pw}", "info")
    return redirect(url_for("user_list"))


@app.route("/vaccine_types", methods=["GET", "POST"])
@require_role("superadmin")
def vaccine_types():
    # Get or create guide (only 1 row)
    guide = VaccineGuide.query.first()
    if not guide:
        guide = VaccineGuide(guide_text="Enter your vaccine/deworming program guide here...")
        db.session.add(guide)
        db.session.commit()

    if request.method == "POST":
        # Guide text update
        if "save_guide" in request.form:
            guide.guide_text = request.form.get("guide_text", "")
            db.session.commit()
            flash("Guide updated!", "success")
        # Vaccine type add
        elif "add_vaccine" in request.form:
            name = request.form["name"]
            # Check for duplicate
            if VaccineType.query.filter_by(name=name).first():
                flash("Vaccine name already exists!", "danger")
                return redirect(url_for("vaccine_types"))
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
        return redirect(url_for("vaccine_types"))

    types = VaccineType.query.order_by(VaccineType.name).all()
    return render_template("vaccine_types.html", types=types, guide=guide)


@app.route("/vaccine_types/edit/<int:vaccine_type_id>", methods=["POST"])
@require_any_role("admin", "superadmin")
def edit_vaccine_type(vaccine_type_id):
    vt = VaccineType.query.get_or_404(vaccine_type_id)
    data = request.get_json()

    # Validate required fields
    if not data or "name" not in data:
        return jsonify({"success": False, "error": "Missing required data."}), 400

    # Prevent duplicate name (case-insensitive match)
    duplicate = VaccineType.query.filter(
        func.lower(VaccineType.name) == data["name"].strip().lower(),
        VaccineType.id != vaccine_type_id
    ).first()
    if duplicate:
        return jsonify({"success": False, "error": "Name already in use."}), 400

    # Update fields safely
    vt.name = data["name"].strip()
    vt.description = data.get("description", "").strip()
    vt.min_age_days = int(data.get("min_age_days", 0))
    vt.booster_schedule_days = data.get("booster_schedule_days", "")
    vt.default_frequency_days = int(data.get("default_frequency_days", 180))

    db.session.commit()
    return jsonify({"success": True})


@app.route("/vaccine_types/delete/<int:vaccine_type_id>", methods=["POST"])
@require_role("superadmin")
def delete_vaccine_type(vaccine_type_id):
    vt = VaccineType.query.get_or_404(vaccine_type_id)
    # Remove only future scheduled, keep history
    VaccinationEvent.query.filter_by(vaccine_type_id=vt.id, status="scheduled").delete()
    db.session.delete(vt)
    db.session.commit()
    flash("Vaccine type deleted. Historical vaccination records remain.", "info")
    return redirect(url_for("vaccine_types"))



@app.route("/goats/<tag>/vaccine/<int:vaccine_type_id>", methods=["GET", "POST"])
def record_vaccine(tag, vaccine_type_id):
    goat = Goat.query.filter_by(tag=tag, status="active").first_or_404()
    vt = VaccineType.query.get_or_404(vaccine_type_id)
    today_str = datetime.now().strftime('%Y-%m-%d')

    if request.method == "POST":
        scheduled_date = request.form.get("scheduled_date", today_str)
        actual_date_given = request.form.get("actual_date_given") or None
        notes = request.form.get("notes", "")
        # 👇 NEW: Accept batch_number and given_by from the form (with fallback to session)
        batch_number = request.form.get("batch_number", "")
        given_by = request.form.get("given_by") or session.get("username")
        
        # If actual_date_given, this is "done"; else, just "scheduled"
        status = "done" if actual_date_given else "scheduled"

        # Find if there's already a scheduled event for this goat/vaccine/date
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
            ve.batch_number = batch_number   # 👈 NEW: Save batch_number
        else:
            ve = VaccinationEvent(
                goat_id=goat.id,
                vaccine_type_id=vt.id,
                scheduled_date=scheduled_date,
                actual_date_given=actual_date_given,
                status=status,
                notes=notes,
                given_by=given_by,
                batch_number=batch_number     # 👈 NEW: Save batch_number
            )
            db.session.add(ve)
        db.session.commit()
        flash(f"{vt.name} vaccination scheduled for {goat.tag}.", "success")
        return redirect(url_for("goat_detail", tag=goat.tag))

    return render_template(
        "record_vaccine.html",
        goat=goat,
        vt=vt,
        today=today_str
    )



@app.route("/vaccines/batch", methods=["GET", "POST"])
def batch_vaccine_entry():
    if not session.get("username"):
        flash("Please login first.", "warning")
        return redirect(url_for("login"))

    all_vaccine_types = VaccineType.query.order_by(VaccineType.name).all()
    all_goats = Goat.query.filter_by(status="active").order_by(Goat.tag).all()
    today_str = datetime.now().strftime('%Y-%m-%d')

    if request.method == "POST":
        vaccine_type_id = int(request.form["vaccine_type_id"])
        actual_date_given = request.form.get("actual_date_given", today_str)
        goat_ids = request.form.getlist("goat_ids")  # This is a list of goat IDs
        notes = request.form.get("notes", "")
        # 👇 NEW: Get these from the form!
        batch_number = request.form.get("batch_number", "")
        given_by = request.form.get("given_by") or session.get("username")
        for goat_id in goat_ids:
            # Prevent duplicate logs
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
                batch_number=batch_number   # 👈 NEW: Save batch_number!
            )
            db.session.add(ve)
        db.session.commit()
        flash(f"Vaccination recorded for {len(goat_ids)} goats.", "success")
        return redirect(url_for("batch_vaccine_entry"))

    return render_template(
        "batch_vaccine_entry.html",
        vaccine_types=all_vaccine_types,
        goats=all_goats,
        today=today_str
    )


@app.route("/reports/vax_overdue")
@require_any_role("admin", "superadmin")
def report_vax_overdue():
    goats = Goat.query.filter_by(status="active").all()
    overdue_list = []
    today = datetime.now().date()
    for goat in goats:
        due_info = get_vaccine_due_info(goat)
        for v in due_info:
            if v["status"] == "overdue":
                overdue_list.append({
                    "goat": goat,
                    "vaccine": v["vaccine"],
                    "due_date": v["next_due"],
                    "days_overdue": (today - v["next_due"]).days,
                    "last_given": v["last_given"],
                })
    # Optional: add sorting by due date, goat, vaccine, etc.
    overdue_list.sort(key=lambda x: (x["due_date"], x["goat"].tag))
    return render_template("report_vax_overdue.html", overdue_list=overdue_list)

@app.route("/reports/vax_overdue/export_csv")
@require_any_role("admin", "superadmin")
def export_vax_overdue_csv():
    goats = Goat.query.filter_by(status="active").all()
    today = datetime.now().date()
    output = []
    for goat in goats:
        due_info = get_vaccine_due_info(goat)
        for v in due_info:
            if v["status"] == "overdue":
                output.append([
                    goat.tag,
                    goat.goat_type.name if goat.goat_type else "",
                    v["vaccine"].name,
                    v["last_given"] or "",
                    v["next_due"].strftime("%Y-%m-%d"),
                    (today - v["next_due"]).days,
                    "Overdue"
                ])
    # Build CSV
    si = []
    writer = csv.writer(si.append)
    writer(["Goat Tag", "Type", "Vaccine", "Last Given", "Next Due", "Days Overdue", "Status"])
    for row in output:
        writer(row)
    return Response('\n'.join(si), mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=overdue_vax_report.csv"})

@app.route("/reports/vax_overdue/export_pdf")
@require_any_role("admin", "superadmin")
def export_vax_overdue_pdf():
    goats = Goat.query.filter_by(status="active").all()
    overdue_list = []
    today = datetime.now().date()
    for goat in goats:
        due_info = get_vaccine_due_info(goat)
        for v in due_info:
            if v["status"] == "overdue":
                overdue_list.append({
                    "goat": goat,
                    "vaccine": v["vaccine"],
                    "due_date": v["next_due"],
                    "days_overdue": (today - v["next_due"]).days,
                    "last_given": v["last_given"],
                })
    overdue_list.sort(key=lambda x: (x["due_date"], x["goat"].tag))
    # Render HTML using a special printable template
    html_out = render_template("report_vax_overdue_pdf.html", overdue_list=overdue_list, today=today)
    # Convert HTML to PDF in memory
    pdf_io = io.BytesIO()
    HTML(string=html_out, base_url=request.base_url).write_pdf(pdf_io)
    pdf_io.seek(0)
    response = make_response(pdf_io.read())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = "attachment; filename=overdue_vax_report.pdf"
    return response

@app.route("/reports/vax_overdue/send_email", methods=["GET", "POST"])
@require_any_role("admin", "superadmin")
def send_vax_overdue_email():
    from flask import request, flash, redirect, url_for
    if request.method == "POST":
        recipient = request.form["email"]
        # ... assemble overdue_list as before ...
        # (reuse your PDF code)
        html_out = render_template("report_vax_overdue_pdf.html", overdue_list=overdue_list, today=today)
        pdf_io = io.BytesIO()
        HTML(string=html_out, base_url=request.base_url).write_pdf(pdf_io)
        pdf_io.seek(0)
        # Send email
        msg = Message(
            subject="Overdue Vaccination Report - Goat Manager",
            sender=app.config['MAIL_USERNAME'],
            recipients=[recipient],
            body="Dear Vet,\n\nPlease find attached the latest Overdue Vaccination Report for the farm.\n\nRegards,\nGoat Manager App"
        )
        msg.attach("overdue_vax_report.pdf", "application/pdf", pdf_io.read())
        mail.send(msg)
        flash("Report sent to {}".format(recipient), "success")
        return redirect(url_for('report_vax_overdue'))
    # Render a simple form to enter recipient email
    return render_template("send_vax_report_email.html")

@app.route("/reports/health")
@require_any_role("admin", "superadmin")
def report_health():
    # Sickness: active and recent history
    sick_logs = Sickness.query.filter_by(status="active").order_by(Sickness.created_at.desc()).all()
    # Death/removal: recent history (last 30/90 days, or all)
    removals = Removal.query.order_by(Removal.date.desc()).all()
    return render_template("report_health.html", sick_logs=sick_logs, removals=removals)

@app.route("/reports/health/export_csv")
@require_any_role("admin", "superadmin")
def export_health_csv():
    from flask import Response
    import csv
    import io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Type", "Goat Tag", "Date", "Sickness/Reason", "Medicine", "Status/Notes", "Photo/Certificate"])
    # Sickness logs
    sick_logs = Sickness.query.filter_by(status="active").order_by(Sickness.created_at.desc()).all()
    for log in sick_logs:
        photo_paths = "; ".join([photo.image_path for photo in log.photos]) if log.photos else "-"
        writer.writerow([
            "Sickness",
            log.goat.tag,
            log.date,
            log.sickness,
            log.medicine,
            log.notes or "-",
            photo_paths
        ])
    # Removals
    removals = Removal.query.order_by(Removal.date.desc()).all()
    for r in removals:
        writer.writerow([
            "Removal",
            r.goat.tag,
            r.date,
            r.reason or "-",
            "-",
            r.notes or "-",
            r.certificate_path or "-"
        ])
    output.seek(0)
    return Response(output, mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=health_report.csv"})


@app.route("/reports/health/export_pdf")
@require_any_role("admin", "superadmin")
def export_health_pdf():
    sick_logs = Sickness.query.filter_by(status="active").order_by(Sickness.created_at.desc()).all()
    removals = Removal.query.order_by(Removal.date.desc()).all()
    today = datetime.now().date()
    html_out = render_template("report_health_pdf.html", sick_logs=sick_logs, removals=removals, today=today)
    # Use pdfkit to generate PDF from HTML
    pdf = pdfkit.from_string(html_out, False)
    response = make_response(pdf)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = "attachment; filename=health_report.pdf"
    return response

@app.route("/reports/health/send_email", methods=["GET", "POST"])
@require_any_role("admin", "superadmin")
def send_health_email():
    from flask import request, flash, redirect, url_for
    if request.method == "POST":
        recipient = request.form["email"]
        sick_logs = Sickness.query.filter_by(status="active").order_by(Sickness.created_at.desc()).all()
        removals = Removal.query.order_by(Removal.date.desc()).all()
        today = datetime.now().date()
        html_out = render_template("report_health_pdf.html", sick_logs=sick_logs, removals=removals, today=today)
        pdf_io = io.BytesIO()
        HTML(string=html_out, base_url=request.base_url).write_pdf(pdf_io)
        pdf_io.seek(0)
        msg = Message(
            subject="Sickness & Mortality Report - Goat Manager",
            sender=app.config['MAIL_USERNAME'],
            recipients=[recipient],
            body="Dear Vet,\n\nPlease find attached the latest Sickness & Mortality Report for the farm.\n\nRegards,\nGoat Manager App"
        )
        msg.attach("health_report.pdf", "application/pdf", pdf_io.read())
        mail.send(msg)
        flash("Health report sent to {}".format(recipient), "success")
        return redirect(url_for('report_health'))
    return render_template("send_health_email.html")

@app.route("/reports/vax_compliance")
@require_any_role("admin", "superadmin")
def report_vax_compliance():
    goats = Goat.query.filter_by(status="active").all()
    vaccine_types = VaccineType.query.all()
    compliance_data = []

    today = datetime.now().date()
    for vt in vaccine_types:
        total = 0
        compliant = 0
        overdue = []
        for goat in goats:
            due_info = get_vaccine_due_info(goat)
            for v in due_info:
                if v["vaccine"].id == vt.id:
                    total += 1
                    if v["status"] != "overdue":
                        compliant += 1
                    else:
                        overdue.append({"goat": goat, "due_date": v["next_due"]})
        percent = int((compliant / total) * 100) if total else 100
        compliance_data.append({
            "vaccine_type": vt,
            "total": total,
            "compliant": compliant,
            "percent": percent,
            "overdue": overdue
        })

    # All recent vaccinations
    vaccinations = VaccinationEvent.query.filter(VaccinationEvent.status == "done").order_by(VaccinationEvent.actual_date_given.desc()).limit(100).all()
    return render_template("report_vax_compliance.html",
                           compliance_data=compliance_data,
                           vaccinations=vaccinations)

@app.route("/reports/goat_register")
@require_any_role("admin", "superadmin")
def report_goat_register():
    goats = Goat.query.all()
    return render_template("report_goat_register.html", goats=goats)

@app.route("/reports/goat_register/export_csv")
@require_any_role("admin", "superadmin")
def export_goat_register_csv():
    from flask import Response
    import csv, io
    goats = Goat.query.all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Tag", "Type", "Sex", "DOB", "Date Acquired", "Acq. Method", "Source",
        "Weight (kg)", "Status", "Num Breedings", "Num Sickness", "Num Vax", "Removed"
    ])
    for goat in goats:
        writer.writerow([
            goat.tag,
            goat.goat_type.name if goat.goat_type else "",
            goat.sex or "",
            goat.dob or "",
            goat.date_acquired or "",
            goat.acquisition_method or "",
            goat.source_name or "",
            goat.weight or "",
            goat.status,
            len(getattr(goat, 'breedings_as_doe', [])) + len(getattr(goat, 'breedings_as_buck', [])),
            len(getattr(goat, 'sickness_history', [])),
            len(getattr(goat, 'vaccination_events', [])),
            "Yes" if goat.status != "active" else "No"
        ])
    output.seek(0)
    return Response(output, mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=goat_register.csv"})


@app.route("/reports/goat_register/export_pdf")
@require_any_role("admin", "superadmin")
def export_goat_register_pdf():
    goats = Goat.query.all()
    today = datetime.now().date()
    html_out = render_template("report_goat_register_pdf.html", goats=goats, today=today)
    pdf = pdfkit.from_string(html_out, False)
    response = make_response(pdf)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = "attachment; filename=goat_register.pdf"
    return response


# --- Initialize database and default config ---
with app.app_context():
    db.create_all()
    #if not User.query.filter_by(username="admin").first():
    #    admin = User(username="admin", role="admin")
    #    admin.set_password("admin123")
    #    db.session.add(admin)
    #if not User.query.filter_by(username="worker").first():
    #    worker = User(username="worker", role="worker")
    #    worker.set_password("worker123")
    #    db.session.add(worker)
    if not User.query.filter_by(username="admin").first():
        admin = User(
            username="admin",
            full_name="Super Admin",
            email="admin@farm.test",
            phone="0123456789",
            role="superadmin",
            status="active",
            created_by="system"
        )
        admin.set_password("super123")
        db.session.add(admin)

    if not User.query.filter_by(username="worker").first():
        worker = User(username="worker", role="worker")
        worker.set_password("worker123")
        db.session.add(worker)
    if not FarmConfig.query.first():
        db.session.add(FarmConfig(
            farm_name="My Goat Farm"
        ))

    db.session.commit()

if __name__ == "__main__":
    print("✅ Flask server starting...")
    app.run(debug=True)
