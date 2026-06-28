import os
import stat
import shutil
from pathlib import Path
from flask import Blueprint, request, redirect, url_for, flash, jsonify, send_file, abort, render_template
from flask_login import login_required, current_user
from models import db, Project

file_manager = Blueprint('file_manager', __name__, url_prefix='/projects/<int:project_id>/filemanager')

def _resolve_safe_path(project, rel_path):
    """Ensure path is within project.deploy_path to prevent directory traversal."""
    base = Path(project.deploy_path).resolve()
    target = (base / rel_path).resolve() if rel_path else base
    try:
        if os.path.commonpath([str(base), str(target)]) != str(base):
            abort(403)
    except ValueError:
        abort(403)
    return base, target

@file_manager.route('/')
@file_manager.route('/dir/<path:rel_path>')
@login_required
def explorer(project_id, rel_path=''):
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id and current_user.role != 'admin':
        abort(403)
        
    if not project.deploy_path or not os.path.isdir(project.deploy_path):
        flash('Deploy path does not exist yet. Push code or create it first.', 'warning')
        return redirect(url_for('main.project_detail', project_id=project_id))
        
    base, target = _resolve_safe_path(project, rel_path)
    
    entries = []
    try:
        for entry in sorted(target.iterdir(), key=lambda e: (e.is_file(), e.name.lower())):
            # Ignore hidden files except .env
            if entry.name.startswith('.') and entry.name != '.env':
                continue
            st = entry.stat()
            # File permission string: e.g. "rw-r--r--"
            perm = stat.filemode(st.st_mode)
            entries.append({
                'name': entry.name,
                'rel_path': str(Path(rel_path) / entry.name) if rel_path else entry.name,
                'is_dir': entry.is_dir(),
                'size': st.st_size if entry.is_file() else None,
                'mtime': st.st_mtime,
                'permissions': perm,
                'octal_permissions': oct(st.st_mode & 0o777)[2:]
            })
    except Exception as e:
        flash(f"Error reading folder: {str(e)}", 'danger')
        
    # Build breadcrumbs
    parts = Path(rel_path).parts if rel_path else []
    breadcrumbs = []
    for i, part in enumerate(parts):
        breadcrumbs.append({
            'name': part,
            'rel_path': '/'.join(parts[:i+1])
        })
        
    return render_template('project_files.html', project=project, rel_path=rel_path, entries=entries, breadcrumbs=breadcrumbs)

@file_manager.route('/view')
@login_required
def view_file(project_id):
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id and current_user.role != 'admin':
        abort(403)
        
    rel_path = request.args.get('path', '').strip()
    base, target = _resolve_safe_path(project, rel_path)
    
    if not target.is_file():
        flash('Not a valid file.', 'danger')
        return redirect(url_for('file_manager.explorer', project_id=project_id))
        
    try:
        content = target.read_text(encoding='utf-8', errors='replace')
        return jsonify({'ok': True, 'content': content, 'filename': target.name})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@file_manager.route('/save', methods=['POST'])
@login_required
def save_file(project_id):
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id and current_user.role != 'admin':
        abort(403)
        
    rel_path = request.json.get('path', '').strip()
    content = request.json.get('content', '')
    base, target = _resolve_safe_path(project, rel_path)
    
    try:
        target.write_text(content, encoding='utf-8')
        return jsonify({'ok': True, 'message': 'File saved successfully!'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@file_manager.route('/upload', methods=['POST'])
@login_required
def upload(project_id):
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id and current_user.role != 'admin':
        abort(403)
        
    rel_path = request.form.get('path', '').strip()
    base, target_dir = _resolve_safe_path(project, rel_path)
    
    if 'file' not in request.files:
        flash('No file selected.', 'danger')
        return redirect(url_for('file_manager.explorer', project_id=project_id, rel_path=rel_path))
        
    f = request.files['file']
    if f.filename == '':
        flash('No selected file.', 'danger')
        return redirect(url_for('file_manager.explorer', project_id=project_id, rel_path=rel_path))
        
    try:
        target_path = target_dir / f.filename
        # Safe prefix check for file creation path
        _resolve_safe_path(project, str(Path(rel_path) / f.filename))
        f.save(str(target_path))
        flash('File uploaded successfully!', 'success')
    except Exception as e:
        flash(f'Upload failed: {str(e)}', 'danger')
        
    return redirect(url_for('file_manager.explorer', project_id=project_id, rel_path=rel_path))

@file_manager.route('/download')
@login_required
def download(project_id):
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id and current_user.role != 'admin':
        abort(403)
        
    rel_path = request.args.get('path', '').strip()
    base, target = _resolve_safe_path(project, rel_path)
    
    if not target.is_file():
        abort(404)
        
    return send_file(str(target), as_attachment=True, download_name=target.name)

@file_manager.route('/create', methods=['POST'])
@login_required
def create_item(project_id):
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id and current_user.role != 'admin':
        abort(403)
        
    rel_path = request.json.get('path', '').strip()
    name = request.json.get('name', '').strip()
    item_type = request.json.get('type', 'file') # file or dir
    
    if not name:
        return jsonify({'ok': False, 'error': 'Name is required'})
        
    base, parent_dir = _resolve_safe_path(project, rel_path)
    target = parent_dir / name
    
    # check directory traversal
    _resolve_safe_path(project, str(Path(rel_path) / name))
    
    try:
        if item_type == 'dir':
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.touch()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@file_manager.route('/delete', methods=['POST'])
@login_required
def delete_item(project_id):
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id and current_user.role != 'admin':
        abort(403)
        
    rel_path = request.json.get('path', '').strip()
    base, target = _resolve_safe_path(project, rel_path)
    
    try:
        if target.is_dir():
            shutil.rmtree(str(target))
        else:
            target.unlink()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@file_manager.route('/rename', methods=['POST'])
@login_required
def rename_item(project_id):
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id and current_user.role != 'admin':
        abort(403)
        
    rel_path = request.json.get('path', '').strip()
    new_name = request.json.get('new_name', '').strip()
    
    if not new_name:
        return jsonify({'ok': False, 'error': 'New name is required'})
        
    base, target = _resolve_safe_path(project, rel_path)
    parent = target.parent
    new_target = parent / new_name
    
    # check directory traversal
    _resolve_safe_path(project, str(Path(rel_path).parent / new_name))
    
    try:
        target.rename(new_target)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@file_manager.route('/permissions', methods=['POST'])
@login_required
def change_permissions(project_id):
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id and current_user.role != 'admin':
        abort(403)
        
    rel_path = request.json.get('path', '').strip()
    octal_str = request.json.get('permissions', '644').strip()
    
    base, target = _resolve_safe_path(project, rel_path)
    
    try:
        mode = int(octal_str, 8)
        os.chmod(str(target), mode)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})
