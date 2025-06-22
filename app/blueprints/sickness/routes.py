from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from app.models import db, Sickness, SicknessPhoto, Goat
from app.utils import require_permission
from datetime import datetime
from werkzeug.utils import secure_filename
import os

sickness_bp = Blueprint('sickness', __name__, url_prefix='/sickness')

@sickness_bp.route('/')
@require_permission('sickness')
def sick_log():
    # Get filter parameters
    goat_tag = request.args.get('goat_tag', '')
    keyword = request.args.get('keyword', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    
    # Base query
    query = Sickness.query
    
    # Apply filters
    if goat_tag:
        goat = Goat.query.filter_by(tag=goat_tag).first()
        if goat:
            query = query.filter_by(goat_id=goat.id)
    
    if keyword:
        query = query.filter(
            (Sickness.sickness.contains(keyword)) |
            (Sickness.medicine.contains(keyword))
        )
    
    if date_from:
        query = query.filter(Sickness.created_at >= date_from)
    
    if date_to:
        query = query.filter(Sickness.created_at <= date_to)
    
    # Get results
    logs = query.order_by(Sickness.created_at.desc()).all()
    goats = Goat.query.filter_by(status="active").order_by(Goat.tag).all()
    
    return render_template('sick_log.html', 
                         logs=logs, 
                         goats=goats,
                         goat_tag=goat_tag,
                         keyword=keyword,
                         date_from=date_from,
                         date_to=date_to)

@sickness_bp.route('/edit/<int:log_id>', methods=['GET', 'POST'])
@require_permission('sickness')
def edit_sick_log(log_id):
    log = Sickness.query.get_or_404(log_id)
    goats = Goat.query.filter_by(status="active").order_by(Goat.tag).all()
    
    if request.method == 'POST':
        log.goat_id = int(request.form['goat_id'])
        log.sickness = request.form['sickness']
        log.medicine = request.form['medicine']
        log.date = request.form['date']
        log.status = request.form.get('status', 'active')
        
        # Handle photo uploads
        if "photos" in request.files:
            photos = request.files.getlist("photos")
            for photo in photos:
                if photo and photo.filename:
                    filename = secure_filename(f"sick_{log.goat_id}_{log.date}_{photo.filename}")
                    save_path = os.path.join("static/uploads", filename)
                    photo.save(save_path)
                    sp = SicknessPhoto(sickness_id=log.id, image_path=save_path)
                    db.session.add(sp)
        
        db.session.commit()
        flash('Sickness log updated successfully.', 'success')
        return redirect(url_for('sickness.sick_log'))
    
    return render_template('edit_sick_log.html', log=log, goats=goats)

@sickness_bp.route('/delete/<int:log_id>', methods=['POST'])
@require_permission('sickness')
def delete_sick_log(log_id):
    log = Sickness.query.get_or_404(log_id)
    
    # Delete associated photos
    for photo in log.photos:
        if os.path.exists(photo.image_path):
            os.remove(photo.image_path)
        db.session.delete(photo)
    
    db.session.delete(log)
    db.session.commit()
    flash('Sickness log deleted.', 'info')
    return redirect(url_for('sickness.sick_log'))

@sickness_bp.route('/batch_delete', methods=['POST'])
@require_permission('sickness')
def batch_delete_sick_log():
    selected_logs = request.form.getlist('selected_logs')
    
    if not selected_logs:
        flash('No logs selected for deletion.', 'warning')
        return redirect(url_for('sickness.sick_log'))
    
    for log_id in selected_logs:
        log = Sickness.query.get(log_id)
        if log:
            # Delete associated photos
            for photo in log.photos:
                if os.path.exists(photo.image_path):
                    os.remove(photo.image_path)
                db.session.delete(photo)
            db.session.delete(log)
    
    db.session.commit()
    flash(f'{len(selected_logs)} sickness logs deleted.', 'info')
    return redirect(url_for('sickness.sick_log'))

@sickness_bp.route('/photo/delete/<int:photo_id>', methods=['POST'])
@require_permission('sickness')
def delete_sickness_photo(photo_id):
    photo = SicknessPhoto.query.get_or_404(photo_id)
    
    # Remove file from disk
    if os.path.exists(photo.image_path):
        os.remove(photo.image_path)
    
    db.session.delete(photo)
    db.session.commit()
    flash("Photo deleted.", "info")
    
    next_url = request.form.get("next")
    return redirect(next_url or url_for("sickness.sick_log"))

@sickness_bp.route('/recover/<int:log_id>', methods=['POST'])
@require_permission('sickness')
def mark_sickness_recovered(log_id):
    log = Sickness.query.get_or_404(log_id)
    log.status = 'recovered'
    db.session.commit()
    flash("Sickness log marked as recovered.", "success")
    return redirect(url_for("goats.goat_detail", tag=log.goat.tag))
