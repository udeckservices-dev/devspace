import re
import os
import stat
from pathlib import Path
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort, Response
from flask_login import login_required, current_user
from models import db, Project, Deployment

main = Blueprint('main', __name__)


# â”€â”€ Dashboard â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@main.route('/')
@login_required
def dashboard():
    if current_user.role == 'admin':
        return redirect(url_for('admin.dashboard'))

    projects = Project.query.filter_by(user_id=current_user.id).all()

    recent_deployments = []
    for project in projects:
        latest = Deployment.query.filter_by(project_id=project.id)\
                                 .order_by(Deployment.created_at.desc()).first()
        if latest:
            recent_deployments.append(latest)
    recent_deployments = sorted(recent_deployments,
                                key=lambda x: x.created_at, reverse=True)[:5]

    return render_template('dashboard.html',
                           projects=projects,
                           project_count=len(projects),
                           recent_deployments=recent_deployments)


# â”€â”€ Projects list â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@main.route('/projects')
@login_required
def projects():
    projects = Project.query.filter_by(user_id=current_user.id)\
                            .order_by(Project.created_at.desc()).all()
    return render_template('projects.html', projects=projects)


# â”€â”€ Add project â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@main.route('/projects/add', methods=['GET', 'POST'])
@login_required
def add_project():
    from services.git_service import (create_bare_repo, VPS_HOST, SSH_USER,
                                      get_project_deploy_path, DEPLOY_BASE)

    if current_user.role != 'admin' and not current_user.can_create_project():
        flash(f'Project limit reached for {current_user.plan.upper()} plan. '
              f'Upgrade to create more.', 'warning')
        return redirect(url_for('main.projects'))

    if request.method == 'POST':
        name        = request.form.get('name', '').strip()
        branch      = request.form.get('branch', 'main').strip() or 'main'
        language    = request.form.get('language', 'python')
        repo_url    = request.form.get('repo_url', '').strip() or None

        if not name:
            flash('Project name is required.', 'danger')
            return render_template('add_project.html',
                                   vps_host=VPS_HOST, ssh_user=SSH_USER,
                                   deploy_base=DEPLOY_BASE)

        # Auto-generate deploy path from owner username + project name
        deploy_path = get_project_deploy_path(current_user.name, name)

        # Create bare repo on this VPS
        result = create_bare_repo(
            project_id=0,           # placeholder â€” updated after insert
            project_name=name,
            username=current_user.name,
            deploy_path=deploy_path,
            branch=branch,
            language=language
        )

        project = Project(
            user_id=current_user.id,
            name=name,
            repo_url=repo_url,
            git_repo_path=result['repo_path'] if result['success'] else None,
            branch=branch,
            language=language,
            deploy_path=deploy_path
        )
        db.session.add(project)
        db.session.commit()

        # Re-write hook now that we have a real project ID
        if result['success']:
            from services.git_service import update_hook
            from markupsafe import escape as _esc
            update_hook(project.id, result['repo_path'],
                        deploy_path, branch, language)
            flash(f'Project created! Git remote: {_esc(result["clone_url"])}', 'success')
        else:
            from markupsafe import escape as _esc
            flash(f'Project saved, but bare repo setup failed: {_esc(str(result["error"]))}',
                  'warning')

        return redirect(url_for('main.project_detail', project_id=project.id))

    return render_template('add_project.html',
                           vps_host=VPS_HOST, ssh_user=SSH_USER,
                           deploy_base=DEPLOY_BASE)


# â”€â”€ Project detail (new: shows git remote + commit log) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@main.route('/projects/<int:project_id>')
@login_required
def project_detail(project_id):
    from services.git_service import get_repo_log, get_clone_url, VPS_HOST, SSH_USER

    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id and current_user.role != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('main.projects'))

    commits    = get_repo_log(project.git_repo_path, project.branch)
    clone_url  = (get_clone_url(project.git_repo_path)
                  if project.git_repo_path else None)
    last_deploy = Deployment.query.filter_by(project_id=project.id)\
                                  .order_by(Deployment.created_at.desc()).first()

    # App running status (Linux systemd)
    app_status = _get_app_status(project)

    return render_template('project_detail.html',
                           project=project,
                           commits=commits,
                           clone_url=clone_url,
                           last_deploy=last_deploy,
                           app_status=app_status,
                           vps_host=VPS_HOST,
                           ssh_user=SSH_USER)


