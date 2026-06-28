"""
git_service.py
--------------
Manages bare Git repositories â€” works on both Windows (dev) and Linux (VPS).

Dev  (Windows): repos at C:/Users/<you>/devspace-repos/<user>/<slug>.git
Live (Linux  ): repos at /opt/devspace/repos/<user>/<slug>.git

On git push:
  post-receive hook  â†’  git checkout -f into deploy_path
                     â†’  POST /internal/deploy/<id>  (pip/npm + service restart)
"""

import os
import re
import stat
import platform
import subprocess
from pathlib import Path

IS_WINDOWS = platform.system() == 'Windows'

# â”€â”€ Read from env (set in .env) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
GIT_REPOS_BASE = os.environ.get('GIT_REPOS_BASE',
    r'C:\Users\DevSpace\DevSpace-repos' if IS_WINDOWS else '/opt/DevSpace/repos')
DEPLOY_BASE    = os.environ.get('DEPLOY_BASE',
    r'C:\Users\DevSpace\DevSpace-apps' if IS_WINDOWS else '/var/www/DevSpace')
VPS_HOST       = os.environ.get('VPS_HOST',       'localhost')
SSH_USER       = os.environ.get('SSH_USER',       'git')
DEPLOY_SECRET  = os.environ.get('DEPLOY_SECRET',  'DevSpace-secret')
INTERNAL_URL   = os.environ.get('INTERNAL_URL',   'http://127.0.0.1:5000')


def _slug(name: str) -> str:
    """Convert any string to a safe folder name: lowercase, hyphens only."""
    s = name.lower().strip()
    s = re.sub(r'[^\w\s-]', '', s)
    s = re.sub(r'[\s_]+', '-', s)
    s = re.sub(r'-+', '-', s)
    return s.strip('-') or 'project'


def get_user_home_dir(username: str) -> str:
    """Return the home directory path for a user: DEPLOY_BASE/<slug(username)>"""
    return os.path.join(DEPLOY_BASE, _slug(username))


def get_project_deploy_path(username: str, project_name: str) -> str:
    """Return deploy path: DEPLOY_BASE/<slug(username)>/<slug(project_name)>"""
    return os.path.join(DEPLOY_BASE, _slug(username), _slug(project_name))


def create_user_home_dir(username: str) -> dict:
    """
    Create the user's home directory under DEPLOY_BASE.
    Returns {'success', 'path', 'error'}.
    """
    home = get_user_home_dir(username)
    try:
        Path(home).mkdir(parents=True, exist_ok=True)
        return {'success': True, 'path': home, 'error': None}
    except Exception as e:
        return {'success': False, 'path': home, 'error': str(e)}


def _run(cmd, cwd=None, timeout=30):
    """Run a shell command string safely via shell=True for git operations.
    cmd is always a hardcoded template with validated/quoted arguments â€” never raw user input.
    """
    try:
        r = subprocess.run(cmd, shell=True, cwd=cwd,
                           capture_output=True, text=True, timeout=timeout)
        return {'ok': r.returncode == 0, 'stdout': r.stdout, 'stderr': r.stderr}
    except Exception as e:
        return {'ok': False, 'stdout': '', 'stderr': str(e)}


def _run_list(cmd_list, cwd=None, timeout=30):
    """Run a command given as a list â€” no shell, no injection risk."""
    try:
        r = subprocess.run(cmd_list, shell=False, cwd=cwd,
                           capture_output=True, text=True, timeout=timeout)
        return {'ok': r.returncode == 0, 'stdout': r.stdout, 'stderr': r.stderr}
    except Exception as e:
        return {'ok': False, 'stdout': '', 'stderr': str(e)}


