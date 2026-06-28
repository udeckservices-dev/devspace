import json
import subprocess
import platform
from services.ssh_service import execute_ssh_command

def _run_docker_command(server, command) -> dict:
    """Run docker command locally or on a remote VPS server."""
    if not server or server.ip in ('localhost', '127.0.0.1'):
        try:
            # Local execution
            r = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=30
            )
            return {
                'success': r.returncode == 0,
                'stdout': r.stdout,
                'stderr': r.stderr
            }
        except Exception as e:
            return {'success': False, 'stdout': '', 'stderr': str(e)}
    else:
        # Remote execution via SSH
        return execute_ssh_command(
            ip=server.ip,
            port=server.ssh_port,
            username=server.username,
            command=command,
            password_enc=server.password_enc,
            ssh_key_enc=server.ssh_key_enc
        )

def list_containers(server) -> list:
    """List Docker containers on a given server."""
    cmd = "docker ps -a --format '{{json .}}'"
    res = _run_docker_command(server, cmd)
    if not res['success']:
        return []
    
    containers = []
    for line in res['stdout'].splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            containers.append(json.loads(line))
        except Exception:
            pass
    return containers

def manage_container(server, container_id, action) -> dict:
    """Start, stop, or restart a container."""
    if action not in ('start', 'stop', 'restart', 'rm'):
        return {'success': False, 'message': 'Invalid container action'}
    cmd = f"docker {action} {container_id}"
    res = _run_docker_command(server, cmd)
    return {
        'success': res['success'],
        'message': res['stdout'] if res['success'] else res['stderr']
    }

def get_container_logs(server, container_id) -> str:
    """Fetch logs from a container."""
    cmd = f"docker logs --tail 200 {container_id}"
    res = _run_docker_command(server, cmd)
    return res['stdout'] if res['success'] else res['stderr']

def list_images(server) -> list:
    """List docker images."""
    cmd = "docker images --format '{{json .}}'"
    res = _run_docker_command(server, cmd)
    if not res['success']:
        return []
    
    images = []
    for line in res['stdout'].splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            images.append(json.loads(line))
        except Exception:
            pass
    return images

def list_volumes(server) -> list:
    """List docker volumes."""
    cmd = "docker volume ls --format '{{json .}}'"
    res = _run_docker_command(server, cmd)
    if not res['success']:
        return []
    
    volumes = []
    for line in res['stdout'].splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            volumes.append(json.loads(line))
        except Exception:
            pass
    return volumes
