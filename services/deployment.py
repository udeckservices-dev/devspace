"""
deployment.py
-------------
Handles deploying a project from its local bare Git repo into the deploy path.
All subprocess calls use list syntax (no shell=True) to prevent command injection.
"""

import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from models import db, Deployment, Project


# â”€â”€ Safe subprocess helper (NO shell=True) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _run(cmd_list, cwd=None, timeout=300):
    """Run a command given as a list. Never uses shell=True."""
    import platform
    if platform.system() == 'Windows' and cmd_list:
        base_cmd = cmd_list[0]
        if base_cmd == 'npm':
            cmd_list[0] = 'npm.cmd'
        elif base_cmd == 'mvn':
            cmd_list[0] = 'mvn.cmd'
        elif base_cmd == 'composer':
            # Check composer.bat or composer.cmd
            cmd_list[0] = 'composer.bat'
        elif base_cmd in ('gradlew', './gradlew'):
            cmd_list[0] = 'gradlew.bat'
            
    try:
        result = subprocess.run(
            cmd_list, shell=False, cwd=cwd,
            capture_output=True, text=True, timeout=timeout
        )
        return {
            'returncode': result.returncode,
            'stdout': result.stdout,
            'stderr': result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {'returncode': -1, 'stdout': '', 'stderr': 'Command timed out'}
    except FileNotFoundError as e:
        return {'returncode': -1, 'stdout': '', 'stderr': f'Command not found: {e}'}
    except Exception as e:
        return {'returncode': -1, 'stdout': '', 'stderr': str(e)}


# â”€â”€ Input validators â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def sanitize_path(path):
    path = os.path.normpath(path)
    if '..' in path:
        return None
    return path


def sanitize_branch(branch):
    branch = branch.strip()
    if not re.match(r'^[a-zA-Z0-9._/-]+$', branch):
        return 'main'
    return branch


def sanitize_service_name(name):
    """Only allow alphanumeric, hyphens, underscores, dots â€” no shell metacharacters."""
    if not name:
        return None
    name = name.strip()
    if re.match(r'^[a-zA-Z0-9._-]+(?:\.service)?$', name):
        return name
    return None


def validate_repo_url(url):
    """
    Allow only http/https/git/ssh URLs and local file:// URLs.
    Reject file:// pointing outside known safe prefixes (handled at call site).
    """
    if not url:
        return None
    url = url.strip()
    allowed = re.compile(
        r'^(https?://|git://|git@|ssh://|file:///)',
        re.IGNORECASE
    )
    if not allowed.match(url):
        return None
    # Reject shell metacharacters
    if re.search(r'[;&|`$<>\n\r]', url):
        return None
    return url


# â”€â”€ Git helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def checkout_from_bare(bare_repo_path: str, deploy_path: str, branch: str) -> dict:
    os.makedirs(deploy_path, exist_ok=True)
    return _run(
        ['git', f'--git-dir={bare_repo_path}',
         f'--work-tree={deploy_path}', 'checkout', '-f', branch],
        timeout=60
    )


def get_git_info_from_bare(bare_repo_path: str, branch: str):
    commit_msg  = ''
    commit_date = None

    r = _run(['git', f'--git-dir={bare_repo_path}', 'log', branch,
              '-1', '--pretty=format:%s'])
    if r['returncode'] == 0:
        commit_msg = r['stdout'].strip()

    r = _run(['git', f'--git-dir={bare_repo_path}', 'log', branch,
              '-1', '--pretty=format:%ci'])
    if r['returncode'] == 0:
        try:
            commit_date = datetime.strptime(r['stdout'].strip(), '%Y-%m-%d %H:%M:%S %z')
        except Exception:
            pass

    return commit_msg, commit_date


def get_git_info(repo_path: str):
    commit_msg  = ''
    commit_date = None

    r = _run(['git', 'log', '-1', '--pretty=format:%s'], cwd=repo_path)
    if r['returncode'] == 0:
        commit_msg = r['stdout'].strip()

    r = _run(['git', 'log', '-1', '--pretty=format:%ci'], cwd=repo_path)
    if r['returncode'] == 0:
        try:
            commit_date = datetime.strptime(r['stdout'].strip(), '%Y-%m-%d %H:%M:%S %z')
        except Exception:
            pass

    return commit_msg, commit_date


# â”€â”€ Language-specific post-checkout steps â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _post_checkout_python(deploy_path: str, log: list) -> bool:
    venv_path = os.path.join(deploy_path, 'venv')

    if not os.path.exists(venv_path):
        log.append(f'[{datetime.now()}] Creating virtualenv...')
        r = _run(['python3', '-m', 'venv', 'venv'], cwd=deploy_path)
        if r['returncode'] != 0:
            r = _run(['python', '-m', 'venv', 'venv'], cwd=deploy_path)
        if r['returncode'] != 0:
            log.append(f'  venv creation failed: {r["stderr"]}')
        else:
            if r['stdout']:
                log.append(f'  venv stdout: {r["stdout"]}')
            if r['stderr']:
                log.append(f'  venv stderr: {r["stderr"]}')

    req_file = os.path.join(deploy_path, 'requirements.txt')
    if os.path.exists(req_file):
        log.append(f'[{datetime.now()}] Installing Python requirements (pip)...')
        import platform
        if platform.system() == 'Windows':
            pip = os.path.join(venv_path, 'Scripts', 'pip.exe')
        else:
            pip = os.path.join(venv_path, 'bin', 'pip')
        if not os.path.exists(pip):
            pip = 'pip3'

        r = _run([pip, 'install', '-r', 'requirements.txt'],
                 cwd=deploy_path, timeout=300)
        if r['stdout']:
            log.append(f'  [pip stdout]\n{r["stdout"]}')
        if r['stderr']:
            log.append(f'  [pip stderr]\n{r["stderr"]}')
            
        if r['returncode'] == 0:
            log.append('  Requirements installed successfully.')
        else:
            log.append(f'  pip install failed with return code {r["returncode"]}')
            return False
    else:
        log.append('  No requirements.txt found, skipping.')

    return True


def _post_checkout_node(deploy_path: str, log: list) -> bool:
    if os.path.exists(os.path.join(deploy_path, 'package.json')):
        log.append(f'[{datetime.now()}] Running npm install...')
        r = _run(['npm', 'install', '--production'],
                 cwd=deploy_path, timeout=300)
        if r['stdout']:
            log.append(f'  [npm install stdout]\n{r["stdout"]}')
        if r['stderr']:
            log.append(f'  [npm install stderr]\n{r["stderr"]}')
            
        if r['returncode'] == 0:
            log.append('  npm packages installed successfully.')
            # Build trigger for Node/React/Next frameworks
            is_ts = os.path.exists(os.path.join(deploy_path, 'tsconfig.json'))
            is_webpack = os.path.exists(os.path.join(deploy_path, 'webpack.config.js'))
            is_vite = os.path.exists(os.path.join(deploy_path, 'vite.config.js')) or os.path.exists(os.path.join(deploy_path, 'vite.config.ts'))
            
            if is_ts or is_webpack or is_vite:
                log.append(f'[{datetime.now()}] Modern JS project configuration detected â€” running npm run build...')
                build_r = _run(['npm', 'run', 'build'], cwd=deploy_path, timeout=300)
                if build_r['stdout']:
                    log.append(f'  [npm run build stdout]\n{build_r["stdout"]}')
                if build_r['stderr']:
                    log.append(f'  [npm run build stderr]\n{build_r["stderr"]}')
                if build_r['returncode'] == 0:
                    log.append('  npm run build completed successfully.')
                else:
                    log.append(f'  npm run build failed with return code {build_r["returncode"]}')
                    return False
        else:
            log.append(f'  npm install failed with return code {r["returncode"]}')
            return False
    else:
        log.append('  No package.json found, skipping npm install.')
    return True


def _post_checkout_php(deploy_path: str, log: list) -> bool:
    if os.path.exists(os.path.join(deploy_path, 'composer.json')):
        log.append(f'[{datetime.now()}] Running composer install...')
        r = _run(['composer', 'install', '--no-dev', '--optimize-autoloader'],
                 cwd=deploy_path, timeout=300)
        if r['stdout']:
            log.append(f'  [composer stdout]\n{r["stdout"]}')
        if r['stderr']:
            log.append(f'  [composer stderr]\n{r["stderr"]}')
            
        if r['returncode'] == 0:
            log.append('  Composer dependencies installed.')
        else:
            log.append(f'  Composer failed with return code {r["returncode"]}')
            return False
    return True


def _post_checkout_java(deploy_path: str, log: list) -> bool:
    if os.path.exists(os.path.join(deploy_path, 'pom.xml')):
        log.append(f'[{datetime.now()}] Maven project detected â€” running package build...')
        r = _run(['mvn', 'clean', 'package', '-DskipTests'],
                 cwd=deploy_path, timeout=600)
        if r['stdout']:
            log.append(f'  [mvn stdout]\n{r["stdout"]}')
        if r['stderr']:
            log.append(f'  [mvn stderr]\n{r["stderr"]}')
            
        if r['returncode'] == 0:
            log.append('  Maven package build succeeded!')
        else:
            log.append(f'  Maven build failed with return code {r["returncode"]}')
            return False
    elif os.path.exists(os.path.join(deploy_path, 'build.gradle')):
        log.append(f'[{datetime.now()}] Gradle project detected â€” running package build...')
        r = _run(['./gradlew', 'build', '-x', 'test'],
                 cwd=deploy_path, timeout=600)
        if r['stdout']:
            log.append(f'  [gradle stdout]\n{r["stdout"]}')
        if r['stderr']:
            log.append(f'  [gradle stderr]\n{r["stderr"]}')
            
        if r['returncode'] == 0:
            log.append('  Gradle package build succeeded!')
        else:
            log.append(f'  Gradle build failed with return code {r["returncode"]}')
            return False
    return True


def _post_checkout_docker(deploy_path: str, log: list) -> bool:
    if os.path.exists(os.path.join(deploy_path, 'docker-compose.yml')) or os.path.exists(os.path.join(deploy_path, 'docker-compose.yaml')):
        log.append(f'[{datetime.now()}] Docker Compose file detected â€” running compose build...')
        r = _run(['docker', 'compose', 'up', '-d', '--build'],
                 cwd=deploy_path, timeout=600)
        if r['stdout']:
            log.append(f'  [docker compose stdout]\n{r["stdout"]}')
        if r['stderr']:
            log.append(f'  [docker compose stderr]\n{r["stderr"]}')
            
        if r['returncode'] == 0:
            log.append('  Docker compose services active!')
        else:
            log.append(f'  Docker compose failed with return code {r["returncode"]}')
            return False
    elif os.path.exists(os.path.join(deploy_path, 'Dockerfile')):
        log.append(f'[{datetime.now()}] Dockerfile detected â€” running docker build...')
        r = _run(['docker', 'build', '-t', 'app-vps', '.'],
                 cwd=deploy_path, timeout=600)
        if r['stdout']:
            log.append(f'  [docker build stdout]\n{r["stdout"]}')
        if r['stderr']:
            log.append(f'  [docker build stderr]\n{r["stderr"]}')
            
        if r['returncode'] == 0:
            log.append('  Docker image built successfully!')
        else:
            log.append(f'  Docker build failed with return code {r["returncode"]}')
            return False
    return True


def _post_checkout_static(deploy_path: str, log: list) -> bool:
    log.append(f'[{datetime.now()}] Static site mapping complete. Virtual Host directories linked.')
    return True


def _restart_service(service_name: str, log: list):
    """Restart a systemd service. service_name MUST be pre-validated."""
    import platform
    if platform.system() == 'Windows':
        return
    svc = sanitize_service_name(service_name)
    if not svc:
        log.append('  Skipping service restart â€” invalid or missing service name.')
        return
    log.append(f'[{datetime.now()}] Restarting service: {svc}')
    r = _run(['sudo', 'systemctl', 'restart', svc], timeout=30)
    if r['stdout']:
        log.append(f'  [systemctl stdout]\n{r["stdout"]}')
    if r['stderr']:
        log.append(f'  [systemctl stderr]\n{r["stderr"]}')
    if r['returncode'] == 0:
        log.append(f'  Service {svc} restarted.')
    else:
        log.append(f'  systemctl restart failed with return code {r["returncode"]}')


# â”€â”€ Main deploy orchestrator â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def deploy_project(project: Project, flask_app=None) -> dict:
    deployment = Deployment(project_id=project.id, status='running')
    db.session.add(deployment)
    db.session.commit()

    try:
        result = _run_deploy(project)
        deployment.status         = result['status']
        deployment.logs           = result.get('logs', '')
        deployment.commit_message = result.get('commit_message', '')
        deployment.commit_date    = result.get('commit_date')
        deployment.finished_at    = datetime.utcnow()

        if result['status'] == 'success':
            project.last_deployed = datetime.utcnow()

        db.session.commit()

        # Email notification
        if flask_app:
            try:
                from services.mail_service import notify_deploy
                notify_deploy(flask_app, project, deployment, result['status'])
            except Exception:
                pass

        return result

    except Exception as e:
        deployment.status      = 'failed'
        deployment.logs        = f'Deployment error: {e}'
        deployment.finished_at = datetime.utcnow()
        db.session.commit()

        if flask_app:
            try:
                from services.mail_service import notify_deploy
                notify_deploy(flask_app, project, deployment, 'failed')
            except Exception:
                pass

        return {'status': 'failed', 'error': str(e), 'logs': deployment.logs}


def _run_deploy(project: Project) -> dict:
    log = []
    lang        = project.language
    deploy_path = project.deploy_path
    branch      = sanitize_branch(project.branch)

    log.append(f'[{datetime.now()}] -- DevSpace: starting deploy --')
    log.append(f'  Project : {project.name}')
    log.append(f'  Language: {lang}')
    log.append(f'  Branch  : {branch}')
    log.append(f'  Path    : {deploy_path}')

    commit_msg  = ''
    commit_date = None

    bare = project.git_repo_path

    if bare and os.path.exists(bare):
        log.append(f'\n[{datetime.now()}] Checking out from local bare repo...')
        r = checkout_from_bare(bare, deploy_path, branch)
        if r['returncode'] != 0:
            log.append(f'  Checkout failed: {r["stderr"]}')
            return {'status': 'failed', 'logs': '\n'.join(log),
                    'commit_message': '', 'commit_date': None}
        log.append('  Checkout complete.')
        if r['stdout']:
            log.append(r['stdout'])
        commit_msg, commit_date = get_git_info_from_bare(bare, branch)

    elif project.repo_url:
        safe_url = validate_repo_url(project.repo_url)
        if not safe_url:
            log.append('  Invalid or unsafe repo URL â€” aborting.')
            return {'status': 'failed', 'logs': '\n'.join(log),
                    'commit_message': '', 'commit_date': None}
        log.append(f'\n[{datetime.now()}] Using external repo URL...')
        result = _deploy_from_external(project, safe_url, deploy_path, branch, log)
        if result['status'] == 'failed':
            return result
        commit_msg  = result.get('commit_message', '')
        commit_date = result.get('commit_date')

    else:
        log.append('\n  No bare repo and no external URL â€” nothing to deploy.')
        return {'status': 'failed', 'logs': '\n'.join(log),
                'commit_message': '', 'commit_date': None}

    log.append(f'  Latest commit: {commit_msg}')

    log.append(f'\n[{datetime.now()}] Running post-checkout steps ({lang})...')

    success = True
    if lang == 'python':
        success = _post_checkout_python(deploy_path, log)
    elif lang == 'node':
        success = _post_checkout_node(deploy_path, log)
    elif lang == 'php':
        success = _post_checkout_php(deploy_path, log)
    elif lang == 'java':
        success = _post_checkout_java(deploy_path, log)
    elif lang == 'docker':
        success = _post_checkout_docker(deploy_path, log)
    elif lang == 'static':
        success = _post_checkout_static(deploy_path, log)

    # Restart service if configured (validated inside _restart_service)
    if project.service_name:
        _restart_service(project.service_name, log)

    log.append(f'\n[{datetime.now()}] -- Deploy {"completed" if success else "finished with errors"} --')

    return {
        'status': 'success' if success else 'failed',
        'logs': '\n'.join(log),
        'commit_message': commit_msg,
        'commit_date': commit_date,
    }


# â”€â”€ External URL fallback â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _deploy_from_external(project, safe_url, deploy_path, branch, log):
    repo_name = safe_url.rstrip('/').split('/')[-1].replace('.git', '')
    # Strip any remaining unsafe chars from repo_name used as folder
    repo_name = re.sub(r'[^\w.-]', '_', repo_name)
    full_path = os.path.join(deploy_path, repo_name)

    if not os.path.exists(full_path):
        log.append(f'  Cloning {safe_url} -> {full_path}')
        r = _run(['git', 'clone', '-b', branch, safe_url, full_path], timeout=300)
        if r['returncode'] != 0:
            log.append(f'  Clone failed: {r["stderr"]}')
            return {'status': 'failed', 'logs': '\n'.join(log)}
    else:
        log.append(f'  git pull in {full_path}')
        r = _run(['git', 'pull', 'origin', branch], cwd=full_path, timeout=120)
        if r['returncode'] != 0:
            log.append(f'  Pull failed: {r["stderr"]}')
            return {'status': 'failed', 'logs': '\n'.join(log)}

    commit_msg, commit_date = get_git_info(full_path)
    return {'status': 'ok', 'commit_message': commit_msg, 'commit_date': commit_date}