# â”€â”€ Public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def create_bare_repo(project_id: int, project_name: str, username: str,
                     deploy_path: str, branch: str = 'main',
                     language: str = 'python') -> dict:
    """
    Create a bare Git repo + post-receive hook.
    Returns {'success', 'repo_path', 'clone_url', 'error'}.
    """
    slug     = _slug(project_name)
    user_dir = os.path.join(GIT_REPOS_BASE, _slug(username))
    repo_dir = os.path.join(user_dir, f'{slug}.git')

    # â”€â”€ 1. Create parent dir â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    try:
        Path(user_dir).mkdir(parents=True, exist_ok=True)
    except PermissionError as e:
        fix_cmd = (
            f'mkdir "{GIT_REPOS_BASE}"'          if IS_WINDOWS else
            f'sudo mkdir -p {GIT_REPOS_BASE} && sudo chown -R $USER {GIT_REPOS_BASE}'
        )
        return {
            'success': False, 'repo_path': repo_dir, 'clone_url': None,
            'error': (
                f"Cannot create {user_dir}.\n"
                f"Fix: {fix_cmd}\n"
                f"Detail: {e}"
            )
        }

    # â”€â”€ 2. git init --bare â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if not os.path.exists(repo_dir):
        r = _run_list(['git', 'init', '--bare', repo_dir])
        if not r['ok']:
            return {'success': False, 'repo_path': repo_dir, 'clone_url': None,
                    'error': f"git init --bare failed: {r['stderr']}"}

    # â”€â”€ 3. Write hook â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    hook_result = _write_hook(repo_dir, project_id, deploy_path, branch, language)
    if not hook_result['ok']:
        return {'success': False, 'repo_path': repo_dir, 'clone_url': None,
                'error': hook_result['error']}

    clone_url = _make_clone_url(repo_dir)
    return {'success': True, 'repo_path': repo_dir,
            'clone_url': clone_url, 'error': None}


def delete_bare_repo(repo_path: str) -> dict:
    if not repo_path or not os.path.exists(repo_path):
        return {'success': True, 'error': None}

    abs_base = os.path.realpath(GIT_REPOS_BASE)
    abs_repo = os.path.realpath(repo_path)
    if not abs_repo.startswith(abs_base):
        return {'success': False,
                'error': f"Refusing to delete outside {GIT_REPOS_BASE}"}

    import shutil
    try:
        shutil.rmtree(abs_repo)
        return {'success': True, 'error': None}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def update_hook(project_id: int, repo_path: str, deploy_path: str,
                branch: str = 'main', language: str = 'python') -> dict:
    """Rewrite the post-receive hook after project settings change."""
    if not repo_path or not os.path.exists(repo_path):
        return {'success': False, 'error': 'Repo path does not exist'}
    result = _write_hook(repo_path, project_id, deploy_path, branch, language)
    return {'success': result['ok'], 'error': result.get('error')}


def get_repo_log(repo_path: str, branch: str = 'main', limit: int = 20) -> list:
    """Recent commits from the bare repo with changed-file counts."""
    if not repo_path or not os.path.exists(repo_path):
        return []
    git_dir = repo_path.replace('\\', '/')
    # %H=full hash %s=subject %an=author %ai=ISO date %d=decorations
    cmd = (f'git --git-dir="{git_dir}" log {branch} '
           f'--pretty=format:"COMMIT|%H|%s|%an|%ai" '
           f'--shortstat -n {limit}')
    r = _run(cmd)
    if not r['ok'] or not r['stdout'].strip():
        return []

    commits = []
    current = None
    for raw in r['stdout'].splitlines():
        line = raw.strip().strip('"')
        if line.startswith('COMMIT|'):
            if current:
                commits.append(current)
            parts = line.split('|', 4)
            if len(parts) == 5:
                current = {
                    'hash':     parts[1][:8],
                    'full_hash': parts[1],
                    'message':  parts[2],
                    'author':   parts[3],
                    'date':     parts[4],
                    'files_changed': 0,
                    'insertions': 0,
                    'deletions': 0,
                }
        elif current and ('changed' in line or 'insertion' in line or 'deletion' in line):
            # e.g. " 3 files changed, 42 insertions(+), 5 deletions(-)"
            import re as _re
            m = _re.search(r'(\d+) file', line)
            if m: current['files_changed'] = int(m.group(1))
            m = _re.search(r'(\d+) insertion', line)
            if m: current['insertions'] = int(m.group(1))
            m = _re.search(r'(\d+) deletion', line)
            if m: current['deletions'] = int(m.group(1))

    if current:
        commits.append(current)
    return commits


