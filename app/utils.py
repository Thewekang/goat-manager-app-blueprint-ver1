from flask import session, redirect, url_for, flash, request
from functools import wraps
from .models import User, Goat, BreedingEvent, VaccineType, VaccinationEvent, TargetWeight
from datetime import datetime, timedelta

# --- Permission Decorator ---
def require_permission(permission):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not session.get("username"):
                flash("Please login first.", "warning")
                return redirect(url_for("auth.login"))
            user = User.query.filter_by(username=session.get("username")).first()
            if not (user and user.has_permission(permission)):
                flash(f"You do not have permission for this action ({permission}).", "danger")
                return redirect(url_for("dashboard.dashboard_home"))
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
                return redirect(url_for("auth.login"))
            user = User.query.filter_by(username=session["username"]).first()
            if not user or user.role != role_required:
                flash(f"Access denied: {role_required} only.", "danger")
                return redirect(url_for("dashboard.dashboard_home"))
            return func(*args, **kwargs)
        return wrapper
    return decorator

def require_any_role(*roles):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not session.get("username"):
                flash("Please login first.", "warning")
                return redirect(url_for("auth.login"))
            user = User.query.filter_by(username=session["username"]).first()
            if not user or user.role not in roles:
                flash("Access denied: insufficient privileges.", "danger")
                return redirect(url_for("dashboard.dashboard_home"))
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
    events = []
    dt = datetime.strptime(event.event_date, "%Y-%m-%d").date()
    start = from_date
    end = to_date
    current = dt

    if not event.recurrence:
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
        if event.recurrence == "daily":
            current += timedelta(days=1)
        elif event.recurrence == "weekly":
            current += timedelta(weeks=1)
        elif event.recurrence == "monthly":
            month = current.month + 1
            year = current.year
            if month > 12:
                month = 1
                year += 1
            try:
                current = current.replace(year=year, month=month)
            except ValueError:
                from calendar import monthrange
                last_day = monthrange(year, month)[1]
                current = current.replace(year=year, month=month, day=last_day)
        else:
            break
    return events

def get_vaccine_due_info(goat):
    result = []
    today = datetime.now().date()
    for vt in VaccineType.query.all():
        dob = datetime.strptime(goat.dob, "%Y-%m-%d").date() if goat.dob else None
        if not dob or (today - dob).days < vt.min_age_days:
            continue
        scheduled_event = (
            VaccinationEvent.query
            .filter_by(goat_id=goat.id, vaccine_type_id=vt.id, status="scheduled")
            .order_by(VaccinationEvent.scheduled_date.asc())
            .first()
        )
        if scheduled_event:
            next_due = datetime.strptime(scheduled_event.scheduled_date, "%Y-%m-%d").date()
            last_given = None
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
            continue
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
