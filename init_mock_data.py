from app import create_app
from app.extensions import db
from app.models import (
    User, Goat, GoatType, Sickness, SicknessPhoto, Removal, 
    BreedingEvent, VaccineType, VaccinationEvent, FarmConfig,
    WeightLog, TargetWeight
)
from datetime import datetime, timedelta
import random

app = create_app()

with app.app_context():
    db.drop_all()
    db.create_all()

    # 1. Create Farm Config
    farm = FarmConfig(farm_name="GoatMaster Farm")
    db.session.add(farm)

    # 2. Create Goat Types (main Malaysian breeds)
    katjang = GoatType(name="Katjang")
    boer = GoatType(name="Boer")
    jamnapari = GoatType(name="Jamnapari")
    saanen = GoatType(name="Saanen")
    db.session.add_all([katjang, boer, jamnapari, saanen])
    db.session.commit()

    # 3. Add General Target Weights (Malaysia, by breed/sex/age)
    target_weight_data = [
        # KATJANG
        (katjang.id, "Male", 1, 3), (katjang.id, "Male", 3, 7), (katjang.id, "Male", 6, 13), (katjang.id, "Male", 9, 18), (katjang.id, "Male", 12, 23), (katjang.id, "Male", 24, 25),
        (katjang.id, "Female", 1, 2.5), (katjang.id, "Female", 3, 6), (katjang.id, "Female", 6, 11), (katjang.id, "Female", 9, 16), (katjang.id, "Female", 12, 18), (katjang.id, "Female", 24, 20),

        # BOER
        (boer.id, "Male", 1, 4), (boer.id, "Male", 3, 12), (boer.id, "Male", 6, 22), (boer.id, "Male", 9, 32), (boer.id, "Male", 12, 40), (boer.id, "Male", 24, 50),
        (boer.id, "Female", 1, 3.5), (boer.id, "Female", 3, 10), (boer.id, "Female", 6, 18), (boer.id, "Female", 9, 25), (boer.id, "Female", 12, 35), (boer.id, "Female", 24, 35),

        # JAMNAPARI
        (jamnapari.id, "Male", 1, 4), (jamnapari.id, "Male", 3, 9), (jamnapari.id, "Male", 6, 16), (jamnapari.id, "Male", 9, 24), (jamnapari.id, "Male", 12, 32), (jamnapari.id, "Male", 24, 40),
        (jamnapari.id, "Female", 1, 3.5), (jamnapari.id, "Female", 3, 8), (jamnapari.id, "Female", 6, 14), (jamnapari.id, "Female", 9, 19), (jamnapari.id, "Female", 12, 26), (jamnapari.id, "Female", 24, 30),

        # SAANEN
        (saanen.id, "Male", 1, 4), (saanen.id, "Male", 3, 10), (saanen.id, "Male", 6, 17), (saanen.id, "Male", 9, 26), (saanen.id, "Male", 12, 34), (saanen.id, "Male", 24, 40),
        (saanen.id, "Female", 1, 3.5), (saanen.id, "Female", 3, 9), (saanen.id, "Female", 6, 16), (saanen.id, "Female", 9, 22), (saanen.id, "Female", 12, 28), (saanen.id, "Female", 24, 35),
    ]

    for gt_id, sex, age, min_weight in target_weight_data:
        db.session.add(TargetWeight(goat_type_id=gt_id, sex=sex, age_months=age, min_weight=min_weight))
    db.session.commit()

    # 4. Create Users
    superadmin = User(username="superadmin", full_name="Super Admin", email="superadmin@goat.com", phone="0111111111", role="superadmin", status="active", created_by="system")
    superadmin.set_password("password")
    admin = User(username="admin", full_name="Admin User", email="admin@goat.com", phone="0222222222", role="admin", status="active", created_by="superadmin")
    admin.set_password("password")
    worker = User(username="worker", full_name="Worker User", email="worker@goat.com", phone="0333333333", role="worker", status="active", created_by="admin")
    worker.set_password("password")
    db.session.add_all([superadmin, admin, worker])
    db.session.commit()

    # 5. Create Vaccine Types
    clostridial = VaccineType(name="Clostridial", description="Clostridial 8-way", min_age_days=60, booster_schedule_days="21,42", default_frequency_days=180)
    ppr = VaccineType(name="PPR", description="Peste des Petits Ruminants", min_age_days=90, booster_schedule_days="", default_frequency_days=365)
    db.session.add_all([clostridial, ppr])
    db.session.commit()

    # 6. Create Goats (mix breeds, male/female, acquired/born)
    goat_types = [katjang, boer, jamnapari, saanen]
    for breed in goat_types:
        for i in range(1, 4):
            goat = Goat(
                tag=f"{breed.name[:2].upper()}-{i:03}",
                goat_type_id=breed.id,
                sex="Male" if i % 2 == 0 else "Female",
                dob=(datetime.now() - timedelta(days=30*i)).strftime('%Y-%m-%d'),
                date_acquired=(datetime.now() - timedelta(days=30*i)).strftime('%Y-%m-%d'),
                acquisition_method="Born" if i % 2 == 1 else "Purchased",
                status="active",
                location="Main Barn" if breed.name in ["Boer", "Katjang"] else "Field",
                weight=10 + i*3 + random.randint(0, 5),
                added_by="admin"
            )
            db.session.add(goat)
    db.session.commit()

    # 7. Add Sample Sickness and Removals
    goat_sample = Goat.query.first()
    s = Sickness(goat_id=goat_sample.id, sickness="Diarrhea", medicine="Electrolyte", created_by="worker")
    db.session.add(s)
    db.session.add(Removal(goat_id=goat_sample.id, reason="Sold", date=(datetime.now()-timedelta(days=5)).strftime("%Y-%m-%d"), notes="Healthy at sale", created_by="admin"))
    db.session.commit()

    # 8. Add Breeding Event
    buck = Goat.query.filter_by(sex="Male").first()
    doe = Goat.query.filter_by(sex="Female").first()
    be = BreedingEvent(
        buck_id=buck.id,
        doe_id=doe.id,
        mating_start_date=(datetime.now()-timedelta(days=25)).strftime("%Y-%m-%d"),
        mating_end_date=(datetime.now()-timedelta(days=22)).strftime("%Y-%m-%d"),
        notes="Planned breeding",
        status="completed",
        created_by="admin"
    )
    db.session.add(be)
    db.session.commit()

    # 9. Add Vaccination Events
    for goat in Goat.query.all():
        for vt in VaccineType.query.all():
            if random.random() > 0.5:
                vax = VaccinationEvent(
                    goat_id=goat.id,
                    vaccine_type_id=vt.id,
                    scheduled_date=(datetime.now()-timedelta(days=14)).strftime('%Y-%m-%d'),
                    actual_date_given=(datetime.now()-timedelta(days=14)).strftime('%Y-%m-%d'),
                    status="done",
                    notes="Annual vaccine",
                    given_by="worker",
                    created_by="worker"
                )
                db.session.add(vax)
    db.session.commit()

    # 10. Add Weight Logs
    for goat in Goat.query.all():
        for w in range(3):
            wl = WeightLog(
                goat_id=goat.id,
                date=(datetime.now()-timedelta(days=7*w)).strftime("%Y-%m-%d"),
                weight=goat.weight + random.randint(-2, 2),
                created_by="worker"
            )
            db.session.add(wl)
    db.session.commit()

    print("✅ Mock database initialized successfully!")