# â”€â”€ Edit project â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@main.route('/projects/edit/<int:project_id>', methods=['GET', 'POST'])
@login_required
def edit_project(project_id):
    from services.git_service import update_hook, get_clone_url, VPS_HOST, SSH_USER

    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id and current_user.role != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('main.projects'))

    if request.method == 'POST':
        project.name         = request.form.get('name', '').strip()
        project.repo_url     = request.form.get('repo_url', '').strip() or None
        project.branch       = request.form.get('branch', 'main').strip() or 'main'
        project.language     = request.form.get('language', 'python')
        project.deploy_path  = request.form.get('deploy_path', '').strip()
        port_val             = request.form.get('port', '').strip()
        project.port         = int(port_val) if port_val.isdigit() else None
        svc                  = request.form.get('service_name', '').strip()
        import re as _re
        project.service_name = (svc if svc and _re.match(r'^[a-zA-Z0-9._-]+(?:\.service)?$', svc) else None)

        if not all([project.name, project.deploy_path]):
            flash('Name and deploy path are required.', 'danger')
            return render_template('edit_project.html', project=project,
                                   vps_host=VPS_HOST, ssh_user=SSH_USER)

        db.session.commit()

        # Refresh post-receive hook with updated settings
        if project.git_repo_path:
            update_hook(project.id, project.git_repo_path,
                        project.deploy_path, project.branch, project.language)

        flash('Project updated successfully.', 'success')
        return redirect(url_for('main.project_detail', project_id=project.id))

    clone_url = (get_clone_url(project.git_repo_path)
                 if project.git_repo_path else None)
    return render_template('edit_project.html', project=project,
                           clone_url=clone_url,
                           vps_host=VPS_HOST, ssh_user=SSH_USER)


# â”€â”€ Delete project â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@main.route('/projects/delete/<int:project_id>', methods=['POST'])
@login_required
def delete_project(project_id):
    from services.git_service import delete_bare_repo

    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id and current_user.role != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('main.projects'))

    # Remove bare repo from disk
    if project.git_repo_path:
        delete_bare_repo(project.git_repo_path)

    db.session.delete(project)
    db.session.commit()

    flash('Project deleted successfully.', 'success')
    return redirect(url_for('main.projects'))


# â”€â”€ Manual deploy (button click) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@main.route('/projects/deploy/<int:project_id>', methods=['POST'])
@login_required
def deploy_project(project_id):
    from services.deployment import deploy_project as do_deploy

    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id and current_user.role != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('main.projects'))

    from flask import current_app
    result = do_deploy(project, flask_app=current_app._get_current_object())

    if result['status'] == 'success':
        flash('Deployment completed successfully!', 'success')
    else:
        flash(f'Deployment failed: {result.get("error", "See logs for details")}',
              'danger')

    return redirect(url_for('main.deployment_logs', project_id=project.id))


# â”€â”€ Deployment logs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@main.route('/projects/<int:project_id>/logs')
@login_required
def deployment_logs(project_id):
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id and current_user.role != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('main.projects'))

    deployments = Deployment.query.filter_by(project_id=project_id)\
                                  .order_by(Deployment.created_at.desc()).all()
    return render_template('deployment_logs.html',
                           project=project,
                           deployments=deployments)


# â”€â”€ Deployed files browser â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _safe_deploy_path(project, rel_path=''):
    """Resolve a path inside project.deploy_path, prevent directory traversal."""
    base = Path(project.deploy_path).resolve()
    target = (base / rel_path).resolve() if rel_path else base
    # Use os.path.commonpath for safe prefix check (handles Windows case)
    try:
        if os.path.commonpath([str(base), str(target)]) != str(base):
            abort(403)
    except ValueError:
        abort(403)
    return base, target


SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', '.tox'}
TEXT_EXTS = {
    '.py', '.js', '.ts', '.jsx', '.tsx', '.html', '.htm', '.css', '.scss',
    '.json', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf', '.env',
    '.md', '.txt', '.sh', '.bash', '.zsh', '.bat', '.ps1', '.rb', '.php',
    '.go', '.java', '.rs', '.c', '.cpp', '.h', '.cs', '.xml', '.svg',
    '.gitignore', '.gitattributes', '.dockerignore', 'Dockerfile',
    'Makefile', 'requirements.txt', 'package.json', 'package-lock.json',
}
MAX_FILE_PREVIEW = 100 * 1024   # 100 KB


def _is_text(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTS or path.name in TEXT_EXTS


def _dir_tree(base: Path, rel='') -> list:
    """Return a flat list of {name, rel_path, type, size, mtime} for one directory level."""
    target = (base / rel) if rel else base
    entries = []
    try:
        for entry in sorted(target.iterdir(), key=lambda e: (e.is_file(), e.name.lower())):
            if entry.name.startswith('.') and entry.name not in {'.env', '.gitignore'}:
                continue
            if entry.is_dir() and entry.name in SKIP_DIRS:
                continue
            rel_entry = str(Path(rel) / entry.name) if rel else entry.name
            st = entry.stat()
            entries.append({
                'name':     entry.name,
                'rel_path': rel_entry,
                'type':     'dir' if entry.is_dir() else 'file',
                'size':     st.st_size if entry.is_file() else None,
                'mtime':    st.st_mtime,
                'is_text':  _is_text(entry) if entry.is_file() else False,
            })
    except PermissionError:
        pass
    return entries


@main.route('/projects/<int:project_id>/files')
@main.route('/projects/<int:project_id>/files/<path:rel_path>')
@login_required
def project_files(project_id, rel_path=''):
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id and current_user.role != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('main.projects'))

    if not project.deploy_path or not os.path.isdir(project.deploy_path):
        flash('Deploy path does not exist yet â€” push your code first.', 'warning')
        return redirect(url_for('main.project_detail', project_id=project_id))

    base, target = _safe_deploy_path(project, rel_path)

    if target.is_file():
        # â”€â”€ File viewer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if not _is_text(target) or target.stat().st_size > MAX_FILE_PREVIEW:
            flash('Binary or large file â€” cannot preview.', 'warning')
            parent = Path(rel_path).parent if rel_path else Path('.')
            parent_rel = '' if str(parent) in ('.', '') else str(parent)
            return redirect(url_for('main.project_files',
                                    project_id=project_id, rel_path=parent_rel))

        content = target.read_text(encoding='utf-8', errors='replace')
        # build breadcrumbs
        parts = Path(rel_path).parts
        breadcrumbs = []
        for i, part in enumerate(parts):
            breadcrumbs.append({
                'name':     part,
                'rel_path': str(Path(*parts[:i+1])),
            })
        return render_template('project_files.html',
                               project=project,
                               rel_path=rel_path,
                               breadcrumbs=breadcrumbs,
                               entries=None,
                               file_content=content,
                               file_name=target.name,
                               file_ext=target.suffix.lower().lstrip('.') or 'text')

    # â”€â”€ Directory listing â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    entries = _dir_tree(base, rel_path)
    parts = Path(rel_path).parts if rel_path else []
    breadcrumbs = []
    for i, part in enumerate(parts):
        breadcrumbs.append({
            'name':     part,
            'rel_path': str(Path(*parts[:i+1])),
        })
    return render_template('project_files.html',
                           project=project,
                           rel_path=rel_path,
                           breadcrumbs=breadcrumbs,
                           entries=entries,
                           file_content=None,
                           file_name=None,
                           file_ext=None)


def _get_app_status(project) -> str:
    """Return 'running' / 'stopped' / 'unknown' for a project."""
    import platform
    if platform.system() == 'Windows':
        return 'dev'   # local dev â€” no systemd
    if not project.service_name:
        return 'unknown'
    import subprocess
    try:
        r = subprocess.run(
            ['systemctl', 'is-active', project.service_name],
            capture_output=True, text=True, timeout=5)
        state = r.stdout.strip()
        return 'running' if state == 'active' else 'stopped'
    except Exception:
        return 'unknown'