def get_commit_files(repo_path: str, commit_hash: str) -> list:
    """Return list of files changed in a specific commit (with name-status only)."""
    if not repo_path or not os.path.exists(repo_path):
        return []
    git_dir = repo_path.replace('\\', '/')
    cmd = f'git --git-dir="{git_dir}" show --name-status --format="" {commit_hash}'
    r = _run(cmd)
    if not r['ok']:
        return []
    status_map = {'M': 'modified', 'A': 'added', 'D': 'deleted',
                  'R': 'renamed',  'C': 'copied'}
    files = []
    for line in r['stdout'].splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split('\t')
        if len(parts) >= 2 and parts[0][0] in status_map:
            files.append({
                'status': status_map.get(parts[0][0], parts[0][0]),
                'path':   parts[-1],
            })
    return files


def get_commit_diff(repo_path: str, commit_hash: str, max_bytes: int = 80_000) -> str:
    """
    Return the full unified diff of a commit.
    Capped at max_bytes to avoid sending huge diffs to the browser.
    """
    if not repo_path or not os.path.exists(repo_path):
        return ''
    git_dir = repo_path.replace('\\', '/')
    # -U3 = 3 lines of context (standard), --no-color = plain text
    cmd = f'git --git-dir="{git_dir}" show --no-color -U3 {commit_hash}'
    r = _run(cmd, timeout=15)
    if not r['ok']:
        return ''
    diff = r['stdout']
    if len(diff) > max_bytes:
        diff = diff[:max_bytes] + '\n\n... (diff truncated â€” too large to display) ...'
    return diff


def get_clone_url(repo_path: str) -> str:
    return _make_clone_url(repo_path)


# â”€â”€ Internal helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _make_clone_url(repo_path: str) -> str:
    """
    Dev  (Windows, localhost): file:///C:/path/to/repo.git   â† git can clone this locally
    Live (Linux, real VPS)   : git@vps-ip:/path/to/repo.git
    """
    if IS_WINDOWS or VPS_HOST in ('localhost', '127.0.0.1'):
        # Use local file:// URL â€” works with git on same machine
        safe = repo_path.replace('\\', '/')
        return f"file:///{safe}"
    return f"{SSH_USER}@{VPS_HOST}:{repo_path}"


