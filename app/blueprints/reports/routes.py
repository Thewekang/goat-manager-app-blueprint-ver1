from flask import Blueprint, render_template, request, redirect, url_for, session, flash, Response, make_response
from ...models import Goat, Sickness, Removal, VaccineType, VaccinationEvent, GoatFeedback, TargetWeight
from ...extensions import db, mail
from ...utils import require_any_role, get_vaccine_due_info, get_target_weight
from datetime import datetime
import io
import csv
import pdfkit

reports_bp = Blueprint("reports", __name__)

@reports_bp.route("/reports/vax_overdue")
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
    overdue_list.sort(key=lambda x: (x["due_date"], x["goat"].tag))
    return render_template("report_vax_overdue.html", overdue_list=overdue_list)

@reports_bp.route("/reports/vax_overdue/export_csv")
@require_any_role("admin", "superadmin")
def export_vax_overdue_csv():
    goats = Goat.query.filter_by(status="active").all()
    today = datetime.now().date()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Goat Tag", "Type", "Vaccine", "Last Given", "Next Due", "Days Overdue", "Status"])
    for goat in goats:
        due_info = get_vaccine_due_info(goat)
        for v in due_info:
            if v["status"] == "overdue":
                writer.writerow([
                    goat.tag,
                    goat.goat_type.name if goat.goat_type else "",
                    v["vaccine"].name,
                    v["last_given"] or "",
                    v["next_due"].strftime("%Y-%m-%d"),
                    (today - v["next_due"]).days,
                    "Overdue"
                ])
    output.seek(0)
    return Response(output, mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=overdue_vax_report.csv"})

@reports_bp.route("/reports/vax_overdue/export_pdf")
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
    html_out = render_template("report_vax_overdue_pdf.html", overdue_list=overdue_list, today=today)
    pdf = pdfkit.from_string(html_out, False)
    response = make_response(pdf)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = "attachment; filename=overdue_vax_report.pdf"
    return response

@reports_bp.route("/reports/health")
@require_any_role("admin", "superadmin")
def report_health():
    sick_logs = Sickness.query.filter_by(status="active").order_by(Sickness.created_at.desc()).all()
    removals = Removal.query.order_by(Removal.date.desc()).all()
    return render_template("report_health.html", sick_logs=sick_logs, removals=removals)

@reports_bp.route("/reports/health/export_csv")
@require_any_role("admin", "superadmin")
def export_health_csv():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Type", "Goat Tag", "Date", "Sickness/Reason", "Medicine", "Status/Notes", "Photo/Certificate"])
    sick_logs = Sickness.query.filter_by(status="active").order_by(Sickness.created_at.desc()).all()
    for log in sick_logs:
        photo_paths = "; ".join([photo.image_path for photo in log.photos]) if log.photos else "-"
        writer.writerow([
            "Sickness",
            log.goat.tag,
            getattr(log, "date", ""),
            log.sickness,
            log.medicine,
            log.notes if hasattr(log, "notes") else "-",
            photo_paths
        ])
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

@reports_bp.route("/reports/health/export_pdf")
@require_any_role("admin", "superadmin")
def export_health_pdf():
    sick_logs = Sickness.query.filter_by(status="active").order_by(Sickness.created_at.desc()).all()
    removals = Removal.query.order_by(Removal.date.desc()).all()
    today = datetime.now().date()
    html_out = render_template("report_health_pdf.html", sick_logs=sick_logs, removals=removals, today=today)
    pdf = pdfkit.from_string(html_out, False)
    response = make_response(pdf)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = "attachment; filename=health_report.pdf"
    return response

@reports_bp.route("/reports/vax_compliance")
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
    vaccinations = VaccinationEvent.query.filter(VaccinationEvent.status == "done").order_by(VaccinationEvent.actual_date_given.desc()).limit(100).all()
    return render_template("report_vax_compliance.html",
                           compliance_data=compliance_data,
                           vaccinations=vaccinations)

@reports_bp.route("/reports/goat_register")
@require_any_role("admin", "superadmin")
def report_goat_register():
    goats = Goat.query.all()
    return render_template("report_goat_register.html", goats=goats)

@reports_bp.route("/reports/goat_register/export_csv")
@require_any_role("admin", "superadmin")
def export_goat_register_csv():
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
            len(getattr(goat, 'sicknesses', [])),
            len(getattr(goat, 'vaccination_events', [])),
            "Yes" if goat.status != "active" else "No"
        ])
    output.seek(0)
    return Response(output, mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=goat_register.csv"})

@reports_bp.route("/reports/goat_register/export_pdf")
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

@reports_bp.route("/reports/vax_overdue/send_email", methods=["GET", "POST"])
@require_any_role("admin", "superadmin")
def send_vax_overdue_email():
    """Send vaccination overdue report via email"""
    if request.method == "POST":
        recipient = request.form.get("recipient")
        if not recipient:
            flash("Recipient email is required.", "danger")
            return redirect(url_for("reports.report_vax_overdue"))
        
        try:
            from flask_mail import Message
            
            # Generate report data
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
            
            # Create email
            msg = Message(
                subject="Vaccination Overdue Report",
                recipients=[recipient],
                html=render_template("email_vax_overdue.html", overdue_list=overdue_list, today=today)
            )
            
            mail.send(msg)
            flash(f"Vaccination overdue report sent to {recipient}", "success")
        except Exception as e:
            flash(f"Failed to send email: {str(e)}", "danger")
        
        return redirect(url_for("reports.report_vax_overdue"))
    
    return render_template("send_email_form.html", 
                         report_type="Vaccination Overdue",
                         action_url=url_for("reports.send_vax_overdue_email"))

@reports_bp.route("/reports/health/send_email", methods=["GET", "POST"])
@require_any_role("admin", "superadmin")
def send_health_email():
    """Send health report via email"""
    if request.method == "POST":
        recipient = request.form.get("recipient")
        if not recipient:
            flash("Recipient email is required.", "danger")
            return redirect(url_for("reports.report_health"))
        
        try:
            from flask_mail import Message
            
            # Generate report data
            sick_logs = Sickness.query.filter_by(status="active").order_by(Sickness.created_at.desc()).all()
            removals = Removal.query.order_by(Removal.date.desc()).all()
            
            # Create email
            msg = Message(
                subject="Health Report",
                recipients=[recipient],
                html=render_template("email_health.html", sick_logs=sick_logs, removals=removals, today=datetime.now().date())
            )
            
            mail.send(msg)
            flash(f"Health report sent to {recipient}", "success")
        except Exception as e:
            flash(f"Failed to send email: {str(e)}", "danger")
        
        return redirect(url_for("reports.report_health"))
    
    return render_template("send_email_form.html", 
                         report_type="Health",
                         action_url=url_for("reports.send_health_email"))