def _control_service(service_name: str, action: str) -> dict:
    """Start / stop / restart a systemd service. action = start|stop|restart"""
    import subprocess, re as _re
    if not service_name:
        return {'ok': False, 'error': 'No service name configured for this project.'}
    # Strict validation â€” only safe service name characters allowed
    if not _re.match(r'^[a-zA-Z0-9._-]+(?:\.service)?$', service_name.strip()):
        return {'ok': False, 'error': 'Invalid service name.'}
    svc = service_name.strip()
    try:
        r = subprocess.run(
            ['sudo', 'systemctl', action, svc],
            shell=False, capture_output=True, text=True, timeout=30)
        return {'ok': r.returncode == 0,
                'error': r.stderr.strip() if r.returncode != 0 else None}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


# â”€â”€ Commit changed-files API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@main.route('/projects/<int:project_id>/commit/<commit_hash>/files')
@login_required
def commit_files(project_id, commit_hash):
    import re as _re
    if not _re.match(r'^[a-f0-9]{7,40}$', commit_hash):
        return jsonify({'error': 'invalid commit hash'}), 400
    from services.git_service import get_commit_files
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id and current_user.role != 'admin':
        return jsonify({'error': 'access denied'}), 403
    files = get_commit_files(project.git_repo_path, commit_hash)
    return jsonify({'files': files})


@main.route('/projects/<int:project_id>/commit/<commit_hash>/diff')
@login_required
def commit_diff(project_id, commit_hash):
    import re as _re
    if not _re.match(r'^[a-f0-9]{7,40}$', commit_hash):
        return jsonify({'error': 'invalid commit hash'}), 400
    from services.git_service import get_commit_diff
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id and current_user.role != 'admin':
        return jsonify({'error': 'access denied'}), 403
    diff = get_commit_diff(project.git_repo_path, commit_hash)
    return jsonify({'diff': diff, 'hash': commit_hash[:8]})


# â”€â”€ App controls: start / stop / restart â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@main.route('/projects/<int:project_id>/control/<action>', methods=['POST'])
@login_required
def app_control(project_id, action):
    if action not in ('start', 'stop', 'restart'):
        return jsonify({'ok': False, 'error': 'Invalid action'}), 400

    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id and current_user.role != 'admin':
        return jsonify({'ok': False, 'error': 'Access denied'}), 403

    import platform
    from flask import current_app
    if platform.system() == 'Windows':
        return jsonify({'ok': True, 'status': 'dev',
                        'message': 'Service control not available in dev mode.'})

    result = _control_service(project.service_name, action)
    status = _get_app_status(project)

    # Email notification
    try:
        from services.mail_service import notify_app_control
        notify_app_control(
            current_app._get_current_object(), project, action,
            success=result['ok'], actor_email=current_user.email
        )
    except Exception:
        pass

    return jsonify({'ok': result['ok'], 'status': status,
                    'error': result.get('error')})


# â”€â”€ App status API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@main.route('/projects/<int:project_id>/status')
@login_required
def app_status_api(project_id):
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id and current_user.role != 'admin':
        return jsonify({'error': 'access denied'}), 403
    return jsonify({'status': _get_app_status(project)})


@main.route('/projects/<int:project_id>/files-api')
@login_required
def project_files_api(project_id):
    """JSON API â€” top-level entries for the quick preview widget."""
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id and current_user.role != 'admin':
        return jsonify({'error': 'access denied'}), 403

    if not project.deploy_path or not os.path.isdir(project.deploy_path):
        return jsonify({'entries': []})

    base = Path(project.deploy_path).resolve()
    entries = _dir_tree(base, '')
    # make entries JSON-serialisable (remove Path objects, round mtime)
    for e in entries:
        e['mtime'] = int(e['mtime'])
    return jsonify({'entries': entries})