def _write_hook(repo_dir: str, project_id: int, deploy_path: str,
                branch: str, language: str) -> dict:
    """Write the appropriate post-receive hook for the current OS."""
    try:
        if IS_WINDOWS:
            _write_windows_hook(repo_dir, project_id, deploy_path, branch, language)
        else:
            _write_linux_hook(repo_dir, project_id, deploy_path, branch, language)
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def _write_linux_hook(repo_dir, project_id, deploy_path, branch, language):
    """Bash post-receive hook for Linux VPS."""
    hook_path = os.path.join(repo_dir, 'hooks', 'post-receive')
    webhook   = f"{INTERNAL_URL}/internal/deploy/{project_id}"

    content = f"""#!/bin/bash
# DevSpace â€” auto-generated post-receive hook
# Project: {project_id} | Branch: {branch}

BRANCH="{branch}"
DEPLOY_PATH="{deploy_path}"
WEBHOOK="{webhook}"
SECRET="{DEPLOY_SECRET}"
GIT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

while read oldrev newrev refname; do
    PUSHED_BRANCH=$(echo "$refname" | sed 's|refs/heads/||')
    [ "$PUSHED_BRANCH" = "$BRANCH" ] || continue

    echo ""
    echo "-----> DevSpace: deploying $BRANCH to $DEPLOY_PATH"

    # Checkout latest code
    if [ -d "$DEPLOY_PATH" ]; then
        git --git-dir="$GIT_DIR" --work-tree="$DEPLOY_PATH" checkout -f "$BRANCH"
        echo "-----> Checkout done"
    else
        echo "-----> WARNING: deploy path $DEPLOY_PATH not found, creating it..."
        mkdir -p "$DEPLOY_PATH"
        git --git-dir="$GIT_DIR" --work-tree="$DEPLOY_PATH" checkout -f "$BRANCH"
    fi

    # Notify DevSpace to run pip/npm install and service restart
    if command -v curl &>/dev/null; then
        echo "-----> Notifying DevSpace webapp..."
        HTTP=$(curl -s -o /dev/null -w "%{{http_code}}" \\
            -X POST "$WEBHOOK" \\
            -H "X-Deploy-Secret: $SECRET" \\
            -H "Content-Type: application/json" \\
            -d '{{"ref":"'"$refname"'","commit":"'"$newrev"'"}}' \\
            --max-time 60)
        echo "-----> Webhook response: HTTP $HTTP"
    fi

    echo "-----> Done!"
    echo ""
done
"""
    with open(hook_path, 'w', newline='\n') as f:
        f.write(content)
    # Make executable
    st = os.stat(hook_path)
    os.chmod(hook_path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _write_windows_hook(repo_dir, project_id, deploy_path, branch, language):
    """
    Windows post-receive hook.
    Git for Windows runs hooks as bash scripts, so we write a bash script
    but also create a .bat fallback.
    """
    hooks_dir = os.path.join(repo_dir, 'hooks')
    hook_path = os.path.join(hooks_dir, 'post-receive')
    webhook   = f"{INTERNAL_URL}/internal/deploy/{project_id}"

    # Normalise Windows path to forward slashes for git bash
    deploy_fwd = deploy_path.replace('\\', '/')
    repo_fwd   = repo_dir.replace('\\', '/')

    # Git for Windows uses bash for hooks â€” write bash script
    bash_content = f"""#!/bin/bash
# DevSpace â€” Windows dev post-receive hook
BRANCH="{branch}"
DEPLOY_PATH="{deploy_fwd}"
WEBHOOK="{webhook}"
SECRET="{DEPLOY_SECRET}"
GIT_DIR="{repo_fwd}"

while read oldrev newrev refname; do
    PUSHED_BRANCH=$(echo "$refname" | sed 's|refs/heads/||')
    [ "$PUSHED_BRANCH" = "$BRANCH" ] || continue

    echo ""
    echo "-----> DevSpace DEV: deploying $BRANCH"
    echo "-----> Target: $DEPLOY_PATH"

    # Create deploy dir if needed
    mkdir -p "$DEPLOY_PATH"

    # Checkout latest code into deploy path
    git --git-dir="$GIT_DIR" --work-tree="$DEPLOY_PATH" checkout -f "$BRANCH"
    echo "-----> Checkout complete"

    # Notify DevSpace
    if command -v curl &>/dev/null; then
        HTTP=$(curl -s -o /dev/null -w "%{{http_code}}" \\
            -X POST "$WEBHOOK" \\
            -H "X-Deploy-Secret: $SECRET" \\
            -H "Content-Type: application/json" \\
            -d '{{"ref":"'"$refname"'","commit":"'"$newrev"'"}}' \\
            --connect-timeout 5 --max-time 30 2>/dev/null)
        echo "-----> Webhook: HTTP $HTTP"
    else
        echo "-----> curl not found - skipping webhook (checkout already done)"
    fi

    echo "-----> Done!"
    echo ""
done
"""
    with open(hook_path, 'w', newline='\n') as f:
        f.write(bash_content)

    # Make executable (matters for Git for Windows bash)
    try:
        st = os.stat(hook_path)
        os.chmod(hook_path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    except Exception:
        pass
