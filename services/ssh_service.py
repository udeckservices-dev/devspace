import io
import os
import paramiko
from services.crypto_service import decrypt_data

def test_ssh_connection(ip, port, username, password_enc=None, ssh_key_enc=None) -> dict:
    """Test SSH connection to a remote server. Returns {'success': bool, 'message': str}."""
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        password = decrypt_data(password_enc) if password_enc else None
        ssh_key = decrypt_data(ssh_key_enc) if ssh_key_enc else None
        
        if ssh_key:
            # Try to load private key
            key_file = io.StringIO(ssh_key)
            try:
                pkey = paramiko.RSAKey.from_private_key(key_file)
            except paramiko.ssh_exception.SSHException:
                try:
                    pkey = paramiko.Ed25519Key.from_private_key(key_file)
                except Exception:
                    pkey = paramiko.PKey.from_private_key(key_file)
            ssh.connect(ip, port=int(port), username=username, pkey=pkey, timeout=10)
        elif password:
            ssh.connect(ip, port=int(port), username=username, password=password, timeout=10)
        else:
            return {'success': False, 'message': 'Neither password nor SSH key provided.'}
            
        ssh.close()
        return {'success': True, 'message': 'Successfully connected to server!'}
    except Exception as e:
        return {'success': False, 'message': f'Connection failed: {str(e)}'}

def execute_ssh_command(ip, port, username, command, password_enc=None, ssh_key_enc=None) -> dict:
    """Execute a single remote command via SSH. Returns {'success': bool, 'stdout': str, 'stderr': str}."""
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        password = decrypt_data(password_enc) if password_enc else None
        ssh_key = decrypt_data(ssh_key_enc) if ssh_key_enc else None
        
        if ssh_key:
            key_file = io.StringIO(ssh_key)
            try:
                pkey = paramiko.RSAKey.from_private_key(key_file)
            except Exception:
                pkey = paramiko.Ed25519Key.from_private_key(key_file)
            ssh.connect(ip, port=int(port), username=username, pkey=pkey, timeout=15)
        elif password:
            ssh.connect(ip, port=int(port), username=username, password=password, timeout=15)
        else:
            return {'success': False, 'stdout': '', 'stderr': 'No authentication credentials provided.'}
            
        stdin, stdout, stderr = ssh.exec_command(command, timeout=300)
        exit_status = stdout.channel.recv_exit_status()
        
        out_str = stdout.read().decode('utf-8', errors='replace')
        err_str = stderr.read().decode('utf-8', errors='replace')
        
        ssh.close()
        return {
            'success': exit_status == 0,
            'stdout': out_str,
            'stderr': err_str
        }
    except Exception as e:
        return {'success': False, 'stdout': '', 'stderr': f'SSH Execution Error: {str(e)}'}

def generate_key_pair() -> dict:
    """Generate a new RSA public and private key pair for deployment."""
    key_out = io.StringIO()
    pkey = paramiko.RSAKey.generate(2048)
    pkey.write_private_key(key_out)
    private_key = key_out.getvalue()
    public_key = f"{pkey.get_name()} {pkey.get_base64()}"
    return {
        'private_key': private_key,
        'public_key': public_key
    }

def scan_server_environment(server) -> dict:
    """Connect to the VPS and auto-detect panels (CyberPanel/cPanel) and web servers (LiteSpeed, Apache, Nginx)."""
    # 1. Panel Check
    panel_cmd = "[ -d /usr/local/lscp ] && echo 'CyberPanel' || ( [ -d /usr/local/cpanel ] && echo 'cPanel' || echo 'None' )"
    res_panel = execute_ssh_command(
        ip=server.ip,
        port=server.ssh_port,
        username=server.username,
        command=panel_cmd,
        password_enc=server.password_enc,
        ssh_key_enc=server.ssh_key_enc
    )
    
    panel = res_panel['stdout'].strip() if res_panel['success'] else 'None'
    # Sanitize case of panel
    if 'cyberpanel' in panel.lower():
        panel = 'CyberPanel'
    elif 'cpanel' in panel.lower():
        panel = 'cPanel'
    else:
        panel = 'None'
        
    # 2. Web Server Process Check
    proc_cmd = "ps aux | grep -iE 'openlitespeed|lsws|nginx|httpd|apache' | grep -v grep"
    res_proc = execute_ssh_command(
        ip=server.ip,
        port=server.ssh_port,
        username=server.username,
        command=proc_cmd,
        password_enc=server.password_enc,
        ssh_key_enc=server.ssh_key_enc
    )
    
    web_server = 'Unknown'
    if res_proc['success'] and res_proc['stdout'].strip():
        stdout_lower = res_proc['stdout'].lower()
        if 'openlitespeed' in stdout_lower or 'lsws' in stdout_lower or 'lscpd' in stdout_lower:
            web_server = 'OpenLiteSpeed / LiteSpeed'
        elif 'nginx' in stdout_lower:
            web_server = 'Nginx'
        elif 'httpd' in stdout_lower or 'apache' in stdout_lower:
            web_server = 'Apache HTTPD'
            
    return {
        'panel_type': panel,
        'web_server': web_server
    }