# â”€â”€ Run App page â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@main.route('/projects/<int:project_id>/run', methods=['GET', 'POST'])
@login_required
def run_app(project_id):
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id and current_user.role != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('main.projects'))

    if request.method == 'POST':
        import re as _re
        # startup_file / entry_point: only safe filename chars
        sf = request.form.get('startup_file', '').strip()
        project.startup_file = sf if sf and _re.match(r'^[\w./-]{1,100}$', sf) else None
        ep = request.form.get('entry_point', '').strip()
        project.entry_point  = ep if ep and _re.match(r'^[\w.:/-]{1,100}$', ep) else None
        # python_version: only digits and dots
        pv = request.form.get('python_version', '').strip()
        project.python_version = pv if pv and _re.match(r'^\d+(\.\d+)*$', pv) else None
        port_val = request.form.get('port', '').strip()
        project.port = int(port_val) if port_val.isdigit() else None
        svc = request.form.get('service_name', '').strip()
        project.service_name = (svc if svc and _re.match(r'^[a-zA-Z0-9._-]+(?:\.service)?$', svc) else None)
        db.session.commit()
        flash('App configuration saved.', 'success')
        return redirect(url_for('main.run_app', project_id=project_id))

    app_status = _get_app_status(project)

    # Detect requirements/package files in deploy_path
    config_files = []
    if project.deploy_path and os.path.isdir(project.deploy_path):
        for fname in ['requirements.txt', 'package.json', 'Pipfile',
                      'pyproject.toml', 'composer.json']:
            if os.path.exists(os.path.join(project.deploy_path, fname)):
                config_files.append(fname)

    return render_template('run_app.html',
                           project=project,
                           app_status=app_status,
                           config_files=config_files)


@main.route('/projects/<int:project_id>/pip-install', methods=['POST'])
@login_required
def run_pip_install(project_id):
    """Run pip install -r requirements.txt inside deploy_path."""
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id and current_user.role != 'admin':
        return jsonify({'ok': False, 'error': 'Access denied'}), 403

    import subprocess, platform
    deploy = project.deploy_path
    req    = os.path.join(deploy, 'requirements.txt') if deploy else None

    if not deploy or not os.path.isdir(deploy):
        return jsonify({'ok': False, 'output': 'Deploy path does not exist.'})
    if not req or not os.path.exists(req):
        return jsonify({'ok': False, 'output': 'requirements.txt not found in deploy path.'})

    # Find pip â€” venv first, then system
    if platform.system() == 'Windows':
        pip = os.path.join(deploy, 'venv', 'Scripts', 'pip.exe')
        if not os.path.exists(pip):
            pip = 'pip'
    else:
        pip = os.path.join(deploy, 'venv', 'bin', 'pip')
        if not os.path.exists(pip):
            pip = os.path.join(deploy, '.venv', 'bin', 'pip')
        if not os.path.exists(pip):
            pip = 'pip3'

    try:
        r = subprocess.run(
            [pip, 'install', '-r', 'requirements.txt'],
            cwd=deploy, capture_output=True, text=True, timeout=120)
        output = (r.stdout + r.stderr).strip()
        return jsonify({'ok': r.returncode == 0, 'output': output or 'Done.'})
    except Exception as e:
        return jsonify({'ok': False, 'output': str(e)})


@main.route('/projects/<int:project_id>/npm-install', methods=['POST'])
@login_required
def run_npm_install(project_id):
    """Run npm install inside deploy_path."""
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id and current_user.role != 'admin':
        return jsonify({'ok': False, 'error': 'Access denied'}), 403

    import subprocess
    deploy = project.deploy_path
    if not deploy or not os.path.isdir(deploy):
        return jsonify({'ok': False, 'output': 'Deploy path does not exist.'})

    try:
        r = subprocess.run(
            ['npm', 'install', '--production'],
            cwd=deploy, capture_output=True, text=True, timeout=180)
        output = (r.stdout + r.stderr).strip()
        return jsonify({'ok': r.returncode == 0, 'output': output or 'Done.'})
    except Exception as e:
        return jsonify({'ok': False, 'output': str(e)})


