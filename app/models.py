from .extensions import db
from datetime import datetime, timedelta

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    full_name = db.Column(db.String(100))
    email = db.Column(db.String(100))
    phone = db.Column(db.String(30))
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # superadmin, admin, worker
    permissions = db.Column(db.String(500), default="")
    must_change_password = db.Column(db.Boolean, default=False)
    created_by = db.Column(db.String(50))
    status = db.Column(db.String(10), default="active")
    last_login = db.Column(db.DateTime)

    def set_password(self, raw_password):
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(raw_password)
        self.must_change_password = False

    def set_temp_password(self, raw_password):
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(raw_password)
        self.must_change_password = True

    def check_password(self, password):
        from werkzeug.security import check_password_hash
        return check_password_hash(self.password_hash, password)

    def has_permission(self, perm):
        if self.role == "superadmin":
            return True
        perms = self.permissions.split(",") if self.permissions else []
        return perm in perms

class PasswordResetRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=db.func.now())
    resolved = db.Column(db.Boolean, default=False)
    user = db.relationship("User", backref="reset_requests")

class Goat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tag = db.Column(db.String(50), unique=True, nullable=False)
    goat_type_id = db.Column(db.Integer, db.ForeignKey('goat_type.id'), nullable=False)
    goat_type = db.relationship('GoatType')
    sex = db.Column(db.String(10))
    is_pregnant = db.Column(db.Boolean, default=False)
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
        from .utils import get_target_weight
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
    status = db.Column(db.String(20), default='active')
    medicine = db.Column(db.String(100))
    created_by = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=db.func.now())
    image_path = db.Column(db.String(200))
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
    created_at = db.Column(db.DateTime, default=db.func.now())
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
    created_at = db.Column(db.DateTime, default=db.func.now())
    buck = db.relationship('Goat', foreign_keys=[buck_id], backref='breedings_as_buck')
    doe = db.relationship('Goat', foreign_keys=[doe_id], backref='breedings_as_doe')

class FarmEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    event_date = db.Column(db.String(20), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    notes = db.Column(db.String(200))
    created_by = db.Column(db.String(50))
    recurrence = db.Column(db.String(20), nullable=True)

class VaccineType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True)
    description = db.Column(db.String(200))
    min_age_days = db.Column(db.Integer, default=0)
    booster_schedule_days = db.Column(db.String(200))
    default_frequency_days = db.Column(db.Integer, default=180)

class VaccinationEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    goat_id = db.Column(db.Integer, db.ForeignKey('goat.id'))
    vaccine_type_id = db.Column(db.Integer, db.ForeignKey('vaccine_type.id'))
    scheduled_date = db.Column(db.String(20))
    actual_date_given = db.Column(db.String(20))
    status = db.Column(db.String(20))
    notes = db.Column(db.Text)
    batch_number = db.Column(db.String(50))
    given_by = db.Column(db.String(50))
    created_by = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=db.func.now())
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
    created_at = db.Column(db.DateTime, default=db.func.now())
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
    timestamp = db.Column(db.DateTime, default=db.func.now())
    image_path = db.Column(db.String(200)) 
    updated_at = db.Column(db.DateTime)
    goat = db.relationship('Goat', backref=db.backref('feedbacks', lazy=True))

class GoatFeedbackPhoto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    feedback_id = db.Column(db.Integer, db.ForeignKey('goat_feedback.id'))
    image_path = db.Column(db.String(200))
    feedback = db.relationship('GoatFeedback', backref=db.backref('photos', lazy=True))
