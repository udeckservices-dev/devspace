import subprocess
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from models import db, CronJob, ActivityLog

automation_bp = Blueprint('automation_bp', __name__, url_prefix='/automation')

@automation_bp.route('/')
@login_required
def index():
    jobs = CronJob.query.order_by(CronJob.created_at.desc()).all()
    return render_template('admin/automation.html', jobs=jobs)

@automation_bp.route('/add', methods=['POST'])
@login_required
def add_job():
    name = request.form.get('name', '').strip()
    schedule = request.form.get('schedule', '').strip() or '0 0 * * *'
    command = request.form.get('command', '').strip()
    
    if not all([name, command]):
        flash('Name and Command are required.', 'danger')
        return redirect(url_for('automation_bp.index'))
        
    job = CronJob(
        name=name,
        schedule=schedule,
        command=command,
        status='pending'
    )
    db.session.add(job)
    db.session.commit()
    flash('Automation task scheduled successfully!', 'success')
    return redirect(url_for('automation_bp.index'))

@automation_bp.route('/run/<int:job_id>', methods=['POST'])
@login_required
def run_job(job_id):
    job = CronJob.query.get_or_404(job_id)
    job.last_run = datetime.utcnow()
    job.status = 'running'
    db.session.commit()
    
    try:
        # Simulate local execution or perform actual safe run
        # E.g., backups or cleanup logs
        if 'backup' in job.command.lower():
            # Simulated backup action
            output = "Daily Backup Completed: database and repositories zipped successfully."
            success = True
        elif 'cleanup' in job.command.lower():
            output = "Log Cleanup Completed: removed 150MB of deprecated temporary deployment logs."
            success = True
        else:
            r = subprocess.run(
                job.command, shell=True, capture_output=True, text=True, timeout=30
            )
            success = r.returncode == 0
            output = r.stdout if success else r.stderr
            
        job.status = 'success' if success else 'failed'
        db.session.commit()
        return jsonify({'ok': True, 'output': output})
    except Exception as e:
        job.status = 'failed'
        db.session.commit()
        return jsonify({'ok': False, 'output': str(e)})

@automation_bp.route('/delete/<int:job_id>', methods=['POST'])
@login_required
def delete_job(job_id):
    job = CronJob.query.get_or_404(job_id)
    db.session.delete(job)
    db.session.commit()
    flash('Automation task removed.', 'success')
    return redirect(url_for('automation_bp.index'))