# â”€â”€ Deploy path scanner â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@main.route('/api/scan-path')
@login_required
def scan_path():
    """
    GET /api/scan-path?path=/some/dir
    Scans a directory â€” restricted to paths the current user owns.
    Admins may scan any path under DEPLOY_BASE.
    """
    import platform
    from services.git_service import DEPLOY_BASE
    raw_path = request.args.get('path', '').strip()
    if not raw_path:
        return jsonify({'ok': False, 'error': 'No path provided'})

    # Normalise separators for the current OS
    p = Path(raw_path.replace('\\', os.sep).replace('/', os.sep)).resolve()

    # â”€â”€ Ownership check â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Admins can scan anywhere under DEPLOY_BASE
    # Regular users can only scan their own home_dir subtree or project paths
    base_resolved = Path(DEPLOY_BASE).resolve()
    if current_user.role == 'admin':
        # Admin: must stay inside DEPLOY_BASE
        try:
            p.relative_to(base_resolved)
        except ValueError:
            return jsonify({'ok': False,
                            'error': 'Scan restricted to the deploy base directory.'})
    else:
        # Regular user: must be inside their own home_dir
        user_home = Path(current_user.home_dir).resolve() if current_user.home_dir else None
        allowed = False
        if user_home:
            try:
                p.relative_to(user_home)
                allowed = True
            except ValueError:
                pass
        if not allowed:
            return jsonify({'ok': False,
                            'error': 'You can only scan your own project directories.'})

    if not p.exists():
        return jsonify({'ok': True, 'exists': False, 'is_dir': False, 'entries': [],
                        'detected': {}, 'language_hint': None,
                        'message': 'Path does not exist â€” it will be created on first deploy.'})

    if not p.is_dir():
        return jsonify({'ok': False, 'error': 'Path exists but is not a directory.'})

    # List top-level entries (skip hidden + heavy dirs)
    SKIP = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', '.tox',
            'dist', 'build', '.next', '.nuxt'}
    entries = []
    try:
        for entry in sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name.lower())):
            if entry.name in SKIP:
                continue
            entries.append({
                'name': entry.name,
                'type': 'dir' if entry.is_dir() else 'file',
                'size': entry.stat().st_size if entry.is_file() else None,
            })
    except PermissionError as exc:
        return jsonify({'ok': False, 'error': f'Permission denied: {exc}'})

    # Detect known config files
    KNOWN = ['requirements.txt', 'package.json', 'Pipfile', 'pyproject.toml',
             'composer.json', 'Gemfile', 'go.mod', '.env', 'Dockerfile',
             'docker-compose.yml', 'manage.py', 'app.py', 'wsgi.py',
             'server.js', 'index.js', 'index.php']
    detected = {}
    for fname in KNOWN:
        fp = p / fname
        if fp.exists():
            detected[fname] = True

    # Guess language
    hint = None
    if any(k in detected for k in ('requirements.txt', 'Pipfile', 'pyproject.toml',
                                   'manage.py', 'app.py', 'wsgi.py')):
        hint = 'python'
    elif any(k in detected for k in ('package.json', 'server.js', 'index.js')):
        hint = 'node'
    elif 'composer.json' in detected or 'index.php' in detected:
        hint = 'php'

    return jsonify({
        'ok': True,
        'exists': True,
        'is_dir': True,
        'path': str(p),
        'platform': platform.system(),
        'entries': entries[:60],          # cap at 60
        'entry_count': len(entries),
        'detected': detected,
        'language_hint': hint,
    })


# â”€â”€ Internal webhook (called by post-receive hook on git push) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@main.route('/internal/deploy/<int:project_id>', methods=['POST'])
def internal_deploy_webhook(project_id):
    """
    Called by the bare-repo post-receive hook after a git push.
    Runs pip/npm install and restarts the service.
    No browser login required â€” protected by X-Deploy-Secret header.
    """
    from services.deployment import deploy_project as do_deploy

    secret = os.environ.get('DEPLOY_SECRET', 'devspace-secret')
    provided = request.headers.get('X-Deploy-Secret', '')
    if provided != secret:
        return jsonify({'error': 'unauthorized'}), 401

    project = Project.query.get(project_id)
    if not project:
        return jsonify({'error': 'project not found'}), 404

    from flask import current_app
    result = do_deploy(project, flask_app=current_app._get_current_object())
    return jsonify({
        'status': result['status'],
        'project': project.name
    }), 200


