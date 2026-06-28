import subprocess
from services.ssh_service import execute_ssh_command

def generate_nginx_config(domain_name, target_port, redirect_ssl=True) -> str:
    """Generate a clean, secure Nginx reverse proxy configuration."""
    cfg = f"""server {{
    listen 80;
    server_name {domain_name};

    location / {{
        proxy_pass http://127.0.0.1:{target_port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSockets support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }}
}}
"""
    return cfg

def _execute_nginx_command(server, command) -> dict:
    if not server or server.ip in ('localhost', '127.0.0.1'):
        try:
            r = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=30
            )
            return {'success': r.returncode == 0, 'stdout': r.stdout, 'stderr': r.stderr}
        except Exception as e:
            return {'success': False, 'stdout': '', 'stderr': str(e)}
    else:
        return execute_ssh_command(
            ip=server.ip,
            port=server.ssh_port,
            username=server.username,
            command=command,
            password_enc=server.password_enc,
            ssh_key_enc=server.ssh_key_enc
        )

def configure_nginx_vhost(server, domain_name, target_port, redirect_ssl=True) -> dict:
    """Setup and reload Nginx configuration for a domain."""
    config_content = generate_nginx_config(domain_name, target_port, redirect_ssl)
    
    # Prepare shell script to write and enable Nginx config on the target server
    # Escaping config content properly
    escaped_config = config_content.replace('"', '\\"').replace('$', '\\$')
    
    setup_script = f"""
cat << 'EOF' > /tmp/{domain_name}.conf
{config_content}
EOF
sudo mv /tmp/{domain_name}.conf /etc/nginx/sites-available/{domain_name}
sudo ln -sf /etc/nginx/sites-available/{domain_name} /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
"""
    res = _execute_nginx_command(server, setup_script)
    if res['success']:
        return {'success': True, 'config': config_content, 'message': 'Nginx vhost configured successfully!'}
    else:
        return {'success': False, 'config': config_content, 'message': f"Failed to setup Nginx: {res['stderr']}"}

def install_letsencrypt_ssl(server, domain_name, email="uditroy@udeckservices.com") -> dict:
    """Orchestrates SSL via Let's Encrypt."""
    cmd = f"sudo certbot --nginx -d {domain_name} --non-interactive --agree-tos -m {email} --redirect"
    res = _execute_nginx_command(server, cmd)
    return {
        'success': res['success'],
        'message': res['stdout'] if res['success'] else res['stderr']
    }