@main.route('/projects/<int:project_id>/zip-deploy', methods=['POST'])
@login_required
def zip_deploy(project_id):
    import zipfile
    import shutil
    from werkzeug.utils import secure_filename
    
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id and current_user.role != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('main.projects'))
        
    if 'zip_file' not in request.files:
        flash('No file part in the request.', 'danger')
        return redirect(url_for('main.project_detail', project_id=project.id))
        
    file = request.files['zip_file']
    if file.filename == '':
        flash('No file selected.', 'danger')
        return redirect(url_for('main.project_detail', project_id=project.id))
        
    if file and file.filename.lower().endswith('.zip'):
        # Create a temporary secure file path in OS temp directory to avoid Flask watchdog reloads
        import tempfile
        temp_dir = tempfile.gettempdir()
        
        filename = secure_filename(file.filename)
        temp_zip_path = os.path.join(temp_dir, filename)
        file.save(temp_zip_path)
        
        deploy_dir = project.deploy_path
        os.makedirs(deploy_dir, exist_ok=True)
        deploy_dir_path = Path(deploy_dir).resolve()
        
        extracted_files = []
        errors = []
        
        try:
            # Secure Extraction to avoid Zip Slip
            with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                for member in zip_ref.infolist():
                    target_path = Path(os.path.join(deploy_dir, member.filename)).resolve()
                    
                    # Security check: Ensure it is inside the deployment directory
                    try:
                        if os.path.commonpath([str(deploy_dir_path), str(target_path)]) != str(deploy_dir_path):
                            errors.append(f"Blocked path traversal attempt in zip: {member.filename}")
                            continue
                    except ValueError:
                        errors.append(f"Invalid path inside zip: {member.filename}")
                        continue
                        
                    if member.is_dir():
                        os.makedirs(target_path, exist_ok=True)
                    else:
                        os.makedirs(target_path.parent, exist_ok=True)
                        with zip_ref.open(member) as source, open(target_path, 'wb') as target:
                            shutil.copyfileobj(source, target)
                        extracted_files.append(member.filename)
                        
            # Clean up temp zip
            if os.path.exists(temp_zip_path):
                os.remove(temp_zip_path)
                
            # Log the deployment activity in the database
            from datetime import datetime
            log_lines = [
                f"[{datetime.now()}] -- ZIP Upload Deploy Activated --",
                f"  Project: {project.name}",
                f"  Language: {project.language}",
                f"  Deploy Path: {project.deploy_path}",
                f"  Files Extracted: {len(extracted_files)}"
            ]
            if errors:
                log_lines.append(f"\nWarnings/Errors:\n" + "\n".join(errors))
            log_lines.append("\nExtracted Files List:")
            for f in extracted_files[:100]:
                log_lines.append(f"  - {f}")
            if len(extracted_files) > 100:
                log_lines.append(f"  ... and {len(extracted_files) - 100} more files.")
                
            deployment = Deployment(
                project_id=project.id,
                status='success' if not errors else 'failed',
                logs="\n".join(log_lines),
                commit_message="ZIP Archive Upload Deploy",
                commit_date=datetime.utcnow(),
                finished_at=datetime.utcnow()
            )
            project.last_deployed = datetime.utcnow()
            db.session.add(deployment)
            db.session.commit()
            
            if errors:
                flash(f"ZIP extracted with some security exclusions: {errors[0]}", "warning")
            else:
                flash("ZIP archive uploaded and extracted successfully! Ready for runtime setup.", "success")
                
            return redirect(url_for('main.run_app', project_id=project.id))
            
        except Exception as e:
            # Clean up temp file
            if os.path.exists(temp_zip_path):
                os.remove(temp_zip_path)
            flash(f"ZIP Extraction failed: {str(e)}", "danger")
            return redirect(url_for('main.project_detail', project_id=project.id))
    else:
        flash("Invalid file format. Only .zip archives are supported.", "danger")
        return redirect(url_for('main.project_detail', project_id=project.id))


@main.route('/projects/zip-deploy-center', methods=['GET', 'POST'])
@login_required
def zip_deploy_center():
    import zipfile
    import shutil
    from werkzeug.utils import secure_filename
    from datetime import datetime
    
    if current_user.role == 'admin':
        projects = Project.query.order_by(Project.created_at.desc()).all()
    else:
        projects = Project.query.filter_by(user_id=current_user.id).order_by(Project.created_at.desc()).all()
        
    if request.method == 'POST':
        project_id = request.form.get('project_id')
        if not project_id:
            flash('Please select a target project.', 'danger')
            return redirect(url_for('main.zip_deploy_center'))
            
        project = Project.query.get_or_404(project_id)
        if project.user_id != current_user.id and current_user.role != 'admin':
            flash('Access denied.', 'danger')
            return redirect(url_for('main.zip_deploy_center'))
            
        if 'zip_file' not in request.files:
            flash('No ZIP file found in the request.', 'danger')
            return redirect(url_for('main.zip_deploy_center'))
            
        file = request.files['zip_file']
        if file.filename == '':
            flash('No file selected.', 'danger')
            return redirect(url_for('main.zip_deploy_center'))
            
        if file and file.filename.lower().endswith('.zip'):
            # Create a temporary secure file path in OS temp directory to avoid Flask watchdog reloads
            import tempfile
            temp_dir = tempfile.gettempdir()
            
            filename = secure_filename(file.filename)
            temp_zip_path = os.path.join(temp_dir, filename)
            file.save(temp_zip_path)
            
            deploy_dir = project.deploy_path
            os.makedirs(deploy_dir, exist_ok=True)
            deploy_dir_path = Path(deploy_dir).resolve()
            
            extracted_files = []
            errors = []
            
            try:
                with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                    for member in zip_ref.infolist():
                        target_path = Path(os.path.join(deploy_dir, member.filename)).resolve()
                        
                        try:
                            if os.path.commonpath([str(deploy_dir_path), str(target_path)]) != str(deploy_dir_path):
                                errors.append(f"Blocked path traversal attempt in zip: {member.filename}")
                                continue
                        except ValueError:
                            errors.append(f"Invalid path inside zip: {member.filename}")
                            continue
                            
                        if member.is_dir():
                            os.makedirs(target_path, exist_ok=True)
                        else:
                            os.makedirs(target_path.parent, exist_ok=True)
                            with zip_ref.open(member) as source, open(target_path, 'wb') as target:
                                shutil.copyfileobj(source, target)
                            extracted_files.append(member.filename)
                            
                if os.path.exists(temp_zip_path):
                    os.remove(temp_zip_path)
                    
                log_lines = [
                    f"[{datetime.now()}] -- ZIP Upload Deploy Activated --",
                    f"  Project: {project.name}",
                    f"  Language: {project.language}",
                    f"  Deploy Path: {project.deploy_path}",
                    f"  Files Extracted: {len(extracted_files)}"
                ]
                if errors:
                    log_lines.append(f"\nWarnings/Errors:\n" + "\n".join(errors))
                log_lines.append("\nExtracted Files List:")
                for f in extracted_files[:100]:
                    log_lines.append(f"  - {f}")
                if len(extracted_files) > 100:
                    log_lines.append(f"  ... and {len(extracted_files) - 100} more files.")
                    
                deployment = Deployment(
                    project_id=project.id,
                    status='success' if not errors else 'failed',
                    logs="\n".join(log_lines),
                    commit_message="ZIP Archive Upload Deploy",
                    commit_date=datetime.utcnow(),
                    finished_at=datetime.utcnow()
                )
                project.last_deployed = datetime.utcnow()
                db.session.add(deployment)
                db.session.commit()
                
                if errors:
                    flash(f"ZIP extracted with some security exclusions: {errors[0]}", "warning")
                else:
                    flash(f"ZIP archive for '{project.name}' uploaded and extracted successfully!", "success")
                    
                return redirect(url_for('main.run_app', project_id=project.id))
                
            except Exception as e:
                if os.path.exists(temp_zip_path):
                    os.remove(temp_zip_path)
                flash(f"ZIP Extraction failed: {str(e)}", "danger")
                return redirect(url_for('main.zip_deploy_center'))
        else:
            flash("Invalid file format. Only .zip archives are supported.", "danger")
            return redirect(url_for('main.zip_deploy_center'))
            
    # Fetch recent zip deployments for audit lists
    project_ids = [p.id for p in projects]
    recent_zip_deploys = []
    if project_ids:
        recent_zip_deploys = Deployment.query.filter(
            Deployment.project_id.in_(project_ids),
            Deployment.commit_message == "ZIP Archive Upload Deploy"
        ).order_by(Deployment.created_at.desc()).limit(15).all()
        
    return render_template('admin/zip_deploy_center.html',
                           projects=projects,
                           recent_zip_deploys=recent_zip_deploys)
